#include <corona/events/engine_events.h>
#include <corona/kernel/core/i_logger.h>
#include <corona/shared_data_hub.h>
#include <corona/kernel/utils/storage.h>
#include <corona/spatial/octree.h>
#include <corona/systems/scene/scene_system.h>

#include <algorithm>
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
    using OctreeEntry = Spatial::Octree<Payload>::Entry;

    struct SceneState {
        Spatial::Octree<Payload>                            tree;
        std::unordered_map<Payload, std::uint32_t>          invisible_frames;
        SceneVisibilityConfig                               cfg;
        SceneStats                                          stats;
        std::unordered_map<Payload,ActorLoadState>          actor_load_states;
    };

    struct SceneFrameInput {
        Payload scene_handle{};
        std::vector<Payload> actor_handles;
        std::vector<Payload> camera_handles;
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

    [[nodiscard]] const SceneState* find_scene(std::uintptr_t scene) const noexcept {
        auto it = scenes.find(scene);
        return it == scenes.end() ? nullptr : &it->second;
    }

    [[nodiscard]] const Spatial::Octree<Payload>* find_tree(std::uintptr_t scene) const noexcept {
        const SceneState* state = find_scene(scene);
        if (state == nullptr || state->tree.empty()) {
            return nullptr;
        }
        return &state->tree;
    }

    template <typename SceneStorage>
    [[nodiscard]] std::vector<SceneFrameInput> collect_scene_inputs(const SceneStorage& scene_storage) const {
        std::vector<SceneFrameInput> scene_inputs;
        for (auto it = scene_storage.cbegin(); it != scene_storage.cend(); ++it) {
            const SceneDevice& scene_dev = *it;
            SceneFrameInput input;
            input.scene_handle = reinterpret_cast<Payload>(&scene_dev);
            input.actor_handles = scene_dev.actor_handles;
            input.camera_handles = scene_dev.camera_handles;
            scene_inputs.push_back(std::move(input));
        }
        return scene_inputs;
    }

    [[nodiscard]] std::vector<OctreeEntry> build_octree_entries(const std::vector<Payload>& actor_handles) const {
        auto& hub = SharedDataHub::instance();
        auto& actor_storage = hub.actor_storage();
        auto& profile_storage = hub.profile_storage();
        auto& mechanics_storage = hub.mechanics_storage();

        std::vector<OctreeEntry> octree_entries;
        for (Payload actor_handle : actor_handles) {
            auto actor_read = actor_storage.try_acquire_read(actor_handle);
            if (!actor_read) continue;
            const ActorDevice& actor_dev = *actor_read;

            for (Payload profile_handle : actor_dev.profile_handles) {
                auto profile_read = profile_storage.try_acquire_read(profile_handle);
                if (!profile_read.valid()) continue;
                const ProfileDevice& profile_dev = *profile_read;

                Payload mechanics_handle = profile_dev.mechanics_handle;
                if (!mechanics_handle) continue;

                auto mechanics_read = mechanics_storage.try_acquire_read(mechanics_handle);
                if (!mechanics_read.valid()) continue;
                const MechanicsDevice& mechanics_dev = *mechanics_read;

                Spatial::AABB aabb;
                aabb.min = mechanics_dev.min_xyz;
                aabb.max = mechanics_dev.max_xyz;
                octree_entries.push_back({actor_handle, aabb});
            }
        }
        return octree_entries;
    }

    [[nodiscard]] static Spatial::AABB compute_root_aabb(const std::vector<OctreeEntry>& octree_entries) {
        Spatial::AABB root_aabb;
        if (octree_entries.empty()) {
            root_aabb.min = ktm::fvec3{-1.0f, -1.0f, -1.0f};
            root_aabb.max = ktm::fvec3{1.0f, 1.0f, 1.0f};
            return root_aabb;
        }

        root_aabb = octree_entries[0].bounds;
        for (const auto& entry : octree_entries) {
            root_aabb = root_aabb.merged(entry.bounds);
        }

        const ktm::fvec3 extent = root_aabb.extent();
        const float max_extent = std::max(std::max(extent[0], extent[1]), extent[2]);
        return root_aabb.expanded(max_extent * 0.1f);
    }

    void rebuild_scene_tree(std::uintptr_t scene_handle, const Spatial::AABB& root_aabb,
                            const std::vector<OctreeEntry>& octree_entries) {
        std::unique_lock lock(mtx);
        get_or_create(scene_handle).tree.rebuild(root_aabb, octree_entries);
    }

    void update_visibility_state(std::uintptr_t scene_handle,
                                 const std::vector<Payload>& actor_handles,
                                 const std::unordered_set<Payload>& visible_actors,
                                 std::size_t octree_entry_count) {
        std::unique_lock lock(mtx);
        SceneState& scene_state = get_or_create(scene_handle);
        const bool eviction_enabled = scene_state.cfg.invisible_frames_to_evict > 0;
        const auto eviction_threshold = eviction_enabled
                                            ? static_cast<std::uint32_t>(scene_state.cfg.invisible_frames_to_evict)
                                            : 0U;

        for (Payload actor_handle : actor_handles) {
            if (visible_actors.count(actor_handle)) {
                scene_state.invisible_frames[actor_handle] = 0;
                continue;
            }

            const uint32_t invisible_count = ++scene_state.invisible_frames[actor_handle];
            if (!eviction_enabled || invisible_count < eviction_threshold) {
                continue;
            }

            if (ctx && ctx->event_bus()) {
                Events::ActorEvictRequestedEvent evict_event{scene_handle, actor_handle};
                ctx->event_bus()->publish(evict_event);

                CFW_LOG_DEBUG("SceneSystem: Evict requested for actor {} (invisible {} frames)",
                              actor_handle, invisible_count);
            }
            scene_state.invisible_frames[actor_handle] = 0;
        }

        scene_state.stats.actor_total = actor_handles.size();
        scene_state.stats.actor_visible = visible_actors.size();
        scene_state.stats.octree_entries = octree_entry_count;
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
    const std::vector<Impl::SceneFrameInput> scene_inputs = impl_->collect_scene_inputs(scene_storage);

    for (const Impl::SceneFrameInput& scene_input : scene_inputs) {
        const std::uintptr_t scene_handle = scene_input.scene_handle;

        const std::vector<Impl::OctreeEntry> octree_entries = impl_->build_octree_entries(scene_input.actor_handles);
        const Spatial::AABB root_aabb = Impl::compute_root_aabb(octree_entries);
        impl_->rebuild_scene_tree(scene_handle, root_aabb, octree_entries);

        std::unordered_set<Impl::Payload> visible_actors;
        for (std::uintptr_t camera_handle : scene_input.camera_handles) {
            auto cam_read = camera_storage.try_acquire_read(camera_handle);
            if ( !cam_read.valid() ) continue;

            const auto frustum = Math::Frustum::from_camera(*cam_read);
            std::vector<Impl::Payload> visible_for_camera = query_frustum(scene_handle, frustum);
            visible_actors.insert(visible_for_camera.begin(),visible_for_camera.end());
        }

        impl_->update_visibility_state(scene_handle, scene_input.actor_handles, visible_actors, octree_entries.size());

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

    const Spatial::Octree<Impl::Payload>* tree = impl_->find_tree(scene);
    if (tree == nullptr) {
        return out;
    }

    out.reserve(tree->size() / 2);
    tree->query_aabb(box, out);

    return out;
}

std::vector<std::uintptr_t> SceneSystem::query_sphere(
    std::uintptr_t scene, const ktm::fvec3& center, float radius) const {
    std::shared_lock lock(impl_->mtx);
    std::vector<std::uintptr_t> out;

    const Spatial::Octree<Impl::Payload>* tree = impl_->find_tree(scene);
    if (tree == nullptr) {
        return out;
    }

    out.reserve(tree->size() / 2);
    tree->query_sphere(center, radius, out);

    return out;
}

std::vector<std::uintptr_t> SceneSystem::query_frustum(
    std::uintptr_t scene, const Math::Frustum& frustum) const {
    std::shared_lock lock(impl_->mtx);
    std::vector<std::uintptr_t> out;

    const Spatial::Octree<Impl::Payload>* tree = impl_->find_tree(scene);
    if (tree == nullptr) {
       return out;
    }

    out.reserve(tree->size() / 2);
    tree->query_if(
        [&](const Spatial::AABB& b) { return frustum.intersects(b); }, out);

    return out;
}

std::vector<std::pair<std::uintptr_t, std::uintptr_t>> SceneSystem::query_pairs(
    std::uintptr_t scene) const {
    std::shared_lock lock(impl_->mtx);
    std::vector<std::pair<std::uintptr_t, std::uintptr_t>> out;

    const Spatial::Octree<Impl::Payload>* tree = impl_->find_tree(scene);
    if (tree == nullptr || tree->size() < 2) {
        return out;
    }

    std::size_t n = tree->size();
    out.reserve(n * (n - 1) / 4); // 保守估计，实际碰撞对通常远小于最大值
    tree->collect_pairs(out);

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
