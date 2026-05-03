#pragma once

#include <corona/events/scene_system_events.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/kernel/system/system_base.h>
#include <corona/math/frustum.h>
#include <corona/spatial/aabb.h>

#include <cstdint>
#include <memory>
#include <utility>
#include <vector>

namespace Corona::Systems {

/**
 * @brief 单场景的可见性策略
 */
struct SceneVisibilityConfig {
    /// 连续不可见超过该帧数时，触发 ActorEvictRequestedEvent。
    /// 0 表示永不 evict（默认，避免在 LRU 接入前误触）。
    int  invisible_frames_to_evict = 0;
    bool collect_stats             = true;
};

/**
 * @brief 单场景统计信息（供 UI / 日志读取）
 */
struct SceneStats {
    std::size_t actor_total       = 0;
    std::size_t actor_visible     = 0;  // 上一帧所有相机视锥的并集
    std::size_t actor_offline     = 0;  // 已被 LRU 卸载（M3 起）
    std::size_t octree_entries    = 0;
    double      last_rebuild_ms   = 0.0;
    double      last_query_ms     = 0.0;
};

/**
 * @brief 场景管理系统（八叉树宿主 / 空间查询服务）
 *
 * 职责（参见 docs/SCENE_OCTREE_CULLING_LRU_TODO_cn.md）：
 * - 每帧重建场景八叉树（M1）；
 * - 提供线程安全的 AABB / 球 / 视锥查询（M1 ~ M2）；
 * - 维护 actor 可见性热度并发出 LRU evict/restore 事件（M3）。
 *
 * 当前为骨架实现：lifecycle 完整、查询接口返回空集合，
 * 真实数据接入与算法在后续里程碑落地，公共 API 保持稳定。
 *
 * 优先级 88：晚于 KinematicsSystem(80)（确保 transform 已就位），
 * 早于 OpticsSystem(90)（确保渲染拿到的查询结果是当前帧的）。
 */
class SceneSystem : public Kernel::SystemBase {
   public:
    SceneSystem();
    ~SceneSystem() override;

    // ========================================
    // ISystem
    // ========================================
    std::string_view get_name() const override { return "Scene"; }
    int              get_priority() const override { return 88; }

    bool initialize(Kernel::ISystemContext* ctx) override;
    void update() override;
    void shutdown() override;

    // ========================================
    // 配置
    // ========================================
    void set_visibility_config(std::uintptr_t scene, SceneVisibilityConfig cfg);

    // ========================================
    // 空间查询（线程安全；当前为空集骨架，M1.2 后填入真实结果）
    // ========================================
    [[nodiscard]] std::vector<std::uintptr_t> query_aabb(
        std::uintptr_t scene, const Spatial::AABB& box) const;

    [[nodiscard]] std::vector<std::uintptr_t> query_sphere(
        std::uintptr_t scene, const ktm::fvec3& center, float radius) const;

    [[nodiscard]] std::vector<std::uintptr_t> query_frustum(
        std::uintptr_t scene, const Math::Frustum& frustum) const;

    /// 物理宽相用：返回 (handle_a, handle_b)，a < b。
    [[nodiscard]] std::vector<std::pair<std::uintptr_t, std::uintptr_t>> query_pairs(
        std::uintptr_t scene) const;

    /// 便捷：内部从 CameraDevice 构造 frustum 后查询
    [[nodiscard]] std::vector<std::uintptr_t> query_visible_for_camera(
        std::uintptr_t scene, std::uintptr_t camera) const;

    // ========================================
    // LRU 协作（M3 起启用，当前为占位）
    // ========================================
    [[nodiscard]] bool is_actor_offline(std::uintptr_t actor) const;
    void               mark_actor_restored(std::uintptr_t actor);

    // ========================================
    // 统计
    // ========================================
    [[nodiscard]] SceneStats stats(std::uintptr_t scene) const;

   private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace Corona::Systems
