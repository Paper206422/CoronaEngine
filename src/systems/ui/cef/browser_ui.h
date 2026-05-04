#pragma once

#include <SDL3/SDL.h>
#include <imgui.h>
#include <imgui_internal.h>
#include <include/cef_browser.h>
#include <include/internal/cef_types.h>

#include <memory>
#include <string>
#include <vector>

namespace Corona::Systems::UI {

struct BrowserTab;

// ============================================================================
// 待处理的键盘事件
// ============================================================================

struct PendingKeyEvent {
    enum EventType { kKeyEvent,
                     kTextEvent,
                     kImeComposition };

    EventType type;
    int key_code = 0;
    int scan_code = 0;
    int modifiers = 0;
    bool pressed = false;
    std::string text;
    int ime_start = 0;
    int ime_length = 0;
    bool is_modifier_combo = false;

    explicit PendingKeyEvent(EventType t) : type(t) {}
};

// ============================================================================
// 浏览器输入处理器
// ============================================================================

class BrowserInputHandler {
   public:
    BrowserInputHandler() = default;

    void clear_pending_events();
    void process_sdl_key_event(const SDL_Event& event);
    void process_sdl_text_event(const SDL_Event& event);
    void process_sdl_ime_event(const SDL_Event& event);
    void send_key_events_to_browser(const CefRefPtr<CefBrowser>& browser);

   private:
    std::vector<PendingKeyEvent> pending_key_events_;
};

// ============================================================================
// 浏览器窗口渲染器
// ============================================================================

class BrowserRenderer {
   public:
    BrowserRenderer() = default;

    // 渲染所有浏览器标签页，返回需要关闭的标签页 ID
    std::vector<int> render_browser_tabs(ImGuiID dock_space_id,
                                         int& active_tab_id,
                                         int& url_input_active_tab,
                                         ImGuiIO* io);

   private:
    void render_single_tab(int tab_id,
                           ImGuiID dock_space_id,
                           int& active_tab_id,
                           int& url_input_active_tab,
                           ImGuiIO* io);

    void setup_window_transform(BrowserTab* tab,
                                ImGuiID dock_space_id,
                                bool is_main_tab);

    void handle_browser_mouse_events(BrowserTab* tab,
                                     int tab_id,
                                     int& active_tab_id,
                                     int& url_input_active_tab,
                                     const ImGuiIO* io,
                                     bool is_dragging = false);
};

}  // namespace Corona::Systems::UI
