#include "cef_client.h"

#include <windows.h>

#include <algorithm>
#include <cstring>
#include <filesystem>
#include <string>

#include "browser_manager.h"
#include "cef_bridge_helpers.h"

namespace Corona::Systems::UI {

// ============================================================================
// OffscreenRenderHandler 实现
// ============================================================================

void OffscreenRenderHandler::GetViewRect(CefRefPtr<CefBrowser> browser, CefRect& rect) {
    BrowserTab* t = tab;
    if (t) {
        rect = CefRect(0, 0, t->width, t->height);
    } else {
        rect = CefRect(0, 0, 800, 600);
    }
}

void OffscreenRenderHandler::OnPaint(CefRefPtr<CefBrowser> browser, PaintElementType type,
                                     const RectList& dirty_rects, const void* buffer,
                                     int width, int height) {
    // 捕获 tab 指针到局部变量，避免 remove_tab 在回调期间将其置空导致的竞争
    BrowserTab* t = tab;
    if (t && type == PET_VIEW && buffer && width > 0 && height > 0) {
        size_t bufferSize = static_cast<size_t>(width) * height * 4;
        std::lock_guard<std::mutex> lock(t->mutex);
        t->pixel_buffer.resize(bufferSize);
        std::memcpy(t->pixel_buffer.data(), buffer, bufferSize);

        // CEF outputs BGRA on Windows; convert to RGBA for Vulkan RGBA8 textures.
        auto* pixels = t->pixel_buffer.data();
        for (size_t i = 0; i < bufferSize; i += 4) {
            std::swap(pixels[i], pixels[i + 2]);
        }

        t->buffer_dirty = true;
    }
}

bool OffscreenRenderHandler::GetScreenPoint(CefRefPtr<CefBrowser> browser, int viewX, int viewY, int& screenX, int& screenY) {
    if (!tab) return false;

    // 将局部坐标转换成屏幕绝对坐标
    POINT mouse_pt;
    GetCursorPos(&mouse_pt);
    screenX = mouse_pt.x;
    screenY = mouse_pt.y;
    return true;
}

// ============================================================================
// OffscreenCefClient 实现
// ============================================================================

OffscreenCefClient::OffscreenCefClient()
    : browser_(nullptr),
      render_handler_(new OffscreenRenderHandler()),
      browser_side_router_(nullptr),
      js_handler_(nullptr) {
}

CefRefPtr<CefRenderHandler> OffscreenCefClient::GetRenderHandler() {
    return render_handler_;
}

void OffscreenCefClient::SetTab(BrowserTab* tab) {
    if (render_handler_) {
        render_handler_->tab = tab;
    }
}

void OffscreenCefClient::OnAfterCreated(CefRefPtr<CefBrowser> browser) {
    CEF_REQUIRE_UI_THREAD();

    if (!browser_) {
        browser_ = browser;
    }

    if (!browser_side_router_) {
        CefMessageRouterConfig config;
        config.js_query_function = "cefQuery";
        config.js_cancel_function = "cefQueryCancel";
        browser_side_router_ = CefMessageRouterBrowserSide::Create(config);

        js_handler_ = new BrowserSideJSHandler();
        browser_side_router_->AddHandler(js_handler_, true);
    }
}

void OffscreenCefClient::OnLoadEnd(CefRefPtr<CefBrowser> browser,
                                   CefRefPtr<CefFrame> frame,
                                   int httpStatusCode) {
    CEF_REQUIRE_UI_THREAD();
    // Main frame load end
}

void OffscreenCefClient::OnBeforeClose(CefRefPtr<CefBrowser> browser) {
    CEF_REQUIRE_UI_THREAD();
    browser_ = nullptr;
    if (browser_side_router_) {
        browser_side_router_->OnBeforeClose(browser);
    }
}

void OffscreenCefClient::Resize(int width, int height) {
    if (browser_) {
        browser_->GetHost()->WasResized();
    }
}

bool OffscreenCefClient::OnBeforeBrowse(CefRefPtr<CefBrowser> browser,
                                        CefRefPtr<CefFrame> frame,
                                        CefRefPtr<CefRequest> request,
                                        bool user_gesture,
                                        bool is_redirect) {
    CEF_REQUIRE_UI_THREAD();
    if (browser_side_router_) {
        browser_side_router_->OnBeforeBrowse(browser, frame);
    }
    return false;
}

void OffscreenCefClient::GetViewRect(CefRefPtr<CefBrowser> browser, CefRect& rect) {
    if (render_handler_) {
        render_handler_->GetViewRect(browser, rect);
    }
}

void OffscreenCefClient::OnPaint(CefRefPtr<CefBrowser> browser, PaintElementType type,
                                 const RectList& dirtyRects, const void* buffer,
                                 int width, int height) {
    if (render_handler_) {
        render_handler_->OnPaint(browser, type, dirtyRects, buffer, width, height);
    }
}

bool OffscreenCefClient::OnConsoleMessage(CefRefPtr<CefBrowser> browser,
                                          cef_log_severity_t level,
                                          const CefString& message,
                                          const CefString& source,
                                          int line) {
    const char* levelStr = "LOG";
    switch (level) {
        case LOGSEVERITY_DEBUG:
            levelStr = "DEBUG";
            break;
        case LOGSEVERITY_INFO:
            levelStr = "INFO";
            break;
        case LOGSEVERITY_WARNING:
            levelStr = "WARNING";
            break;
        case LOGSEVERITY_ERROR:
            levelStr = "ERROR";
            break;
        default:
            break;
    }

    const auto msg = message.ToString();
    if (msg.find("ActorTransformFast") != std::string::npos || msg.find("coronaBridge") != std::string::npos) {
        VUE_LOG_INFO("[{}] {}", levelStr, msg.c_str());
    }
    return true;
}

void OffscreenCefClient::OnRenderProcessTerminated(CefRefPtr<CefBrowser> browser,
                                                   TerminationStatus status,
                                                   int error_code,
                                                   const CefString& error_string) {
    CEF_REQUIRE_UI_THREAD();
    if (browser_side_router_) {
        browser_side_router_->OnRenderProcessTerminated(browser);
    }
}

bool OffscreenCefClient::OnProcessMessageReceived(CefRefPtr<CefBrowser> browser,
                                                  CefRefPtr<CefFrame> frame,
                                                  CefProcessId source_process,
                                                  CefRefPtr<CefProcessMessage> message) {
    CEF_REQUIRE_UI_THREAD();
    if (handle_realtime_process_message(message)) {
        return true;
    }
    if (message->GetName() == "RendererMessage") {
        std::string msg = message->GetArgumentList()->GetString(0);
        CFW_LOG_INFO("CEF: Received message from Renderer: {}", msg);
        return true;
    }

    return forward_process_message_to_router(browser_side_router_, browser, frame, source_process, message);
}

// ============================================================================
// CefContextMenuHandler 实现
// ============================================================================

void OffscreenCefClient::OnBeforeContextMenu(CefRefPtr<CefBrowser> browser,
                                             CefRefPtr<CefFrame> frame,
                                             CefRefPtr<CefContextMenuParams> params,
                                             CefRefPtr<CefMenuModel> model) {
    CEF_REQUIRE_UI_THREAD();

    if (!model || !frame) {
        return;
    }

    // 清空现有菜单项（可选，如果只想保留自定义菜单）
    model->Clear();

    // 添加刷新菜单项
    model->AddItem(MENU_ID_REFRESH, "刷新页面");
}

bool OffscreenCefClient::OnContextMenuCommand(CefRefPtr<CefBrowser> browser,
                                              CefRefPtr<CefFrame> frame,
                                              CefRefPtr<CefContextMenuParams> params,
                                              int command_id,
                                              CefContextMenuHandler::EventFlags event_flags) {
    CEF_REQUIRE_UI_THREAD();

    if (!browser || !frame) {
        return false;
    }

    switch (command_id) {
        case MENU_ID_REFRESH:
            // 刷新当前页面
            browser->Reload();
            CFW_LOG_INFO("Browser refresh triggered via context menu");
            return true;
        default:
            return false;
    }
}

void OffscreenCefClient::OnContextMenuDismissed(CefRefPtr<CefBrowser> browser,
                                                CefRefPtr<CefFrame> frame) {
    CEF_REQUIRE_UI_THREAD();
    // 菜单关闭时的清理工作（可选）
}

// ============================================================================
// CefAppConfig 实现
// ============================================================================

void CefAppConfig::OnBeforeCommandLineProcessing(const CefString& process_type,
                                                 CefRefPtr<CefCommandLine> command_line) {
    command_line->AppendSwitch("disable-web-security");
    command_line->AppendSwitch("allow-file-access-from-files");
    command_line->AppendSwitch("allow-file-access");
    command_line->AppendSwitch("no-sandbox");
    command_line->AppendSwitch("disable-gpu");
    command_line->AppendSwitch("disable-gpu-compositing");
    command_line->AppendSwitch("enable-plugins");
    command_line->AppendSwitch("enable-net-benchmarking");
    command_line->AppendSwitch("disable-pdf-extension");
    command_line->AppendSwitch("disable-pdf-viewer");
    command_line->AppendSwitch("disable-component-update");
    command_line->AppendSwitch("disable-background-networking");
    command_line->AppendSwitch("disable-d3d11");
    command_line->AppendSwitch("disable-accelerated-video-decode");
}

// ============================================================================
// CEF 生命周期管理
// ============================================================================

CefMessageRouterConfig message_router_config;

bool initialize_cef() {
    message_router_config.js_query_function = "cefQuery";
    message_router_config.js_cancel_function = "cefQueryCancel";

    CefMainArgs main_args(GetModuleHandle(nullptr));
    CefRefPtr<CefAppConfig> app(new CefAppConfig());

    CefSettings settings;
    settings.multi_threaded_message_loop = true;
    settings.windowless_rendering_enabled = true;
    settings.no_sandbox = true;
    settings.remote_debugging_port = 9222;
    settings.log_severity = LOGSEVERITY_INFO;
    settings.uncaught_exception_stack_size = 10;

    CefString(&settings.locale).FromASCII("zh-CN");

    std::filesystem::path cache_path = std::filesystem::current_path() / "cache";
    if (!std::filesystem::exists(cache_path)) {
        std::filesystem::create_directories(cache_path);
    }
    CefString(&settings.cache_path).FromString(cache_path.string());

    // 使用单独的子进程可执行文件
    wchar_t exe_path[MAX_PATH];
    GetModuleFileNameW(nullptr, exe_path, MAX_PATH);
    std::filesystem::path exe_dir = std::filesystem::path(exe_path).parent_path();
    std::filesystem::path subprocess_path = exe_dir / "cef_subprocess.exe";

    if (std::filesystem::exists(subprocess_path)) {
        CefString(&settings.browser_subprocess_path).FromWString(subprocess_path.wstring());
        CFW_LOG_INFO("CEF: Using separate subprocess: {}", subprocess_path.string());
    } else {
        CefString(&settings.browser_subprocess_path).FromWString(exe_path);
        CFW_LOG_WARNING("CEF: cef_subprocess.exe not found, using main executable as subprocess");
    }

    CefString(&settings.user_agent).FromASCII("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36");
    settings.background_color = CefColorSetARGB(255, 255, 255, 255);
    settings.persist_session_cookies = true;

    CefRefPtr<CefCommandLine> command_line = CefCommandLine::CreateCommandLine();
    command_line->InitFromString(::GetCommandLineW());

    if (!CefInitialize(main_args, settings, app.get(), nullptr)) {
        CFW_LOG_ERROR("Failed to initialize CEF.");
        return false;
    }

    return true;
}

void shutdown_cef() {
    CFW_LOG_INFO("CEF: Starting shutdown...");
    CefShutdown();
    CFW_LOG_INFO("CEF: Shutdown complete");
}

}  // namespace Corona::Systems::UI
