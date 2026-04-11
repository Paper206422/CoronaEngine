#pragma once

#include <corona/kernel/utils/storage.h>

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
 */
struct ScreenshotRequestEvent
{
    void* surface = nullptr;
    std::string file_path;
    std::shared_ptr<std::promise<bool>> completion_promise;
};

}  // namespace Corona::Events
