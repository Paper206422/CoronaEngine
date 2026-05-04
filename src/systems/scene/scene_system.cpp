#include <corona/events/engine_events.h>
#include <corona/kernel/core/i_logger.h>
#include <corona/shared_data_hub.h>
#include <corona/spatial/octree.h>
#include <corona/systems/scene/scene_system.h>

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
    // M1.1 TODO:
    //   1) 遍历 SharedDataHub::scene_storage()，对每个 scene：
    //      - 从 actor_handles 出发，沿 ActorDevice → ProfileDevice → MechanicsDevice
    //        读取 (min_xyz, max_xyz)，构造 Octree::Entry 列表；
    //      - 计算 root AABB（merge + padding），调用 tree.rebuild(root, entries)；
    //      - 写回 SceneDevice.{min_world,max_world,center_world}（迁移阶段先不动，
    //        与 MechanicsSystem 重复计算可接受）。
    //   2) 收集本帧所有相机的可见集并集，更新 invisible_frames，按阈值发 Evict 事件。
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
