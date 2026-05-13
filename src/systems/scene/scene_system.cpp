#include <corona/events/engine_events.h>
#include <corona/kernel/core/i_logger.h>
#include <corona/kernel/utils/storage.h>
#include <corona/shared_data_hub.h>
#include <corona/spatial/octree.h>
#include <corona/systems/scene/scene_system.h>

#include <mutex>
#include <shared_mutex>
#include <unordered_map>
#include <unordered_set>

#include "quill/backend/StringFromTime.h"

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

    if (ctx && ctx->event_bus()) {
        auto id1 = ctx->event_bus()->subscribe<Events::ActorLoadCompletedEvent>(
            [this](const Events::ActorLoadCompletedEvent& e) {
                this->on_load_completed(e);
            });
        auto id2 = ctx->event_bus()->subscribe<Events::ActorUnloadCompletedEvent>(
           [this](const Events::ActorUnloadCompletedEvent& e) {
               this->on_unload_completed(e);
           });

        impl_->event_subscriptions.push_back(id1);
        impl_->event_subscriptions.push_back(id2);
    }

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
        auto scene_read = scene_storage.try_acquire_read(scene_handle);
        if ( !scene_read.valid() )  continue;
        const SceneDevice& scene_dev = *scene_read;

        Impl::SceneState& scene_state = impl_->get_or_create(scene_handle);
        std::vector<typename Spatial::Octree<Impl::Payload>::Entry> octree_entries;

        std::unordered_set<Impl::Payload> added_actors;
        for (std::uintptr_t actor_handle : scene_dev.actor_handles) {
            if (added_actors.count(actor_handle)) continue;

            auto& actor_storage = hub.actor_storage();
            auto actor_read = actor_storage.try_acquire_read(actor_handle);
            if ( !actor_read ) continue;
            const ActorDevice& actor_dev = *actor_read;

            {
                std::unique_lock lock(impl_->mtx);
                if (!scene_state.actor_load_states.count(actor_handle)) {
                    scene_state.actor_load_states[actor_handle] = ActorLoadState::Loaded;
                }
            }

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
                added_actors.insert(actor_handle);
                break;
            }
        }

        Spatial::AABB root_aabb;
        if (!octree_entries.empty()) {
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

        scene_state.tree.rebuild(root_aabb,octree_entries);

        std::vector<std::pair<ktm::fvec3,Math::Frustum>> cameras;
        std::unordered_set<Impl::Payload> visible_actors;
        for (std::uintptr_t camera_handle : scene_dev.camera_handles) {
            auto cam_read = camera_storage.try_acquire_read(camera_handle);
            if ( !cam_read.valid() ) continue;

            // 填充相机位置和视锥
            const CameraDevice& cam_dev = *cam_read;
            Math::Frustum frustum = Math::Frustum::from_camera(cam_dev);
            cameras.emplace_back(cam_dev.position,frustum);

            std::vector<Impl::Payload> visible_for_camera = query_visible_for_camera(scene_handle,camera_handle);
            visible_actors.insert(visible_for_camera.begin(),visible_for_camera.end());
        }

        if (scene_state.cfg.enable_distance_culling && !cameras.empty()) {
            std::unique_lock lock(impl_->mtx);

            for (const auto& entry : octree_entries) {
                Impl::Payload actor_handle = entry.payload;
                ActorLoadState& current_state = scene_state.actor_load_states[actor_handle];

                // 计算物体到最近相机的欧氏距离
                ktm::fvec3 actor_center = entry.bounds.center();
                float min_distance = std::numeric_limits<float>::max();
                for (const auto& [cam_pos,_] : cameras) {
                    min_distance = std::min(min_distance,ktm::distance(actor_center,cam_pos));
                }

                // 状态机转换
                switch (current_state) {
                    case ActorLoadState::Loaded:
                        // 超过卸载距离 + 不在任何相机视锥内
                        if (min_distance > scene_state.cfg.unload_distance &&
                            !visible_actors.count(actor_handle)) {
                            current_state = ActorLoadState::Unloading;
                            if (impl_->ctx && impl_->ctx->event_bus()) {
                                Events::ActorUnloadRequestedEvent unload_event{scene_handle,actor_handle};
                                impl_->ctx->event_bus()->publish(unload_event);
                                CFW_LOG_NOTICE("SceneSystem: Published unload request for actor {} (scene: {}, distance: {:.2f}m)",
                                              actor_handle, scene_handle, min_distance);
                            }
                            }
                        break;

                    case ActorLoadState::Unloaded:
                        // 触发条件：进入预加载距离范围
                        if (min_distance < scene_state.cfg.preload_distance) {
                            current_state = ActorLoadState::Loading;
                            if (impl_->ctx && impl_->ctx->event_bus()) {
                                Events::ActorLoadRequestedEvent load_event{scene_handle,actor_handle};
                                impl_->ctx->event_bus()->publish(load_event);
                                CFW_LOG_NOTICE("SceneSystem: Published preload request for actor {} (scene: {}, distance: {:.2f}m)",
                                              actor_handle, scene_handle, min_distance);
                            }
                        }
                        break;

                    case  ActorLoadState::Loading:
                    case  ActorLoadState::Unloading:
                        // 过渡状态不做任何操作，等待资源系统的完成事件
                        break;
                }
            }
        }

        {
            std::unique_lock lock(impl_->mtx);

            for (std::uintptr_t actor_handle : scene_dev.actor_handles) {
                // 跳过未加载和正在加载/卸载的Actor
                if (scene_state.actor_load_states[actor_handle] != ActorLoadState::Loaded) {
                    continue;
                }

                if ( visible_actors.count(actor_handle) ) {
                    scene_state.invisible_frames[actor_handle] = 0;
                }else {
                    uint32_t cnt = ++scene_state.invisible_frames[actor_handle];

                    if ( scene_state.cfg.invisible_frames_to_evict > 0 &&
                        cnt >= static_cast<uint32_t>(scene_state.cfg.invisible_frames_to_evict) ) {
                        if (impl_->ctx && impl_->ctx->event_bus()) {
                            Events::ActorEvictRequestedEvent evict_event{scene_handle,actor_handle};
                            impl_->ctx->event_bus()->publish(evict_event);
                            CFW_LOG_NOTICE("SceneSystem: Evict requested for actor {} (invisible {} frames)",
                                   actor_handle, cnt);
                        }
                        scene_state.invisible_frames[actor_handle] = 0;
                        }
                }
            }
        }

        {
            std::unique_lock lock(impl_->mtx);
            scene_state.stats.actor_total = scene_dev.actor_handles.size();
            scene_state.stats.actor_visible = visible_actors.size();
            scene_state.stats.octree_entries = octree_entries.size();

            scene_state.stats.actor_loaded = 0;
            scene_state.stats.actor_loading = 0;
            scene_state.stats.actor_unloading = 0;
            scene_state.stats.actor_unloaded = 0;

            for (const auto& [actor_handle, state] : scene_state.actor_load_states) {
                switch (state) {
                    case ActorLoadState::Loaded: scene_state.stats.actor_loaded++; break;
                    case ActorLoadState::Loading:   scene_state.stats.actor_loading++; break;
                    case ActorLoadState::Unloading: scene_state.stats.actor_unloading++; break;
                    case ActorLoadState::Unloaded:  scene_state.stats.actor_unloaded++; break;
                }
            }
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

    // 取消所有事件订阅
    if (impl_->ctx && impl_->ctx->event_bus()) {
        for (Kernel::EventId subscription_id : impl_->event_subscriptions) {
            impl_->ctx->event_bus()->unsubscribe(subscription_id);
        }
    }
    impl_->event_subscriptions.clear();

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

void SceneSystem::set_distance_config(std::uintptr_t scene, float unload_dist,
                                    float preload_dist,bool enable) {
    std::unique_lock lock(impl_->mtx);
    auto& scene_state = impl_->get_or_create(scene);
    scene_state.cfg.enable_distance_culling = enable;
    scene_state.cfg.unload_distance = unload_dist;
    scene_state.cfg.preload_distance = preload_dist;
}

// ============================================================================
// 私有事件处理
// ============================================================================

void SceneSystem::on_load_completed(const Events::ActorLoadCompletedEvent& event) {
   std::unique_lock lock(impl_->mtx);
    auto scene_it = impl_->scenes.find(event.scene);
    if (scene_it == impl_->scenes.end()) return;

    auto& state_map = scene_it->second.actor_load_states;
    auto actor_it = state_map.find(event.actor);
    if (actor_it != state_map.end() && actor_it->second == ActorLoadState::Loading) {
        actor_it->second = ActorLoadState::Loaded;
        impl_->offline_actors[event.actor] = false;
        CFW_LOG_NOTICE("SceneSystem: Actor {} (scene: {}) load completed", event.actor, event.scene);
    }
}

void SceneSystem::on_unload_completed(const Events::ActorUnloadCompletedEvent& event) {
    std::unique_lock lock(impl_->mtx);
    auto scene_it = impl_->scenes.find(event.scene);
    if (scene_it == impl_->scenes.end()) return;

    auto& state_map = scene_it->second.actor_load_states;
    auto actor_it = state_map.find(event.actor);
    if (actor_it != state_map.end() && actor_it->second == ActorLoadState::Unloading) {
        actor_it->second = ActorLoadState::Unloaded;
        impl_->offline_actors[event.actor] = true;
        CFW_LOG_NOTICE("SceneSystem: Actor {} (scene: {}) unload completed", event.actor, event.scene);
    }
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

    std::vector<std::uintptr_t> filtered;
    filtered.reserve(out.size());
    const auto& state_map = it->second.actor_load_states;
    for (std::uintptr_t actor_handle : out) {
        auto state_it = state_map.find(actor_handle);
        if (state_it != state_map.end() && state_it->second == ActorLoadState::Loaded) {
            filtered.push_back(actor_handle);
        }
    }

    return filtered;
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

    std::vector<std::uintptr_t> filtered;
    filtered.reserve(out.size());
    const auto& state_map = it->second.actor_load_states;
    for (std::uintptr_t actor_handle : out) {
        auto state_it = state_map.find(actor_handle);
        if (state_it != state_map.end() && state_it->second == ActorLoadState::Loaded) {
            filtered.push_back(actor_handle);
        }
    }
    return filtered;

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

    std::vector<std::uintptr_t> filtered;
    filtered.reserve(out.size());
    const auto& state_map = it->second.actor_load_states;
    for (std::uintptr_t actor_handle : out) {
        auto state_it = state_map.find(actor_handle);
        if (state_it != state_map.end() && state_it->second == ActorLoadState::Loaded) {
            filtered.push_back(actor_handle);
        }
    }
    return filtered;
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

    std::vector<std::pair<std::uintptr_t, std::uintptr_t>> filtered;
    filtered.reserve(out.size());
    const auto& state_map = it->second.actor_load_states;
    for (const auto& pair : out) {
        auto state_a = state_map.find(pair.first);
        auto state_b = state_map.find(pair.second);
        if (state_a != state_map.end() && state_a->second == ActorLoadState::Loaded
            && state_b != state_map.end() && state_b->second == ActorLoadState::Loaded) {
            filtered.push_back(pair);
        }
    }
    return filtered;
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

//加载状态查询
ActorLoadState SceneSystem::get_actor_load_state(std::uintptr_t scene,std::uintptr_t actor) const {
    std::shared_lock lock(impl_->mtx);
    auto scene_it = impl_->scenes.find(scene);
    if (scene_it == impl_->scenes.end()) {
        return ActorLoadState::Unloaded;
    }
    auto actor_it = scene_it->second.actor_load_states.find(actor);
    return (actor_it != scene_it->second.actor_load_states.end()) ?
            actor_it->second : ActorLoadState::Unloaded;
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
    // LRU恢复时，将所有包含该actor的场景中的状态设为已加载
    for (auto& [scene, state] : impl_->scenes) {
        auto it = state.actor_load_states.find(actor);
        if (it != state.actor_load_states.end()) {
            it->second = ActorLoadState::Loaded;
        }
    }
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
