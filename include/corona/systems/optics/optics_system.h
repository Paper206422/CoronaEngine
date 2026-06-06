#pragma once

#include <Horizon.h>
#include <corona/events/optics_system_events.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/kernel/system/system_base.h>

#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

// 前向声明 Hardware 结构体
struct Hardware;

namespace Corona::Systems {

#ifdef CORONA_ENABLE_VISION
namespace Vision {
struct VisionBuildResult;  // 定义见 vision/vision_geometry_adapter.h
}  // namespace Vision
#endif

/**
 * @brief 光学系统 (Optics System)
 *
 * 负责场景光学渲染、光线追踪、GPU 资源管理和渲染管线控制。
 * 运行在独立线程，以 120 FPS 渲染场景。
 */

/// 渲染后端枚举
enum class RenderBackend : int {
    Native = 0,  ///< 默认 Vulkan/光栅化管线
    Vision = 1,  ///< Vision CUDA 路径追踪后端
};

class OpticsSystem : public Kernel::SystemBase {
   public:
    OpticsSystem();
    ~OpticsSystem() override;

    // ========================================
    // ISystem 接口实现
    // ========================================

    std::string_view get_name() const override {
        return "Optics";
    }

    int get_priority() const override {
        return 90;  // 高优先级，在显示系统之后初始化
    }

    /**
     * @brief 初始化光学系统
     * @param ctx 系统上下文
     * @return 初始化成功返回 true
     */
    bool initialize(Kernel::ISystemContext* ctx) override;

    /**
     * @brief 每帧渲染
     *
     * 在独立线程中调用，执行场景光学渲染
     */
    void update() override;

    /**
     * @brief 关闭光学系统
     *
     * 清理所有 GPU 资源和渲染管线
     */
    void shutdown() override;

   private:
    bool initialize_vision_backend_if_enabled();
    bool initialize_hardware_resources();
    bool initialize_render_pipelines();

    void ensure_camera_render_resources(uint32_t width, uint32_t height);
    void optics_pipeline(float frame_count, uint64_t frame_index);
    void process_pending_screenshots(std::uintptr_t camera_handle, HardwareImage& render_target);

#ifdef CORONA_ENABLE_VISION
    // Vision 相关私有方法（在 CORONA_ENABLE_VISION 宏保护下实现）
    bool init_vision_lazy();  ///< 首次切换到 Vision 时的 lazy 初始化
    void run_vision_frame(float frame_count, uint64_t frame_index);

    /// 计算当前 SharedDataHub 场景的轻量签名，用于检测动态变化
    /// （几何拓扑 / transform / 材质参数 / materialColor / visible）。
    std::size_t compute_vision_scene_signature() const;

    /// 以"全量重建"方式把当前场景数据重新同步到 Vision：
    /// build_vision_geometry → scene.prepare → prepare_geometry → invalidate。
    /// 复用现有 pipeline（材质类型固定，无需重编译着色器），并通过
    /// scene.prepare() 内部的 remove_unused_elements() 回收旧材质，避免累积泄漏。
    /// 返回本次重建的统计结果，供去抖/重试逻辑区分"空场景"与"数据未就绪"。
    Vision::VisionBuildResult rebuild_vision_scene();

    /// 去抖检测：若签名变化则触发（延迟）重建，覆盖导入/导出/参数调整等动态操作。
    void sync_vision_dynamic_scene();
#endif  // CORONA_ENABLE_VISION
    struct ActorPickRequest {
        std::uintptr_t pick_handle{0};
        std::uint32_t x{0};
        std::uint32_t y{0};
    };
    std::optional<ActorPickRequest> take_pending_actor_pick(std::uintptr_t camera_handle);
    void complete_actor_pick(const ActorPickRequest& request);

    std::unique_ptr<Hardware> hardware_;
    std::uintptr_t image_handle_{};
    HardwareImage offscreen_image_;  ///< Dedicated render target for offscreen cameras (no surface)
    uint32_t offscreen_w_{0}, offscreen_h_{0};

    // Vision 后端状态
#ifdef CORONA_ENABLE_VISION
    // [MANUAL-READBACK] Locally-owned CPU staging buffer for the manual expansion of
    // FrameBuffer::fill_window_buffer(). Stored flat as 4 floats (RGBA) per pixel to
    // avoid leaking ocarina::float4 into this public header; the .cpp reinterpret_casts
    // data() to ocarina::float4* for view_texture().download_immediately().
    std::vector<float> vision_readback_buffer_;

    // [MANUAL-READBACK] Half-precision staging buffer for the upload step. Vision's
    // view_texture() is PixelStorage::FLOAT4 (float32 RGBA), but finalOutputImage is
    // RGBA16_FLOAT (half). HardwareImage::copyFrom() does a raw byte copy sized by
    // the destination format, so we must convert float32 -> half here before upload;
    // otherwise the float32 bytes are reinterpreted as half and the picture scrambles.
    std::vector<uint16_t> vision_half_buffer_;

    // 启用 Vision 编译时，首帧 update() 检测到 pending != current 会自动触发
    // init_vision_lazy() 切换到 Vision；若初始化失败仍会回退 Native。
    std::atomic<int> pending_backend_{static_cast<int>(RenderBackend::Vision)};
#else
    std::atomic<int> pending_backend_{static_cast<int>(RenderBackend::Native)};
#endif
    RenderBackend current_backend_{RenderBackend::Native};
    bool vision_initialized_{false};
    std::uintptr_t last_render_cam_handle_{0};
    uint32_t consecutive_vision_failures_{0};
    bool has_last_vision_frame_{false};
    uint32_t last_vision_frame_width_{0};
    uint32_t last_vision_frame_height_{0};

    // ---- Vision 动态场景同步（脏标记 + 去抖全量重建）----
    std::size_t vision_applied_signature_{0};   ///< 已同步到 Vision 的场景签名基线
    std::size_t vision_pending_signature_{0};   ///< 最近一次检测到的（可能仍在变化的）签名
    uint32_t vision_stable_frames_{0};          ///< 签名保持稳定的连续帧数，用于去抖
    static constexpr uint32_t kVisionRebuildDebounceFrames = 3;  ///< 稳定该帧数后才重建

    // 当一次重建检测到"有候选物体但 0 实例"（数据尚未就绪）时，不锁定签名并在
    // 后续帧重试，直到数据就绪或达到上限后兜底接受，避免每帧空转重建。
    uint32_t vision_rebuild_retries_{0};        ///< 数据未就绪导致的连续重试次数
    static constexpr uint32_t kVisionRebuildMaxRetries = 30;  ///< 重试上限（约 0.5s @60fps）

    struct PendingScreenshot {
        std::uintptr_t camera_handle = 0;
        std::string file_path;
        std::shared_ptr<std::promise<bool>> completion_promise;
    };
    std::vector<PendingScreenshot> pending_screenshots_;
    std::mutex screenshot_mutex_;
    Kernel::EventId screenshot_request_sub_id_ = 0;
    Kernel::EventId backend_switch_sub_id_ = 0;
};

}  // namespace Corona::Systems
