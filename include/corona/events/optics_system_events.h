#pragma once

#include <corona/kernel/utils/storage.h>

#include <array>
#include <future>
#include <memory>
#include <string>

namespace Corona {
class Model;
}

namespace Corona::Events {

/**
 * @brief 光学系统内部事件（单线程使用 EventBus）
 */
struct OpticsSystemDemoEvent {
    int demo_value;
};

/**
 * @brief 引擎到光学系统的跨线程事件（使用 EventStream）
 */
struct EngineToOpticsDemoEvent {
    float delta_time;
};

/**
 * @brief 光学系统到引擎的跨线程事件（使用 EventStream）
 */
struct OpticsToEngineDemoEvent {
    float delta_time;
};

/**
 * @brief Screenshot request (published by Camera/Viewport API, consumed by OpticsSystem)
 *
 * Uses camera_handle as the matching key so that offscreen cameras (without a
 * display surface) can still take screenshots.
 */
struct ScreenshotRequestEvent {
    std::uintptr_t camera_handle = 0;
    std::string file_path;
    std::shared_ptr<std::promise<bool>> completion_promise;
};

/**
 * @brief Request to switch the optics render backend (published by script API,
 *        consumed by OpticsSystem).
 *
 * backend: 0 = Native (Vulkan rasterization), 1 = Vision (CUDA path tracing).
 * The switch is only meaningful when the engine is compiled with
 * CORONA_ENABLE_VISION; otherwise OpticsSystem keeps the Native backend.
 */
struct RenderBackendSwitchEvent {
    int backend = 0;
};

/**
 * @brief Actor picking request (published by Camera API, consumed by OpticsSystem)
 */
struct ActorPickRequestEvent {
    std::uintptr_t camera_handle = 0;
    int x = 0;
    int y = 0;
    std::shared_ptr<std::promise<std::array<std::uintptr_t, 2>>> completion_promise;
};

}  // namespace Corona::Events
