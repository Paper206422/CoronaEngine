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

    // ========================================
    // 渲染后端切换 API（线程安全）
    // ========================================

    /// 提交后端切换请求（线程安全，下一帧生效）
    void set_render_backend(RenderBackend backend);

    /// 获取当前生效的渲染后端
    [[nodiscard]] RenderBackend get_render_backend() const;

   private:
    bool initialize_vision_backend_if_enabled();
    bool initialize_hardware_resources();
    bool initialize_render_pipelines();

    void optics_pipeline(float frame_count, uint64_t frame_index);
    void process_pending_screenshots(std::uintptr_t camera_handle, HardwareImage& render_target);

#ifdef CORONA_ENABLE_VISION
    // Vision 相关私有方法（在 CORONA_ENABLE_VISION 宏保护下实现）
    bool init_vision_lazy();  ///< 首次切换到 Vision 时的 lazy 初始化
    void run_vision_frame(float frame_count, uint64_t frame_index);
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
    std::atomic<int> pending_backend_{static_cast<int>(RenderBackend::Native)};
    RenderBackend current_backend_{RenderBackend::Native};
    bool vision_initialized_{false};
    std::uintptr_t last_render_cam_handle_{0};
    uint32_t consecutive_vision_failures_{0};
    bool has_last_vision_frame_{false};
    uint32_t last_vision_frame_width_{0};
    uint32_t last_vision_frame_height_{0};

    struct PendingScreenshot {
        std::uintptr_t camera_handle = 0;
        std::string file_path;
        std::shared_ptr<std::promise<bool>> completion_promise;
    };
    std::vector<PendingScreenshot> pending_screenshots_;
    std::mutex screenshot_mutex_;
    Kernel::EventId screenshot_request_sub_id_ = 0;
};

}  // namespace Corona::Systems
