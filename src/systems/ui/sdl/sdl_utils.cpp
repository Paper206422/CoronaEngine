#include "sdl_utils.h"

#include <imgui_impl_sdl3.h>

#include <cmath>

namespace Corona::Systems::UI {

// ============================================================================
// KeyUtils 实现
// ============================================================================

namespace KeyUtils {

int convert_sdl_key_code_to_windows(int sdl_key) {
    if (sdl_key >= SDLK_A && sdl_key <= SDLK_Z) {
        return 0x41 + (sdl_key - SDLK_A);
    }

    if (sdl_key >= SDLK_0 && sdl_key <= SDLK_9) {
        return 0x30 + (sdl_key - SDLK_0);
    }

    switch (sdl_key) {
        case SDLK_RETURN:
            return 0x0D;
        case SDLK_GRAVE:
            return 0xC0;
        case SDLK_MINUS:
            return 0xBD;
        case SDLK_EQUALS:
            return 0xBB;
        case SDLK_LEFTBRACKET:
            return 0xDB;
        case SDLK_RIGHTBRACKET:
            return 0xDD;
        case SDLK_BACKSLASH:
            return 0xDC;
        case SDLK_SEMICOLON:
            return 0xBA;
        case SDLK_APOSTROPHE:
            return 0xDE;
        case SDLK_COMMA:
            return 0xBC;
        case SDLK_PERIOD:
            return 0xBE;
        case SDLK_SLASH:
            return 0xBF;
        case SDLK_LEFT:
            return 0x25;
        case SDLK_UP:
            return 0x26;
        case SDLK_RIGHT:
            return 0x27;
        case SDLK_DOWN:
            return 0x28;
        case SDLK_HOME:
            return 0x24;
        case SDLK_END:
            return 0x23;
        case SDLK_PAGEUP:
            return 0x21;
        case SDLK_PAGEDOWN:
            return 0x22;
        case SDLK_INSERT:
            return 0x2D;
        case SDLK_DELETE:
            return 0x2E;
        case SDLK_BACKSPACE:
            return 0x08;
        case SDLK_TAB:
            return 0x09;
        case SDLK_ESCAPE:
            return 0x1B;
        case SDLK_SPACE:
            return 0x20;
        case SDLK_KP_0:
            return 0x60;
        case SDLK_KP_1:
            return 0x61;
        case SDLK_KP_2:
            return 0x62;
        case SDLK_KP_3:
            return 0x63;
        case SDLK_KP_4:
            return 0x64;
        case SDLK_KP_5:
            return 0x65;
        case SDLK_KP_6:
            return 0x66;
        case SDLK_KP_7:
            return 0x67;
        case SDLK_KP_8:
            return 0x68;
        case SDLK_KP_9:
            return 0x69;
        case SDLK_KP_MULTIPLY:
            return 0x6A;
        case SDLK_KP_PLUS:
            return 0x6B;
        case SDLK_KP_MINUS:
            return 0x6D;
        case SDLK_KP_DECIMAL:
            return 0x6E;
        case SDLK_KP_DIVIDE:
            return 0x6F;
        case SDLK_KP_ENTER:
            return 0x0D;
        case SDLK_F1:
            return 0x70;
        case SDLK_F2:
            return 0x71;
        case SDLK_F3:
            return 0x72;
        case SDLK_F4:
            return 0x73;
        case SDLK_F5:
            return 0x74;
        case SDLK_F6:
            return 0x75;
        case SDLK_F7:
            return 0x76;
        case SDLK_F8:
            return 0x77;
        case SDLK_F9:
            return 0x78;
        case SDLK_F10:
            return 0x79;
        case SDLK_F11:
            return 0x7A;
        case SDLK_F12:
            return 0x7B;
        default:
            return sdl_key;
    }
}

bool is_modifier_key(int key) {
    return key == SDLK_LCTRL || key == SDLK_RCTRL ||
           key == SDLK_LSHIFT || key == SDLK_RSHIFT ||
           key == SDLK_LALT || key == SDLK_RALT ||
           key == SDLK_LGUI || key == SDLK_RGUI;
}

bool should_send_char_event(int key, int modifiers) {
    if (is_modifier_key(key)) return false;
    if (key >= SDLK_F1 && key <= SDLK_F12) return false;
    if (key == SDLK_RETURN || key == SDLK_KP_ENTER) return true;
    if (modifiers & EVENTFLAG_CONTROL_DOWN) {
        if ((key >= SDLK_A && key <= SDLK_Z) || (key >= SDLK_0 && key <= SDLK_9)) {
            return true;
        }
    }
    return false;
}

}  // namespace KeyUtils

// ============================================================================
// MouseUtils 实现
// ============================================================================

namespace MouseUtils {

int MouseStateManager::handle_mouse_click(const ImVec2& current_pos, Uint32 current_time) {
    float dx = current_pos.x - last_click_pos_.x;
    float dy = current_pos.y - last_click_pos_.y;
    float distance = std::sqrtf(dx * dx + dy * dy);

    if ((current_time - last_click_time_) < kDoubleClickTime && distance < kDoubleClickDist) {
        click_count_++;
    } else {
        click_count_ = 1;
    }

    if (click_count_ > 3) click_count_ = 1;

    last_click_time_ = current_time;
    last_click_pos_ = current_pos;

    return click_count_;
}

void MouseStateManager::reset() {
    last_click_time_ = 0;
    last_click_pos_ = ImVec2(0, 0);
    click_count_ = 0;
    is_left_down_ = false;
    is_dragging_ = false;
}

CefBrowserHost::MouseButtonType convert_mouse_button(Uint8 sdl_button) {
    switch (sdl_button) {
        case SDL_BUTTON_LEFT:
            return MBT_LEFT;
        case SDL_BUTTON_MIDDLE:
            return MBT_MIDDLE;
        case SDL_BUTTON_RIGHT:
            return MBT_RIGHT;
        default:
            return MBT_LEFT;
    }
}

CefMouseEvent create_mouse_event(const ImVec2& mouse_pos, const ImVec2& item_pos, uint32_t modifiers) {
    CefMouseEvent mouse_event;
    mouse_event.x = static_cast<int>(mouse_pos.x - item_pos.x);
    mouse_event.y = static_cast<int>(mouse_pos.y - item_pos.y);
    mouse_event.modifiers = modifiers;
    return mouse_event;
}

uint32_t get_modifiers(bool is_left_down, bool is_right_down) {
    ImGuiIO& io = ImGui::GetIO();
    uint32_t modifiers = 0;

    if (is_left_down) modifiers |= EVENTFLAG_LEFT_MOUSE_BUTTON;
    if (is_right_down) modifiers |= EVENTFLAG_RIGHT_MOUSE_BUTTON;
    if (io.KeyShift) modifiers |= EVENTFLAG_SHIFT_DOWN;
    if (io.KeyCtrl) modifiers |= EVENTFLAG_CONTROL_DOWN;
    if (io.KeyAlt) modifiers |= EVENTFLAG_ALT_DOWN;

    return modifiers;
}

void send_mouse_click(CefRefPtr<CefBrowser> browser, const ImVec2& mouse_pos,
                      const ImVec2& item_pos, CefBrowserHost::MouseButtonType button,
                      bool mouse_up, int click_count) {
    if (!browser) return;

    bool is_left = (button == MBT_LEFT);
    bool is_right = (button == MBT_RIGHT);
    uint32_t modifiers = get_modifiers(!mouse_up && is_left, !mouse_up && is_right);

    CefMouseEvent mouse_event = create_mouse_event(mouse_pos, item_pos, modifiers);
    browser->GetHost()->SendMouseClickEvent(mouse_event, button, mouse_up, click_count);
}

void send_mouse_move(CefRefPtr<CefBrowser> browser, const ImVec2& mouse_pos,
                     const ImVec2& item_pos, bool mouse_leave) {
    if (!browser) return;

    ImGuiIO& io = ImGui::GetIO();
    bool is_left_down = ImGui::IsMouseDown(ImGuiMouseButton_Left);
    bool is_right_down = ImGui::IsMouseDown(ImGuiMouseButton_Right);
    uint32_t modifiers = get_modifiers(is_left_down, is_right_down);

    CefMouseEvent mouse_event = create_mouse_event(mouse_pos, item_pos, modifiers);
    browser->GetHost()->SendMouseMoveEvent(mouse_event, mouse_leave);
}

void send_mouse_wheel(CefRefPtr<CefBrowser> browser, const ImVec2& mouse_pos,
                      const ImVec2& item_pos, float wheel_delta) {
    if (!browser) return;

    uint32_t modifiers = get_modifiers(ImGui::IsMouseDown(0), ImGui::IsMouseDown(1));
    CefMouseEvent mouse_event = create_mouse_event(mouse_pos, item_pos, modifiers);

    // Windows 标准滚轮增量通常是 120
    browser->GetHost()->SendMouseWheelEvent(mouse_event, 0, static_cast<int>(wheel_delta * 120));
}

}  // namespace MouseUtils

// ============================================================================
// SDLEventHandler 实现
// ============================================================================

bool SDLEventHandler::is_input_method_switch(const SDL_Event& event) {
    if (event.type != SDL_EVENT_KEY_DOWN && event.type != SDL_EVENT_KEY_UP) {
        return false;
    }

    int key = static_cast<int>(event.key.key);
    bool ctrl = (event.key.mod & SDL_KMOD_CTRL) != 0;
    bool shift = (event.key.mod & SDL_KMOD_SHIFT) != 0;
    bool alt = (event.key.mod & SDL_KMOD_ALT) != 0;

    return ((ctrl && shift) || (alt && shift) ||
            (ctrl && key == SDLK_SPACE) ||
            (event.key.mod & SDL_KMOD_GUI && key == SDLK_SPACE));
}

bool SDLEventHandler::should_process_in_imgui(const SDL_Event& event, int url_input_active_tab) {
    if (event.type == SDL_EVENT_KEY_DOWN ||
        event.type == SDL_EVENT_KEY_UP ||
        event.type == SDL_EVENT_TEXT_INPUT ||
        event.type == SDL_EVENT_TEXT_EDITING) {
        return url_input_active_tab != -1;
    }
    return true;
}

EventProcessResult SDLEventHandler::process_events(
    SDL_Window* window,
    int current_url_input_active_tab,
    KeyEventCallback on_key_event,
    KeyEventCallback on_text_event,
    KeyEventCallback on_ime_event) {
    EventProcessResult result;
    result.url_input_active_tab = current_url_input_active_tab;

    SDL_Event event;
    while (SDL_PollEvent(&event)) {
        if (is_input_method_switch(event)) {
            ImGui_ImplSDL3_ProcessEvent(&event);
            continue;
        }

        bool should_pass_to_imgui = should_process_in_imgui(event, result.url_input_active_tab);

        if (event.type == SDL_EVENT_KEY_DOWN || event.type == SDL_EVENT_KEY_UP) {
            if (on_key_event) on_key_event(event);
        } else if (event.type == SDL_EVENT_TEXT_INPUT) {
            if (on_text_event) on_text_event(event);
        } else if (event.type == SDL_EVENT_TEXT_EDITING) {
            if (on_ime_event) on_ime_event(event);
        }

        if (should_pass_to_imgui) {
            ImGui_ImplSDL3_ProcessEvent(&event);
        }

        switch (event.type) {
            case SDL_EVENT_QUIT:
                result.should_quit = true;
                break;

            case SDL_EVENT_WINDOW_RESIZED:
                if (event.window.windowID == SDL_GetWindowID(window)) {
                    result.window_resized = true;
                }
                break;

            default:
                break;
        }
    }

    return result;
}

}  // namespace Corona::Systems::UI