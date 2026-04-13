#pragma once

namespace Corona::Events {

/**
 * @brief UI系统内部事件（单线程使用 EventBus）
 */
struct ImguiSystemDemoEvent {
    int demo_value;
};

/**
 * @brief 引擎到UI系统的跨线程事件（使用 EventStream）
 */
struct EngineToImguiDemoEvent {
    float delta_time;
};

/**
 * @brief UI系统到引擎的跨线程事件（使用 EventStream）
 */
struct ImguiToEngineDemoEvent {
    float delta_time;
};

/**
 * @brief UI系统到引擎的跨线程事件（使用 EventStream）
 */
struct ScriptFinishStartEvent {
    float delta_time;
};

}  // namespace Corona::Events