#include "cef_client.h"

#include <corona/kernel/core/i_logger.h>

#include <algorithm>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <windows.h>

#include "browser_manager.h"

namespace Corona::Systems::UI {

// ============================================================================
// BrowserSideJSHandler 实现
// ============================================================================

BrowserSideJSHandler::~BrowserSideJSHandler() {
    PyGILState_STATE state = PyGILState_Ensure();
    Py_XDECREF(pFunc_);
    PyGILState_Release(state);
}

void BrowserSideJSHandler::initialize_python() {
    if (!Py_IsInitialized()) {
        Py_Initialize();
        PyEval_SaveThread();
    }

    PyGILState_STATE state = PyGILState_Ensure();
    PyObject* pModule = nullptr;

    try {
        PyRun_SimpleString("import sys");
        PyRun_SimpleString("import os");
        PyRun_SimpleString("sys.path.insert(0, os.path.join(os.getcwd(), 'CabbageEditor'))");

        PyObject* pName = PyUnicode_FromString("main");
        if (!pName) {
            throw std::runtime_error("Failed to create module name");
        }

        pModule = PyImport_Import(pName);
        Py_DECREF(pName);

        if (!pModule) {
            PyErr_Print();
            PyGILState_Release(state);
            throw std::runtime_error("Failed to import Python module 'main'");
        }

        PyObject* pClass = PyObject_GetAttrString(pModule, "editor");
        if (!pClass) {
            Py_DECREF(pModule);
            PyErr_Print();
            PyGILState_Release(state);
            throw std::runtime_error("Failed to get 'editor' attribute from module");
        }

        if (PyCallable_Check(pClass)) {
            pFunc_ = PyObject_GetAttrString(pClass, "deal_func_from_js");
        }

        Py_DECREF(pClass);
        Py_DECREF(pModule);

    } catch (const std::exception&) {
        if (pModule) {
            Py_DECREF(pModule);
        }
        PyErr_Print();
        PyGILState_Release(state);
        throw;
    }

    PyGILState_Release(state);
}

bool BrowserSideJSHandler::OnQuery(CefRefPtr<CefBrowser> browser,
                                   CefRefPtr<CefFrame> frame,
                                   int64_t query_id,
                                   const CefString& request,
                                   bool persistent,
                                   CefRefPtr<Callback> callback) {
    CEF_REQUIRE_UI_THREAD();
    std::string req = request.ToString();
    VUE_LOG_INFO("Received query: {}", req.c_str());

    if (!Py_IsInitialized()) {
        Py_Initialize();
        PyEval_SaveThread();
    }

    PyGILState_STATE gstate = PyGILState_Ensure();

    try {
        if (!pFunc_) {
            initialize_python();
        }

        PyObject* args = PyTuple_Pack(1, PyUnicode_FromString(req.c_str()));
        PyObject* object = PyObject_CallObject(pFunc_, args);
        Py_DECREF(args);

        if (!object) {
            PyErr_Print();
            VUE_LOG_ERROR("Python function call failed for request");
            callback->Failure(0, "Python function call failed");
        } else {
            if (PyUnicode_Check(object)) {
                const char* result = PyUnicode_AsUTF8(object);
                callback->Success(result);
            } else {
                if (PyObject* str_obj = PyObject_Str(object)) {
                    const char* result = PyUnicode_AsUTF8(str_obj);
                    callback->Success(result);
                    Py_DECREF(str_obj);
                }
            }
            Py_DECREF(object);
        }

    } catch (const std::exception& e) {
        std::cerr << "Exception in OnQuery: " << e.what() << std::endl;
        callback->Failure(0, e.what());
        PyGILState_Release(gstate);
        return false;
    }

    PyGILState_Release(gstate);
    return true;
}

// ============================================================================
// OffscreenRenderHandler 实现
// ============================================================================

void OffscreenRenderHandler::GetViewRect(CefRefPtr<CefBrowser> browser, CefRect& rect) {
    if (tab) {
        rect = CefRect(0, 0, tab->width, tab->height);
    } else {
        rect = CefRect(0, 0, 800, 600);
    }
}

void OffscreenRenderHandler::OnPaint(CefRefPtr<CefBrowser> browser, PaintElementType type,
                                     const RectList& dirty_rects, const void* buffer,
                                     int width, int height) {
    if (tab && type == PET_VIEW) {
        size_t bufferSize = width * height * 4;
        std::lock_guard<std::mutex> lock(tab->mutex);
        tab->pixel_buffer.resize(bufferSize);
        std::memcpy(tab->pixel_buffer.data(), buffer, bufferSize);

        // CEF outputs BGRA on Windows; convert to RGBA for Vulkan RGBA8 textures.
        auto* pixels = tab->pixel_buffer.data();
        for (size_t i = 0; i < bufferSize; i += 4) {
            std::swap(pixels[i], pixels[i + 2]);
        }

        tab->buffer_dirty = true;
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
        case LOGSEVERITY_DEBUG:   levelStr = "DEBUG"; break;
        case LOGSEVERITY_INFO:    levelStr = "INFO"; break;
        case LOGSEVERITY_WARNING: levelStr = "WARNING"; break;
        case LOGSEVERITY_ERROR:   levelStr = "ERROR"; break;
        default: break;
    }

    // if (!source.empty()) {
    //     VUE_LOG_INFO("[{}] {}:{} - {}", levelStr, source.ToString().c_str(), line, message.ToString().c_str());
    // } else {
    //     VUE_LOG_INFO("[{}] {}", levelStr, message.ToString().c_str());
    // }
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
    if (message->GetName() == "RendererMessage") {
        std::string msg = message->GetArgumentList()->GetString(0);
        CFW_LOG_INFO("CEF: Received message from Renderer: {}", msg);
        return true;
    }
    if (browser_side_router_) {
        return browser_side_router_->OnProcessMessageReceived(browser, frame, source_process, message);
    }
    return false;
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

    CefString(&settings.user_agent).FromASCII(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36");
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
