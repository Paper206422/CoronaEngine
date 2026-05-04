#pragma once

#include <SDL3/SDL.h>
#include <cef_browser.h>
#include <imgui.h>
#include <include/internal/cef_types.h>

#include <functional>
#include <string>
#include <vector>

namespace Corona::Systems::UI {

// ============================================================================
// 键盘工具函数
// ============================================================================

namespace KeyUtils {

int convert_sdl_key_code_to_windows(int sdl_key);
bool is_modifier_key(int key);
bool should_send_char_event(int key, int modifiers);

}  // namespace KeyUtils

// ============================================================================
// 鼠标状态管理器
// ============================================================================

namespace MouseUtils {

class MouseStateManager {
   public:
    MouseStateManager() = default;

    int handle_mouse_click(const ImVec2& current_pos, Uint32 current_time);

    void set_mouse_down(bool down) { is_left_down_ = down; }
    bool is_mouse_down() const { return is_left_down_; }

    int get_click_count() const { return click_count_; }

    void set_dragging(bool dragging) { is_dragging_ = dragging; }
    bool is_dragging() const { return is_dragging_; }

    void reset();

   private:
    Uint32 last_click_time_ = 0;
    ImVec2 last_click_pos_{0, 0};
    int click_count_ = 0;
    bool is_left_down_ = false;
    bool is_dragging_ = false;

    static constexpr Uint32 kDoubleClickTime = 500;
    static constexpr float kDoubleClickDist = 5.0f;
};

CefBrowserHost::MouseButtonType convert_mouse_button(Uint8 sdl_button);
CefMouseEvent create_mouse_event(const ImVec2& mouse_pos, const ImVec2& item_pos, uint32_t modifiers = 0);
uint32_t get_modifiers(bool is_left_down = false);

void send_mouse_click(CefRefPtr<CefBrowser> browser, const ImVec2& mouse_pos,
                      const ImVec2& item_pos, CefBrowserHost::MouseButtonType button,
                      bool mouse_up, int click_count);
void send_mouse_move(CefRefPtr<CefBrowser> browser, const ImVec2& mouse_pos,
                     const ImVec2& item_pos, bool mouse_leave = false);
void send_mouse_wheel(CefRefPtr<CefBrowser> browser, const ImVec2& mouse_pos,
                      const ImVec2& item_pos, float wheel_delta);

}  // namespace MouseUtils

// ============================================================================
// SDL 事件处理器
// ============================================================================

struct EventProcessResult {
    bool should_quit = false;
    bool window_resized = false;
    int url_input_active_tab = -1;
};

class SDLEventHandler {
   public:
    SDLEventHandler() = default;

    using KeyEventCallback = std::function<void(const SDL_Event&)>;

    EventProcessResult process_events(SDL_Window* window,
                                      int current_url_input_active_tab,
                                      KeyEventCallback on_key_event = nullptr,
                                      KeyEventCallback on_text_event = nullptr,
                                      KeyEventCallback on_ime_event = nullptr);

   private:
    bool is_input_method_switch(const SDL_Event& event);
    bool should_process_in_imgui(const SDL_Event& event, int url_input_active_tab);
};

}  // namespace Corona::Systems::UI
