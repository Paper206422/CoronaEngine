/**
 * @brief CEF 子进程可执行文件
 *
 * 这是一个轻量级的可执行文件，专门用于 CEF 子进程（Browser, Renderer, GPU 等）。
 * 使用单独的可执行文件可以避免主引擎的静态初始化代码在子进程中执行。
 */

#include <cef_app.h>
#include <include/cef_v8.h>
#include <wrapper/cef_helpers.h>
#include <wrapper/cef_message_router.h>

#include <iostream>

#ifdef _WIN32
#include <windows.h>
#endif

// 与主程序使用相同的消息路由配置
static CefMessageRouterConfig GetMessageRouterConfig() {
    CefMessageRouterConfig config;
    config.js_query_function = "cefQuery";
    config.js_cancel_function = "cefQueryCancel";
    return config;
}

// 渲染进程处理器 - 负责在渲染进程中注入 cefQuery 函数
class SubprocessRenderHandler : public CefRenderProcessHandler {
   public:
    SubprocessRenderHandler() : renderer_side_router_(nullptr) {}

    class FastCameraMoveHandler : public CefV8Handler {
       public:
        bool Execute(const CefString& name,
                     CefRefPtr<CefV8Value> object,
                     const CefV8ValueList& arguments,
                     CefRefPtr<CefV8Value>& retval,
                     CefString& exception) override {
            if (name == "actorTransform") {
                if (arguments.size() < 3) {
                    exception = "actorTransform(handle, operation, vector) requires 3 arguments";
                    retval = CefV8Value::CreateBool(false);
                    return true;
                }

                const auto handle_value = arguments[0];
                if (!handle_value || (!handle_value->IsInt() && !handle_value->IsDouble())) {
                    exception = "actorTransform: handle must be a number";
                    retval = CefV8Value::CreateBool(false);
                    return true;
                }

                const auto operation_value = arguments[1];
                if (!operation_value || !operation_value->IsInt()) {
                    exception = "actorTransform: operation must be an integer";
                    retval = CefV8Value::CreateBool(false);
                    return true;
                }

                const auto vector_value = arguments[2];
                if (!vector_value || !vector_value->IsArray() || vector_value->GetArrayLength() != 3) {
                    exception = "actorTransform: vector must be number[3]";
                    retval = CefV8Value::CreateBool(false);
                    return true;
                }

                auto context = CefV8Context::GetCurrentContext();
                if (!context || !context->GetBrowser()) {
                    retval = CefV8Value::CreateBool(false);
                    return true;
                }

                CefRefPtr<CefProcessMessage> message = CefProcessMessage::Create("ActorTransformFast");
                CefRefPtr<CefListValue> args = message->GetArgumentList();
                args->SetDouble(0, handle_value->GetDoubleValue());
                args->SetInt(1, operation_value->GetIntValue());

                auto vector_list = CefListValue::Create();
                for (int i = 0; i < 3; ++i) {
                    auto elem = vector_value->GetValue(i);
                    if (!elem || (!elem->IsInt() && !elem->IsDouble())) {
                        exception = "actorTransform: vector must be number[3]";
                        retval = CefV8Value::CreateBool(false);
                        return true;
                    }
                    if (elem->IsInt()) {
                        vector_list->SetInt(i, elem->GetIntValue());
                    } else {
                        vector_list->SetDouble(i, elem->GetDoubleValue());
                    }
                }

                args->SetList(2, vector_list);
                context->GetFrame()->SendProcessMessage(PID_BROWSER, message);
                retval = CefV8Value::CreateBool(true);
                return true;
            }

            if (name != "cameraMove") {
                return false;
            }

            if (arguments.size() < 5) {
                exception = "cameraMove(handle, position, forward, up, fov) requires 5 arguments";
                retval = CefV8Value::CreateBool(false);
                return true;
            }

            const auto handle_value = arguments[0];
            if (!handle_value || (!handle_value->IsInt() && !handle_value->IsDouble())) {
                exception = "cameraMove: handle must be a number";
                retval = CefV8Value::CreateBool(false);
                return true;
            }

            auto read_vec3 = [&](const CefRefPtr<CefV8Value>& value, CefRefPtr<CefListValue> out) -> bool {
                if (!value || !value->IsArray() || value->GetArrayLength() != 3) {
                    return false;
                }
                for (int i = 0; i < 3; ++i) {
                    auto elem = value->GetValue(i);
                    if (!elem || (!elem->IsInt() && !elem->IsDouble())) {
                        return false;
                    }
                    if (elem->IsInt()) {
                        out->SetInt(i, elem->GetIntValue());
                    } else {
                        out->SetDouble(i, elem->GetDoubleValue());
                    }
                }
                return true;
            };

            auto context = CefV8Context::GetCurrentContext();
            if (!context) {
                retval = CefV8Value::CreateBool(false);
                return true;
            }

            auto browser = context->GetBrowser();
            if (!browser) {
                retval = CefV8Value::CreateBool(false);
                return true;
            }

            CefRefPtr<CefProcessMessage> message = CefProcessMessage::Create("CameraMoveFast");
            CefRefPtr<CefListValue> args = message->GetArgumentList();
            args->SetDouble(0, handle_value->GetDoubleValue());

            auto pos_list = CefListValue::Create();
            auto fwd_list = CefListValue::Create();
            auto up_list = CefListValue::Create();

            if (!read_vec3(arguments[1], pos_list) ||
                !read_vec3(arguments[2], fwd_list) ||
                !read_vec3(arguments[3], up_list)) {
                exception = "cameraMove: position/forward/up must be number[3]";
                retval = CefV8Value::CreateBool(false);
                return true;
            }

            args->SetList(1, pos_list);
            args->SetList(2, fwd_list);
            args->SetList(3, up_list);

            if (!arguments[4] || (!arguments[4]->IsInt() && !arguments[4]->IsDouble())) {
                exception = "cameraMove: fov must be a number";
                retval = CefV8Value::CreateBool(false);
                return true;
            }

            if (arguments[4]->IsInt()) {
                args->SetInt(4, arguments[4]->GetIntValue());
            } else {
                args->SetDouble(4, arguments[4]->GetDoubleValue());
            }
            context->GetFrame()->SendProcessMessage(PID_BROWSER, message);
            retval = CefV8Value::CreateBool(true);
            return true;
        }

        IMPLEMENT_REFCOUNTING(FastCameraMoveHandler);
    };

    void OnContextCreated(CefRefPtr<CefBrowser> browser,
                          CefRefPtr<CefFrame> frame,
                          CefRefPtr<CefV8Context> context) override {
        if (!renderer_side_router_) {
            renderer_side_router_ = CefMessageRouterRendererSide::Create(GetMessageRouterConfig());
        }

        // 将 cefQuery 和 cefQueryCancel 函数注入到 window 对象中
        renderer_side_router_->OnContextCreated(browser, frame, context);

        CefRefPtr<CefV8Value> global = context->GetGlobal();
        CefRefPtr<CefV8Value> bridge = CefV8Value::CreateObject(nullptr, nullptr);
        CefRefPtr<CefV8Handler> handler(new FastCameraMoveHandler());
        CefRefPtr<CefV8Value> camera_move = CefV8Value::CreateFunction("cameraMove", handler);
        CefRefPtr<CefV8Value> actor_transform = CefV8Value::CreateFunction("actorTransform", handler);
        bridge->SetValue("cameraMove", camera_move, V8_PROPERTY_ATTRIBUTE_NONE);
        bridge->SetValue("actorTransform", actor_transform, V8_PROPERTY_ATTRIBUTE_NONE);
        global->SetValue("coronaBridge", bridge, V8_PROPERTY_ATTRIBUTE_NONE);

        std::cout << "[Renderer] V8 context created, cefQuery injected" << std::endl;
    }

    void OnContextReleased(CefRefPtr<CefBrowser> browser,
                           CefRefPtr<CefFrame> frame,
                           CefRefPtr<CefV8Context> context) override {
        if (renderer_side_router_) {
            renderer_side_router_->OnContextReleased(browser, frame, context);
        }
    }

    bool OnProcessMessageReceived(CefRefPtr<CefBrowser> browser,
                                  CefRefPtr<CefFrame> frame,
                                  CefProcessId source_process,
                                  CefRefPtr<CefProcessMessage> message) override {
        if (renderer_side_router_) {
            return renderer_side_router_->OnProcessMessageReceived(
                browser, frame, source_process, message);
        }
        return false;
    }

   private:
    CefRefPtr<CefMessageRouterRendererSide> renderer_side_router_;
    IMPLEMENT_REFCOUNTING(SubprocessRenderHandler);
};

// CefApp 实现，用于子进程
class SubprocessApp : public CefApp {
   public:
    SubprocessApp() : render_handler_(new SubprocessRenderHandler()) {}

    CefRefPtr<CefRenderProcessHandler> GetRenderProcessHandler() override {
        return render_handler_;
    }

   private:
    CefRefPtr<SubprocessRenderHandler> render_handler_;
    IMPLEMENT_REFCOUNTING(SubprocessApp);
};

#ifdef _WIN32
int APIENTRY wWinMain(HINSTANCE hInstance,
                      HINSTANCE hPrevInstance,
                      LPWSTR lpCmdLine,
                      int nCmdShow) {
    CefMainArgs main_args(hInstance);
#else
int main(int argc, char* argv[]) {
    CefMainArgs main_args(argc, argv);
#endif

    CefRefPtr<SubprocessApp> app(new SubprocessApp());

    // 执行 CEF 子进程逻辑
    // 这将阻塞直到子进程结束
    return CefExecuteProcess(main_args, app.get(), nullptr);
}
