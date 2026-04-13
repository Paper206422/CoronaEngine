#pragma once

#include <SDL3/SDL.h>
#include <corona/kernel/system/i_system.h>
#include <corona/events/imgui_system_events.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/systems/ui/vulkan_backend.h>
#include <imgui.h>

#include <memory>

namespace Corona::Systems 
{

    class VulkanBackend;

    /**
    * @brief UI系统
    *
    * 负责启动和管理 ImGui 界面。
    * 运行在主线程（不使用独立线程），因为 SDL/ImGui/CEF 都要求在主线程中运行。
    *
    * 注意：此系统直接实现 ISystem 接口，而不是继承 SystemBase，
    * 因为它不需要独立线程和 SystemBase 提供的线程管理功能。
    */
    class ImguiSystem : public Kernel::ISystem
    {
    public:
        ImguiSystem() = default;
        ~ImguiSystem() override = default;

        // ========================================
        // ISystem 接口实现
        // ========================================

        [[nodiscard]] std::string_view get_name() const override { return "Imgui"; }
        [[nodiscard]] int get_priority() const override { return 40; }

        bool initialize(Kernel::ISystemContext* ctx) override;
        void update() override;
        void shutdown() override;

        // 主线程系统不需要线程控制，提供空实现
        void start() override;
        void stop() override;
        void pause() override {}
        void resume() override {}

        // 状态和帧率
        [[nodiscard]] Kernel::SystemState get_state() const override { return state_; }
        [[nodiscard]] int get_target_fps() const override { return 60; }

        // 性能统计（主线程系统不单独统计）
        [[nodiscard]] float get_actual_fps() const override { return 0.0f; }
        [[nodiscard]] float get_average_frame_time() const override { return 0.0f; }
        [[nodiscard]] float get_max_frame_time() const override { return 0.0f; }
        [[nodiscard]] std::uint64_t get_total_frames() const override { return 0; }
        void reset_stats() override {}

        /**
        * @brief 检查 UI 系统是否仍在运行
        * @return 如果用户关闭了窗口返回 false
        */
        [[nodiscard]] bool is_ui_running() const { return running_; }

    private:
        Kernel::SystemState state_ = Kernel::SystemState::idle;

        SDL_Event event_{};
        bool show_demo_window_ = false;
        bool running_ = false;
        SDL_Window* window_ = nullptr;
        ImGuiIO* io_ = nullptr;

        bool window_size_changed_ = false;
        bool sdl_initialized_ = false;

        std::unique_ptr<VulkanBackend> vulkan_backend_;

        int active_tab_id_ = -1;

        Kernel::EventId sdl_start_id_ = 0;

    };

}  // namespace Corona::Systems