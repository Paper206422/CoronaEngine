#include <corona/events/engine_events.h>
#include <corona/kernel/core/i_logger.h>
#include <corona/shared_data_hub.h>
#include <corona/spatial/octree.h>
#include <corona/systems/scene/scene_system.h>

#include <algorithm>
#include <mutex>
#include <shared_mutex>
#include <unordered_map>

namespace Corona::Systems {

// ============================================================================
// SceneSystem::Impl —— 私有状态
//
// 当前为骨架（M1.0）：仅维护数据结构与读写锁，所有查询返回空集。
// 后续 M1 阶段会在 update() 中读取 SharedDataHub 重建八叉树，
// 公共接口保持不变。
// ============================================================================

struct SceneSystem::Impl {
    using Payload = std::uintptr_t;

    struct SceneState {
        Spatial::Octree<Payload>                            tree;
        std::unordered_map<Payload, std::uint32_t>          invisible_frames;
        SceneVisibilityConfig                               cfg;
        SceneStats                                          stats;
    };

    mutable std::shared_mutex                               mtx;
    std::unordered_map<std::uintptr_t /*scene*/, SceneState> scenes;
    std::unordered_map<Payload, bool>                       offline_actors;
    Kernel::ISystemContext*                                 ctx = nullptr;

    SceneState& get_or_create(std::uintptr_t scene) {
        auto [it, inserted] = scenes.try_emplace(scene);
        return it->second;
    }
};

// ============================================================================
// 生命周期
// ============================================================================

SceneSystem::SceneSystem() : impl_(std::make_unique<Impl>()) {
    set_target_fps(60);
}

SceneSystem::~SceneSystem() = default;

bool SceneSystem::initialize(Kernel::ISystemContext* ctx) {
    impl_->ctx = ctx;
    CFW_LOG_NOTICE("SceneSystem: Initializing (skeleton, queries return empty)");
    return true;
}

void SceneSystem::update() {
    auto& hub = SharedDataHub::instance();
    auto& scene_storage     = hub.scene_storage();
    auto& actor_storage     = hub.actor_storage();
    auto& profile_storage   = hub.profile_storage();
    auto& mechanics_storage = hub.mechanics_storage();
    auto& geometry_storage  = hub.geometry_storage();
    auto& transform_storage = hub.model_transform_storage();

    // ================================================================
    // Phase 1：只读遍历 scene → actor → profile → mechanics → geometry → transform
    //          将局部 (min_xyz, max_xyz) 通过 ModelTransform 变换到世界 AABB
    //          收集为 Octree::Entry 列表
    //
    //          注意：此阶段只持有 Storage 的 shared_lock(读)，
    //          避免在下阶段获取 unique_lock(写) 时发生死锁。
    // ================================================================
    struct SceneBuildData {
        std::uintptr_t                                      key;
        std::vector<Spatial::Octree<Impl::Payload>::Entry> entries;
        std::size_t                                         actor_count = 0;
    };
    std::vector<SceneBuildData> build_list;

    for (const auto& scene : scene_storage) {
        if (!scene.enabled) continue;

        SceneBuildData bd;
        bd.key         = reinterpret_cast<std::uintptr_t>(&scene);
        bd.actor_count = scene.actor_handles.size();
        bd.entries.reserve(scene.actor_handles.size());

        for (auto actor_handle : scene.actor_handles) {
            auto actor = actor_storage.acquire_read(actor_handle);
            if (!actor) continue;

            // ActorDevice → ProfileDevice → MechanicsDevice → GeometryDevice → ModelTransform
            // 一个 actor 可能有多个含 mechanics 的 profile，合并所有 world AABB 为一个条目
            bool has_any_mech = false;
            Spatial::AABB actor_world_box{};

            for (auto profile_handle : actor->profile_handles) {
                auto profile = profile_storage.acquire_read(profile_handle);
                if (!profile || profile->mechanics_handle == 0) continue;

                auto mech = mechanics_storage.acquire_read(profile->mechanics_handle);
                if (!mech || !mech->physics_enabled) continue;

                auto geom = geometry_storage.acquire_read(mech->geometry_handle);
                if (!geom) continue;

                auto tx = transform_storage.acquire_read(geom->transform_handle);
                if (!tx) continue;

                // 将局部 AABB 的 8 个角点变换到世界空间，取 min/max 包络
                ktm::fmat4x4 M = tx->compute_matrix();
                auto to_world = [&M](const ktm::fvec3& local) -> ktm::fvec3 {
                    ktm::fvec4 h{local.x, local.y, local.z, 1.0f};
                    ktm::fvec4 w = M * h;
                    return ktm::fvec3{w.x, w.y, w.z};
                };

                const ktm::fvec3& lmin = mech->min_xyz;
                const ktm::fvec3& lmax = mech->max_xyz;

                // 局部 AABB 的 8 个角点：min/max 各分量组合 → 世界空间 → 取包络
                ktm::fvec3 corners[8] = {
                    {lmin.x, lmin.y, lmin.z}, {lmax.x, lmin.y, lmin.z},
                    {lmin.x, lmax.y, lmin.z}, {lmax.x, lmax.y, lmin.z},
                    {lmin.x, lmin.y, lmax.z}, {lmax.x, lmin.y, lmax.z},
                    {lmin.x, lmax.y, lmax.z}, {lmax.x, lmax.y, lmax.z},
                };
                Spatial::AABB world_box;
                ktm::fvec3 wp0 = to_world(corners[0]);
                world_box.min = wp0;
                world_box.max = wp0;
                for (int i = 1; i < 8; ++i) {
                    ktm::fvec3 wp = to_world(corners[i]);
                    world_box.min.x = std::min(world_box.min.x, wp.x);
                    world_box.min.y = std::min(world_box.min.y, wp.y);
                    world_box.min.z = std::min(world_box.min.z, wp.z);
                    world_box.max.x = std::max(world_box.max.x, wp.x);
                    world_box.max.y = std::max(world_box.max.y, wp.y);
                    world_box.max.z = std::max(world_box.max.z, wp.z);
                }

                // 合并当前 profile 的世界 AABB 到 actor 的总包围盒
                actor_world_box = has_any_mech
                    ? actor_world_box.merged(world_box)
                    : world_box;
                has_any_mech = true;
            }

            if (has_any_mech) {
                // payload = actor_handle
                bd.entries.push_back({actor_handle, actor_world_box});
            }
        }

        build_list.push_back(std::move(bd));
    }

    // ================================================================
    // Phase 2：写阶段 —— 此时所有读锁已释放，安全获取 unique_lock
    //          合并世界 AABB 得到 root，重建八叉树，写回 SceneDevice
    // ================================================================
    std::unique_lock lock(impl_->mtx);

    for (auto& bd : build_list) {
        auto& state = impl_->get_or_create(bd.key);

        if (bd.entries.empty()) {
            state.tree.clear();
            continue;
        }

        //合并所有 actor 世界 AABB 得到场景根包围盒
        Spatial::AABB root = bd.entries[0].bounds;
        for (std::size_t i = 1; i < bd.entries.size(); ++i) {
            root = root.merged(bd.entries[i].bounds);
        }
        root = root.expanded(state.tree.config().root_padding);

        state.tree.rebuild(root, bd.entries);

        // 写回 SceneDevice
        if (auto s_w = scene_storage.acquire_write(bd.key)) {
            s_w->min_world    = root.min;
            s_w->max_world    = root.max;
            s_w->center_world = root.center();
        }

        state.stats.actor_total    = bd.actor_count;
        state.stats.octree_entries = bd.entries.size();
    }
}

void SceneSystem::shutdown() {
    CFW_LOG_NOTICE("SceneSystem: Shutting down...");
    std::unique_lock lock(impl_->mtx);
    impl_->scenes.clear();
    impl_->offline_actors.clear();
}

// ============================================================================
// 配置
// ============================================================================

void SceneSystem::set_visibility_config(std::uintptr_t scene, SceneVisibilityConfig cfg) {
    std::unique_lock lock(impl_->mtx);
    impl_->get_or_create(scene).cfg = cfg;
}

// ============================================================================
// 查询接口（骨架：返回空集；保持线程安全）
// ============================================================================

std::vector<std::uintptr_t> SceneSystem::query_aabb(
    std::uintptr_t scene, const Spatial::AABB& box) const {
    std::shared_lock lock(impl_->mtx);
    std::vector<std::uintptr_t> out;
    auto it = impl_->scenes.find(scene);
    if (it != impl_->scenes.end()) {
        it->second.tree.query_aabb(box, out);
    }
    return out;
}

std::vector<std::uintptr_t> SceneSystem::query_sphere(
    std::uintptr_t scene, const ktm::fvec3& center, float radius) const {
    std::shared_lock lock(impl_->mtx);
    std::vector<std::uintptr_t> out;
    auto it = impl_->scenes.find(scene);
    if (it != impl_->scenes.end()) {
        it->second.tree.query_sphere(center, radius, out);
    }
    return out;
}

std::vector<std::uintptr_t> SceneSystem::query_frustum(
    std::uintptr_t scene, const Math::Frustum& frustum) const {
    std::shared_lock lock(impl_->mtx);
    std::vector<std::uintptr_t> out;
    auto it = impl_->scenes.find(scene);
    if (it != impl_->scenes.end()) {
        it->second.tree.query_if(
            [&](const Spatial::AABB& b) { return frustum.intersects(b); }, out);
    }
    return out;
}

std::vector<std::pair<std::uintptr_t, std::uintptr_t>> SceneSystem::query_pairs(
    std::uintptr_t scene) const {
    std::shared_lock lock(impl_->mtx);
    std::vector<std::pair<std::uintptr_t, std::uintptr_t>> out;
    auto it = impl_->scenes.find(scene);
    if (it != impl_->scenes.end()) {
        it->second.tree.collect_pairs(out);
    }
    return out;
}

std::vector<std::uintptr_t> SceneSystem::query_visible_for_camera(
    std::uintptr_t scene, std::uintptr_t camera) const {
    auto& cam_storage = SharedDataHub::instance().camera_storage();
    auto cam_handle = cam_storage.try_acquire_read(camera);
    if (!cam_handle.valid()) {
        return {};
    }
    const auto frustum = Math::Frustum::from_camera(*cam_handle);
    return query_frustum(scene, frustum);
}

// ============================================================================
// LRU 协作（占位）
// ============================================================================

bool SceneSystem::is_actor_offline(std::uintptr_t actor) const {
    std::shared_lock lock(impl_->mtx);
    auto it = impl_->offline_actors.find(actor);
    return it != impl_->offline_actors.end() && it->second;
}

void SceneSystem::mark_actor_restored(std::uintptr_t actor) {
    std::unique_lock lock(impl_->mtx);
    impl_->offline_actors[actor] = false;
}

// ============================================================================
// 统计
// ============================================================================

SceneStats SceneSystem::stats(std::uintptr_t scene) const {
    std::shared_lock lock(impl_->mtx);
    auto it = impl_->scenes.find(scene);
    if (it == impl_->scenes.end()) {
        return SceneStats{};
    }
    SceneStats s = it->second.stats;
    s.octree_entries = it->second.tree.size();
    return s;
}

}  // namespace Corona::Systems
