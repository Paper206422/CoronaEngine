#pragma once

#include <CabbageHardware.h>
#include <corona/events/optics_system_events.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/kernel/system/system_base.h>

#include <cstdint>
#include <memory>
#include <mutex>
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

    void optics_pipeline(float frame_count, uint64_t frame_index);
    void process_pending_screenshots(void* surface);

    std::unique_ptr<Hardware> hardware_;
    std::uintptr_t image_handle_{};

    struct PendingScreenshot
    {
        void* surface = nullptr;
        std::string file_path;
        std::shared_ptr<std::promise<bool>> completion_promise;
    };
    std::vector<PendingScreenshot> pending_screenshots_;
    std::mutex screenshot_mutex_;
    Kernel::EventId screenshot_request_sub_id_ = 0;
};

}  // namespace Corona::Systems
