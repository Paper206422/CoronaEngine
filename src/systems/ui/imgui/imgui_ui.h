#pragma once

#include <SDL3/SDL.h>
#include <imgui.h>

#include <memory>

#include "cef/browser_ui.h"
#include "sdl/sdl_utils.h"

namespace Corona::Systems {
class VulkanBackend;
}

namespace Corona::Systems::UI {

// ============================================================================
// SDL/ImGui 生命周期管理
// ============================================================================

bool initialize_sdl_imgui(SDL_Window*& window, ImGuiIO*& io, std::unique_ptr<VulkanBackend>& vulkan_backend);
void shutdown_sdl_imgui(SDL_Window*& window, ImGuiIO*& io, std::unique_ptr<VulkanBackend>& vulkan_backend);

// ============================================================================
// UI 布局管理器
// ============================================================================

class UiLayoutManager {
   public:
    UiLayoutManager() = default;

    ImGuiID setup_dockspace();
    void end_dockspace();

   private:
    bool dockspace_active_ = false;
};

// ============================================================================
// UI 帧上下文
// ============================================================================

struct UiFrameContext {
    SDL_Window* window = nullptr;
    ImGuiIO* io = nullptr;
    VulkanBackend* vulkan_backend = nullptr;
    int* active_tab_id = nullptr;
    bool* running = nullptr;
    bool* window_size_changed = nullptr;
};

// ============================================================================
// UI 帧运行器
// ============================================================================

class UiFrameRunner {
   public:
    UiFrameRunner() = default;

    void run_frame(UiFrameContext& context);

   private:
    int url_input_active_tab_ = -1;
    bool system_cursor_hidden_ = false;
    bool system_cursor_custom_ = false;
    bool viewport_system_cursor_load_attempted_ = false;
    SDL_Cursor* viewport_system_cursor_ = nullptr;

    SDL_Cursor* ensure_viewport_system_cursor();
    void apply_system_cursor_visibility(SDL_Window* main_window, int active_tab_id);

    UiLayoutManager layout_manager_{};
    BrowserRenderer browser_renderer_{};
    BrowserInputHandler input_handler_{};
    SDLEventHandler event_handler_{};
};

}  // namespace Corona::Systems::UI