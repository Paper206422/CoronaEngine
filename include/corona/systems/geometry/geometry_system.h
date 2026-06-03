#pragma once

#include <corona/events/geometry_system_events.h>
#include <corona/events/scene_system_events.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/kernel/system/system_base.h>
#include <corona/math/frustum.h>
#include <corona/spatial/aabb.h>

#include <cstdint>
#include <future>
#include <memory>
#include <unordered_map>
#include <utility>
#include <vector>

namespace Corona::Systems {

/**
 * @brief 物体加载状态枚举
 */
enum class ActorLoadState : uint8_t {
    Loaded,     // 已加载，可正常渲染和物理模拟
    Loading,    // 正在异步加载中
    Unloading,  // 正在异步卸载中
    Unloaded    // 已卸载，数据不在内存中
};

/**
 * @brief 单场景的可见性策略
 */
struct SceneVisibilityConfig {
    /// 连续不可见超过该帧数时，触发 ActorEvictRequestedEvent。
    /// 0 表示永不 evict（默认，避免在 LRU 接入前误触）。
    int  invisible_frames_to_evict = 0;
    bool collect_stats             = true;

    bool enable_distance_culling  = false; // 是否启用距离卸载
    float unload_distance         = 0.0f; // 超过此距离且不可见时触发卸载
    float preload_distance        = 0.0f; // 进入此距离时触发预加载
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

    //距离卸载统计
    std::size_t actor_loaded      = 0;
    std::size_t actor_loading     = 0;
    std::size_t actor_unloading   = 0;
    std::size_t actor_unloaded    = 0;
};

/**
 * @brief 几何系统 (Geometry System)
 *
 * 负责几何数据管理、空间变换、包围盒计算，并承载场景八叉树空间索引服务
 * （原 SceneSystem 职责已并入此处）：
 * - 每帧重建场景八叉树；
 * - 提供线程安全的 AABB / 球 / 视锥 / 碰撞对查询；
 * - 维护 Actor 加载状态机与距离预加载/卸载；
 * - 维护 actor 可见性热度并发出 LRU evict/restore 事件。
 *
 * 运行在独立线程，以 60 FPS 更新几何状态。
 *
 * 优先级 85：晚于 transform 写入者，早于 MechanicsSystem(75)，确保物理宽相
 * query_pairs() 在同帧读取到已重建的八叉树。
 */
class GeometrySystem : public Kernel::SystemBase {
   public:
    GeometrySystem();
    ~GeometrySystem() override;

    // ========================================
    // ISystem 接口实现
    // ========================================

    std::string_view get_name() const override {
        return "Geometry";
    }

    int get_priority() const override {
        return 85;  // 高优先级，早于 MechanicsSystem(75)，保证八叉树同帧就绪
    }

    /**
     * @brief 初始化几何系统
     * @param ctx 系统上下文
     * @return 初始化成功返回 true
     */
    bool initialize(Kernel::ISystemContext* ctx) override;

    /**
     * @brief 每帧更新几何
     *
     * 在独立线程中调用，更新几何变换、重建八叉树并维护加载状态。
     */
    void update() override;

    /**
     * @brief 关闭几何系统
     *
     * 清理所有几何资源与异步任务。
     */
    void shutdown() override;

    // ========================================
    // 配置
    // ========================================
    void set_visibility_config(std::uintptr_t scene, SceneVisibilityConfig cfg);

    /// 距离卸载配置接口
    void set_distance_config(std::uintptr_t scene, float unload_dist, float preload_dist, bool enable = true);

    // ========================================
    // 空间查询（线程安全）
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

    /// 加载状态查询接口
    [[nodiscard]] ActorLoadState get_actor_load_state(std::uintptr_t actor, std::uintptr_t scene) const;

    // ========================================
    // LOD 工具
    // ========================================
    /// 计算物体包围球在屏幕上的占比（0~1）
    static float compute_screen_ratio(const ktm::fvec3& camera_pos,
                                      float              camera_fov_deg,
                                      const ktm::fvec3& world_center,
                                      float              bounding_radius);

    /// 根据屏幕占比选择 LOD 等级（0 = 原始网格）
    static int select_lod_level(float                     screen_ratio,
                                const std::vector<float>& thresholds);

    // ========================================
    // 统计
    // ========================================
    [[nodiscard]] SceneStats stats(std::uintptr_t scene) const;

   private:
    void on_load_completed(const Events::ActorLoadCompletedEvent& event);
    void on_unload_completed(const Events::ActorUnloadCompletedEvent& event);
    void on_load_requested(const Events::ActorLoadRequestedEvent& event);
    void on_unload_requested(const Events::ActorUnloadRequestedEvent& event);
    void process_async_tasks();  // 处理完成的异步资源任务

    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace Corona::Systems
