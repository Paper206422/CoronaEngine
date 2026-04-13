#include "browser_ui.h"

#include <SDL3/SDL.h>

#include "browser_manager.h"
#include "cef_client.h"
#include "sdl/sdl_utils.h"

namespace Corona::Systems::UI {

// ============================================================================
// BrowserInputHandler 实现
// ============================================================================

void BrowserInputHandler::clear_pending_events() {
    pending_key_events_.clear();
}

void BrowserInputHandler::process_sdl_key_event(const SDL_Event& event) {
    bool pressed = (event.type == SDL_EVENT_KEY_DOWN);
    int key_code = static_cast<int>(event.key.key);
    int scan_code = static_cast<int>(event.key.scancode);
    int modifiers = 0;

    Uint32 sdl_mod = event.key.mod;
    if (sdl_mod & SDL_KMOD_CTRL) modifiers |= EVENTFLAG_CONTROL_DOWN;
    if (sdl_mod & SDL_KMOD_SHIFT) modifiers |= EVENTFLAG_SHIFT_DOWN;
    if (sdl_mod & SDL_KMOD_ALT) modifiers |= EVENTFLAG_ALT_DOWN;
    if (sdl_mod & SDL_KMOD_GUI) modifiers |= EVENTFLAG_COMMAND_DOWN;
    if (sdl_mod & SDL_KMOD_CAPS) modifiers |= EVENTFLAG_CAPS_LOCK_ON;
    if (sdl_mod & SDL_KMOD_NUM) modifiers |= EVENTFLAG_NUM_LOCK_ON;

    bool is_common_edit_shortcut = false;
    if (modifiers & EVENTFLAG_CONTROL_DOWN) {
        switch (key_code) {
            case SDLK_A:
            case SDLK_C:
            case SDLK_V:
            case SDLK_Z:
            case SDLK_Y:
                is_common_edit_shortcut = true;
                break;
            default:
                break;
        }
    }

    bool is_modifier_combo = (modifiers & (EVENTFLAG_CONTROL_DOWN | EVENTFLAG_ALT_DOWN)) &&
                             ((key_code >= 'a' && key_code <= 'z') ||
                              (key_code >= 'A' && key_code <= 'Z') ||
                              (key_code >= '0' && key_code <= '9'));

    PendingKeyEvent key_event(PendingKeyEvent::kKeyEvent);
    key_event.key_code = key_code;
    key_event.scan_code = scan_code;
    key_event.modifiers = modifiers;
    key_event.pressed = pressed;
    key_event.is_modifier_combo = is_modifier_combo || is_common_edit_shortcut;

    pending_key_events_.push_back(key_event);
}

void BrowserInputHandler::process_sdl_text_event(const SDL_Event& event) {
    if (event.text.text && event.text.text[0]) {
        PendingKeyEvent text_event(PendingKeyEvent::kTextEvent);
        text_event.text = event.text.text;
        pending_key_events_.push_back(text_event);
    }
}

void BrowserInputHandler::process_sdl_ime_event(const SDL_Event& event) {
    if (event.edit.text && event.edit.text[0]) {
        PendingKeyEvent ime_event(PendingKeyEvent::kImeComposition);
        ime_event.text = event.edit.text;
        ime_event.ime_start = event.edit.start;
        ime_event.ime_length = event.edit.length;
        pending_key_events_.push_back(ime_event);
    }
}

void BrowserInputHandler::send_key_events_to_browser(const CefRefPtr<CefBrowser>& browser) {
    if (!browser) return;

    for (const auto& pending_event : pending_key_events_) {
        if (pending_event.type == PendingKeyEvent::kKeyEvent) {
            CefKeyEvent cef_key_event;
            cef_key_event.type = pending_event.pressed ? KEYEVENT_RAWKEYDOWN : KEYEVENT_KEYUP;
            cef_key_event.windows_key_code = KeyUtils::convert_sdl_key_code_to_windows(pending_event.key_code);
            cef_key_event.native_key_code = pending_event.scan_code;
            cef_key_event.modifiers = pending_event.modifiers;
            cef_key_event.character = pending_event.key_code;
            cef_key_event.unmodified_character = pending_event.key_code;

            bool is_common_edit_shortcut = false;
            if (pending_event.modifiers & EVENTFLAG_CONTROL_DOWN) {
                switch (pending_event.key_code) {
                    case SDLK_A:
                    case SDLK_C:
                    case SDLK_V:
                    case SDLK_Z:
                    case SDLK_Y:
                        is_common_edit_shortcut = true;
                        break;
                    default:
                        break;
                }
            }

            browser->GetHost()->SendKeyEvent(cef_key_event);

            if (pending_event.pressed &&
                (pending_event.key_code == SDLK_RETURN || pending_event.key_code == SDLK_KP_ENTER)) {
                CefKeyEvent char_event = cef_key_event;
                char_event.type = KEYEVENT_CHAR;
                char_event.character = 0x0D;
                char_event.unmodified_character = 0x0D;
                browser->GetHost()->SendKeyEvent(char_event);
            }

            if (pending_event.pressed && pending_event.is_modifier_combo) {
                if (is_common_edit_shortcut) {
                    cef_key_event.type = KEYEVENT_CHAR;
                    browser->GetHost()->SendKeyEvent(cef_key_event);
                } else {
                    switch (pending_event.key_code) {
                        case SDLK_RETURN:
                        case SDLK_KP_ENTER:
                        case SDLK_TAB:
                        case SDLK_BACKSPACE:
                        case SDLK_DELETE:
                        case SDLK_ESCAPE:
                            cef_key_event.type = KEYEVENT_CHAR;
                            browser->GetHost()->SendKeyEvent(cef_key_event);
                            break;
                        default:
                            break;
                    }
                }
            }
        } else if (pending_event.type == PendingKeyEvent::kTextEvent) {
            const std::string& text = pending_event.text;
            if (!text.empty()) {
                bool has_control_chars = false;
                for (char c : text) {
                    if (c == '\b' || c == '\t' || c == '\n' || c == '\r') {
                        has_control_chars = true;
                        break;
                    }
                }

                if (!has_control_chars) {
                    bool is_ascii = true;
                    for (char c : text) {
                        if (static_cast<unsigned char>(c) >= 128) {
                            is_ascii = false;
                            break;
                        }
                    }

                    if (is_ascii) {
                        for (char c : text) {
                            if (c >= 32 && c < 127) {
                                CefKeyEvent cef_text_event;
                                cef_text_event.type = KEYEVENT_CHAR;
                                cef_text_event.modifiers = 0;
                                cef_text_event.windows_key_code = static_cast<uint16_t>(c);
                                cef_text_event.native_key_code = static_cast<uint16_t>(c);
                                cef_text_event.character = static_cast<uint16_t>(c);
                                cef_text_event.unmodified_character = static_cast<uint16_t>(c);
                                browser->GetHost()->SendKeyEvent(cef_text_event);
                            }
                        }
                    } else {
                        if (char* utf16_text = SDL_iconv_string("UTF-16LE", "UTF-8", text.c_str(), text.length() + 1)) {
                            auto* utf16_chars = reinterpret_cast<uint16_t*>(utf16_text);
                            size_t utf16_len = 0;
                            while (utf16_chars[utf16_len] != 0) {
                                utf16_len++;
                            }
                            for (size_t i = 0; i < utf16_len; i++) {
                                CefKeyEvent cef_text_event;
                                cef_text_event.type = KEYEVENT_CHAR;
                                cef_text_event.modifiers = 0;
                                cef_text_event.windows_key_code = utf16_chars[i];
                                cef_text_event.native_key_code = utf16_chars[i];
                                cef_text_event.character = utf16_chars[i];
                                cef_text_event.unmodified_character = utf16_chars[i];
                                browser->GetHost()->SendKeyEvent(cef_text_event);
                            }
                            SDL_free(utf16_text);
                        }
                    }
                }
            }
        }
    }

    clear_pending_events();
}

// ============================================================================
// BrowserRenderer 实现
// ============================================================================

static MouseUtils::MouseStateManager mouse_state;

void BrowserRenderer::setup_window_transform(BrowserTab* tab,
                                             ImGuiID dock_space_id,
                                             bool is_main_tab) {
    if (is_main_tab) {
        ImGui::SetNextWindowDockID(dock_space_id, ImGuiCond_Always);
    } else {
        ImGuiViewport* browser_viewport = ImGui::GetMainViewport();
        ImVec2 work_pos = browser_viewport->WorkPos;
        ImVec2 work_size = browser_viewport->WorkSize;

        auto target_w = static_cast<float>(tab->dock_width);
        auto target_h = static_cast<float>(tab->dock_height);

        ImVec2 final_pos = work_pos;

        if (tab->docking_pos == "left_top") {
            final_pos.x = work_pos.x;
            final_pos.y = work_pos.y + 50.f;
        } else if (tab->docking_pos == "left_bottom") {
            final_pos.x = work_pos.x;
            final_pos.y = work_pos.y + work_size.y - target_h;
        } else if (tab->docking_pos == "right_top") {
            final_pos.x = work_pos.x + work_size.x - target_w;
            final_pos.y = work_pos.y + 50.f;
        } else if (tab->docking_pos == "right_bottom") {
            final_pos.x = work_pos.x + work_size.x - target_w;
            final_pos.y = work_pos.y + work_size.y - target_h;
        } else if (tab->docking_pos == "bottom_left") {
            final_pos.x = work_pos.x + 300.f;
            final_pos.y = work_pos.y + work_size.y - target_h;
        } else if (tab->docking_pos == "bottom_right") {
            final_pos.x = work_pos.x + work_size.x - target_w - 300.f;
            final_pos.y = work_pos.y + work_size.y - target_h;
        } else {
            final_pos.x = work_pos.x + 300.f;
            final_pos.y = work_pos.y + 50.f;
        }

        ImGui::SetNextWindowPos(final_pos, ImGuiCond_FirstUseEver);
        ImGui::SetNextWindowSize(ImVec2(target_w, target_h), ImGuiCond_FirstUseEver);

        tab->dock_initialized = true;
    }
}

void BrowserRenderer::handle_browser_mouse_events(BrowserTab* tab,
                                                  int tab_id,
                                                  int& active_tab_id,
                                                  int& url_input_active_tab,
                                                  const ImGuiIO* io,
                                                  bool is_dragging) {
    if (is_dragging) return;  // 拖拽期间不处理浏览器鼠标事件

    const bool is_hovered = ImGui::IsItemHovered();
    const bool is_active = (active_tab_id == tab_id);
    const ImVec2 mouse_pos = ImGui::GetMousePos();
    const ImVec2 item_pos = ImGui::GetItemRectMin();  // 窗口内容区域起点

    auto browser = tab->client ? tab->client->GetBrowser() : nullptr;
    if (!browser) return;

    // 1. 处理点击事件 (按下/释放)
    auto process_button = [&](ImGuiMouseButton imgui_btn, CefBrowserHost::MouseButtonType cef_btn) {
        if (is_hovered) {
            if (ImGui::IsMouseClicked(imgui_btn)) {
                active_tab_id = tab_id;
                url_input_active_tab = -1;
                browser->GetHost()->SetFocus(true);

                int clicks = (imgui_btn == ImGuiMouseButton_Left) ? mouse_state.handle_mouse_click(mouse_pos, SDL_GetTicks()) : 1;

                if (imgui_btn == ImGuiMouseButton_Left) mouse_state.set_mouse_down(true);

                MouseUtils::send_mouse_click(browser, mouse_pos, item_pos, cef_btn, false, clicks);
            }
        }

        if (ImGui::IsMouseReleased(imgui_btn)) {
            bool was_down = (imgui_btn == ImGuiMouseButton_Left && mouse_state.is_mouse_down());
            if (is_hovered || (was_down && is_active)) {
                MouseUtils::send_mouse_click(browser, mouse_pos, item_pos, cef_btn, true, 1);
                if (imgui_btn == ImGuiMouseButton_Left) {
                    mouse_state.set_mouse_down(false);
                    mouse_state.set_dragging(false);
                }
            }
        }
    };

    process_button(ImGuiMouseButton_Left, MBT_LEFT);
    process_button(ImGuiMouseButton_Right, MBT_RIGHT);
    process_button(ImGuiMouseButton_Middle, MBT_MIDDLE);

    // 2. 处理移动事件
    if (is_hovered || mouse_state.is_mouse_down()) {
        MouseUtils::send_mouse_move(browser, mouse_pos, item_pos, !is_hovered);

        if (mouse_state.is_mouse_down()) {
            ImVec2 drag_delta = ImGui::GetMouseDragDelta(ImGuiMouseButton_Left, 0.0f);
            if (drag_delta.x * drag_delta.x + drag_delta.y * drag_delta.y > 4.0f) {
                mouse_state.set_dragging(true);
            }
        }
    }

    // 3. 处理滚轮
    if (is_hovered && io->MouseWheel != 0) {
        MouseUtils::send_mouse_wheel(browser, mouse_pos, item_pos, io->MouseWheel);
    }
}

void BrowserRenderer::render_single_tab(int tab_id,
                                        ImGuiID dock_space_id,
                                        int& active_tab_id,
                                        int& url_input_active_tab,
                                        ImGuiIO* io) {
    auto* tab = BrowserManager::instance().get_tab(tab_id);
    if (!tab || !tab->open) return;

    BrowserManager::instance().update_texture(tab_id);

    std::string window_id = tab->name + "##" + std::to_string(tab_id);

    ImGuiWindowFlags browser_window_flags = ImGuiWindowFlags_NoTitleBar |
                                            ImGuiWindowFlags_NoScrollbar |
                                            ImGuiWindowFlags_NoNavInputs |
                                            ImGuiWindowFlags_NoNavFocus |
                                            ImGuiWindowFlags_NoMove;

    bool is_main_tab = (tab->docking_pos == "main");
    if (is_main_tab) {
        browser_window_flags |= ImGuiWindowFlags_NoMove;  // 主窗口始终禁止移动
    }

    setup_window_transform(tab, dock_space_id, is_main_tab);

    if (ImGui::Begin(window_id.c_str(), &tab->open, browser_window_flags)) {
        ImVec2 window_pos = ImGui::GetWindowPos();
        ImVec2 content_min = ImGui::GetWindowContentRegionMin();
        ImVec2 cef_origin = ImVec2(window_pos.x + content_min.x, window_pos.y + content_min.y);

        ImVec2 avail_size = ImGui::GetContentRegionAvail();
        int new_width = static_cast<int>(avail_size.x);
        int new_height = static_cast<int>(avail_size.y);
        if (new_width > 0 && new_height > 0 &&
            (new_width != tab->width || new_height != tab->height)) {
            BrowserManager::instance().resize_tab(tab_id, new_width, new_height);
        }

        // ----------------- 拖拽区域检测与启动窗口移动 -----------------
        if (!is_main_tab) {
            bool in_drag_region = false;

            // 检测鼠标是否在拖拽区域内（若为空则全区域可拖拽）
            {
                std::lock_guard<std::mutex> lock(tab->drag_mutex);
               
                for (const auto& region : tab->drag_regions) {
                    ImRect abs_region(
                        cef_origin.x + region.x,
                        cef_origin.y + region.y,
                        cef_origin.x + region.x + region.width,
                        cef_origin.y + region.y + region.height);
                    if (abs_region.Contains(io->MousePos)) {
                        in_drag_region = true;
                        break;
                    }
                }
            }

            // 光标样式
            if (in_drag_region) {
                ImGui::SetMouseCursor(ImGuiMouseCursor_ResizeAll);
            }

            // 拖拽启动逻辑（区分点击与拖拽）
            if (in_drag_region && ImGui::IsMouseClicked(ImGuiMouseButton_Left) && !tab->dragging_window) {
                tab->drag_pending = true;
                tab->drag_pending_start_pos = io->MousePos;
            }

            // 待拖拽状态，检查移动距离
            if (tab->drag_pending && !tab->dragging_window) {
                ImVec2 delta(io->MousePos.x - tab->drag_pending_start_pos.x,
                             io->MousePos.y - tab->drag_pending_start_pos.y);
                float distance = sqrtf(delta.x * delta.x + delta.y * delta.y);
                if (distance > 5.0f) {  // 拖拽阈值
                    tab->dragging_window = true;
                    tab->drag_pending = false;

                    ImGuiWindow* window = ImGui::GetCurrentWindow();

                    // 如果窗口已停靠，先分离
                    if (window->DockNode) {
                        ImGuiContext* g = ImGui::GetCurrentContext();
                        ImGui::DockContextProcessUndockWindow(g, window);
                        window = ImGui::GetCurrentWindow();  // 分离后窗口可能重建
                    }

                    window->Flags &= ~ImGuiWindowFlags_NoMove;  // 允许移动

                    // 启动 ImGui 内置窗口移动（支持Multi-Viewport跨窗口拖拽）
                    ImGui::StartMouseMovingWindow(window);
                } else if (ImGui::IsMouseReleased(ImGuiMouseButton_Left)) {
                    tab->drag_pending = false;  // 视为点击
                }
            }

            // 拖拽结束：重置状态
            if (ImGui::IsMouseReleased(ImGuiMouseButton_Left)) {
                tab->dragging_window = false;
                tab->drag_pending = false;
            }
        }
        // -------------------------------------------------------------

        // 渲染浏览器纹理
        if (is_valid_texture_id(tab->texture_id)) {
            ImGui::Image(tab->texture_id, avail_size);
        }

        // 仅当未拖拽时传递鼠标事件给浏览器
        if (!tab->dragging_window) {
            handle_browser_mouse_events(tab, tab_id, active_tab_id, url_input_active_tab, io);
        }
    }
    ImGui::End();
}

std::vector<int> BrowserRenderer::render_browser_tabs(ImGuiID dock_space_id,
                                                      int& active_tab_id,
                                                      int& url_input_active_tab,
                                                      ImGuiIO* io) {
    std::vector<int> tabs_to_close;
    auto& tabs = BrowserManager::instance().get_tabs();

    for (auto& [tab_id, tab] : tabs) {
        if (!tab->open) {
            tabs_to_close.push_back(tab_id);
            continue;
        }
        if (tab->minimized) {
            continue;
        }

        render_single_tab(tab_id, dock_space_id, active_tab_id, url_input_active_tab, io);
    }

    return tabs_to_close;
}

}  // namespace Corona::Systems::UI