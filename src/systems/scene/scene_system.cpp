#include <corona/events/engine_events.h>
#include <corona/kernel/core/i_logger.h>
#include <corona/shared_data_hub.h>
#include <corona/kernel/utils/storage.h>
#include <corona/spatial/octree.h>
#include <corona/systems/scene/scene_system.h>

#include <mutex>
#include <shared_mutex>
#include <unordered_map>
#include <unordered_set>

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
        std::unordered_map<Payload,ActorLoadState>          actor_load_states;
    };

    mutable std::shared_mutex                               mtx;
    std::unordered_map<std::uintptr_t /*scene*/, SceneState> scenes;
    std::unordered_map<Payload, bool>                       offline_actors;
    std::vector<Kernel::EventId>                            event_subscriptions;
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
    auto& scene_storage = hub.scene_storage();
    auto& camera_storage = hub.camera_storage();
    std::vector<std::uintptr_t> scene_handles;
    {
        for (auto it = scene_storage.cbegin(); it != scene_storage.cend(); ++it) {
            const SceneDevice& scene_dev = *it;
            scene_handles.push_back(reinterpret_cast<std::uintptr_t>(&scene_dev));
        }
    }

    for (std::uintptr_t scene_handle : scene_handles) {
        std::vector<std::uintptr_t> actor_handles;
        std::vector<std::uintptr_t> camera_handles;
        {
            auto scene_read = scene_storage.try_acquire_read(scene_handle);
            if ( !scene_read.valid() )  continue;
            actor_handles = scene_read->actor_handles;
            camera_handles = scene_read->camera_handles;
        }

        std::vector<typename Spatial::Octree<Impl::Payload>::Entry> octree_entries;

        for (std::uintptr_t actor_handle : actor_handles) {
            auto& actor_storage = hub.actor_storage();
            auto actor_read = actor_storage.try_acquire_read(actor_handle);
            if ( !actor_read ) continue;
            const ActorDevice& actor_dev = *actor_read;

            for (std::uintptr_t profile_handle : actor_dev.profile_handles) {
                auto& profile_storage = hub.profile_storage();
                auto profile_read = profile_storage.try_acquire_read(profile_handle);
                if (!profile_read.valid()) continue;
                const ProfileDevice& profile_dev = *profile_read;

                std::uintptr_t mechanics_handle = profile_dev.mechanics_handle;
                if ( !mechanics_handle ) continue;

                auto& mechanics_storage = hub.mechanics_storage();
                auto mechanics_read = mechanics_storage.try_acquire_read(mechanics_handle);
                if (!mechanics_read.valid()) continue;
                const MechanicsDevice& mechanics_dev = *mechanics_read;

                Spatial::AABB aabb;
                aabb.min = mechanics_dev.min_xyz;
                aabb.max = mechanics_dev.max_xyz;
                octree_entries.push_back({actor_handle,aabb});
            }
        }

        Spatial::AABB root_aabb;
        if ( !octree_entries.empty() ) {
            root_aabb = octree_entries[0].bounds;
            for (const auto& entry : octree_entries) {
                root_aabb = root_aabb.merged(entry.bounds);
            }
            ktm::fvec3 extent = root_aabb.extent();

            //padding 添加10%的内边距
            float max_extent = std::max({extent.x,extent.y,extent.z});
            float padding = max_extent * 0.1f;
            root_aabb = root_aabb.expanded(padding);
        }else {
            root_aabb.min = ktm::fvec3{-1.0f, -1.0f, -1.0f};
            root_aabb.max = ktm::fvec3{1.0f, 1.0f, 1.0f};
        }

        {
            std::unique_lock lock(impl_->mtx);
            impl_->get_or_create(scene_handle).tree.rebuild(root_aabb,octree_entries);
        }

        std::unordered_set<Impl::Payload> visible_actors;
        for (std::uintptr_t camera_handle : camera_handles) {
            auto cam_read = camera_storage.try_acquire_read(camera_handle);
            if ( !cam_read.valid() ) continue;

            std::vector<Impl::Payload> visible_for_camera = query_visible_for_camera(scene_handle,camera_handle);
            visible_actors.insert(visible_for_camera.begin(),visible_for_camera.end());
        }

        {
            std::unique_lock lock(impl_->mtx);
            Impl::SceneState& scene_state = impl_->get_or_create(scene_handle);

            for (std::uintptr_t actor_handle : actor_handles) {
                if ( visible_actors.count(actor_handle) ) {
                    scene_state.invisible_frames[actor_handle] = 0;
                }else {
                    uint32_t cnt = ++scene_state.invisible_frames[actor_handle];

                    if ( scene_state.invisible_frames[actor_handle] >= static_cast<uint32_t>(scene_state.cfg.invisible_frames_to_evict) ) {
                        if ( impl_->ctx && impl_->ctx->event_bus()) {
                            Events::ActorEvictRequestedEvent evict_event{actor_handle};
                            impl_->ctx->event_bus()->publish(evict_event);

                            CFW_LOG_NOTICE("SceneSystem: Evict requested for actor {} (invisible {} frames)",
                                   actor_handle, cnt);
                        }
                        scene_state.invisible_frames[actor_handle] = 0;
                    }
                }
            }

            scene_state.stats.actor_total = actor_handles.size();
            scene_state.stats.actor_visible = visible_actors.size();
            scene_state.stats.octree_entries = octree_entries.size();
        }

        auto scene_write = scene_storage.try_acquire_write(scene_handle);
        if (scene_write.valid()) {
            SceneDevice& scene_dev_write = *scene_write;
            scene_dev_write.min_world = root_aabb.min;
            scene_dev_write.max_world = root_aabb.max;
            scene_dev_write.center_world = root_aabb.center();
        }
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
// 查询接口（骨架：返回空集；保持线程安全）(已实现)
// ============================================================================

std::vector<std::uintptr_t> SceneSystem::query_aabb(
    std::uintptr_t scene, const Spatial::AABB& box) const {
    std::shared_lock lock(impl_->mtx);
    std::vector<std::uintptr_t> out;

    auto it = impl_->scenes.find(scene);
    if (it == impl_->scenes.end() || it->second.tree.empty()) {
        return out;
    }

    out.reserve(it->second.tree.size() / 2);
    it->second.tree.query_aabb(box, out);

    return out;
}

std::vector<std::uintptr_t> SceneSystem::query_sphere(
    std::uintptr_t scene, const ktm::fvec3& center, float radius) const {
    std::shared_lock lock(impl_->mtx);
    std::vector<std::uintptr_t> out;

    auto it = impl_->scenes.find(scene);
    if (it == impl_->scenes.end() || it->second.tree.empty()) {
        return out;
    }

    out.reserve(it->second.tree.size() / 2);
    it->second.tree.query_sphere(center, radius, out);

    return out;
}

std::vector<std::uintptr_t> SceneSystem::query_frustum(
    std::uintptr_t scene, const Math::Frustum& frustum) const {
    std::shared_lock lock(impl_->mtx);
    std::vector<std::uintptr_t> out;

    auto it = impl_->scenes.find(scene);
    if (it == impl_->scenes.end() || it->second.tree.empty()) {
       return out;
    }

    out.reserve(it->second.tree.size() / 2);
    it->second.tree.query_if(
        [&](const Spatial::AABB& b) { return frustum.intersects(b); }, out);

    return out;
}

std::vector<std::pair<std::uintptr_t, std::uintptr_t>> SceneSystem::query_pairs(
    std::uintptr_t scene) const {
    std::shared_lock lock(impl_->mtx);
    std::vector<std::pair<std::uintptr_t, std::uintptr_t>> out;

    auto it = impl_->scenes.find(scene);
    if (it == impl_->scenes.end() || it->second.tree.size() < 2) {
        return out;
    }

    std::size_t n = it->second.tree.size();
    out.reserve(n * (n - 1) / 4); // 保守估计，实际碰撞对通常远小于最大值
    it->second.tree.collect_pairs(out);

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
