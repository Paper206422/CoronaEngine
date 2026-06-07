#include <corona/events/engine_events.h>
#include <corona/events/script_system_events.h>
#include <corona/kernel/core/i_logger.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/systems/script/camera_follow_controller.h>
#include <corona/systems/script/python_api.h>
#include <corona/systems/script/script_system.h>
#include <nanobind/nanobind.h>

namespace Corona::Systems {

ScriptSystem::ScriptSystem()
    : python_api_(std::make_unique<Script::Python::PythonAPI>()) {
    set_target_fps(60);  // 显示系统高刷新率以提升响应速度
}

ScriptSystem::~ScriptSystem() = default;

bool ScriptSystem::initialize(Kernel::ISystemContext* ctx) {
    CFW_LOG_NOTICE("ScriptSystem: Initializing...");

    // 【订阅系统内部事件】使用 EventBus
    auto* event_bus = ctx->event_bus();
    if (event_bus) {
        python_start_id_ = event_bus->subscribe<Events::ImguiToPythonEvent>(
            [this](const Events::ImguiToPythonEvent& event) {
                // 检查是否正在关闭
                if (python_api_->is_shutting_down()) {
                    return;
                }
                CFW_LOG_INFO("ScriptSystem: Received ImguiToPythonEvent start");
                nanobind::gil_scoped_acquire gil;
                if (!python_api_->pStartFunc.is_valid()) {
                    return;
                }
                python_api_->pStartFunc();
            });

        js_call_python_id_ = event_bus->subscribe<Events::ImguiCallPythonEvent>(
            [this](const Events::ImguiCallPythonEvent& event) {
                // 检查是否正在关闭
                if (python_api_->is_shutting_down()) {
                    return;
                }
                CFW_LOG_INFO("ScriptSystem: Received ImguiCallPythonEvent js_call");
                nanobind::gil_scoped_acquire gil;
                if (!python_api_->pJsCallFunc.is_valid()) {
                    return;
                }
                python_api_->pJsCallFunc(event.args);
            });

        CFW_LOG_DEBUG("ScriptSystem: EventBus subscriptions ready");
    } else {
        CFW_LOG_WARNING("ScriptSystem: No event bus available");
    }

    return true;
}

void ScriptSystem::update() {
#ifdef CORONA_ENABLE_PYTHON_API
    CameraFollowController::instance().update(1.0f / 60.0f);
    python_api_->runPythonScript();
#endif
}

void ScriptSystem::shutdown() {
    CFW_LOG_NOTICE("ScriptSystem: Shutting down...");

    // 取消 EventBus 订阅
    if (auto* event_bus = context()->event_bus()) {
        if (python_start_id_ != 0) {
            event_bus->unsubscribe(python_start_id_);
        }
        if (js_call_python_id_ != 0) {
            event_bus->unsubscribe(js_call_python_id_);
        }
        CFW_LOG_DEBUG("ScriptSystem: Unsubscribed from events");
    }

    // 主动关闭 Python 解释器，避免在析构时阻塞
    python_api_->shutdown();
}

}  // namespace Corona::Systems
