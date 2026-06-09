#pragma once

#include <cstdint>

namespace Corona::Events {

/**
 * @brief 声学系统内部事件（单线程使用 EventBus）
 */
struct AcousticsSystemDemoEvent {
    int demo_value;
};

/**
 * @brief 引擎到声学系统的跨线程事件（使用 EventStream）
 */
struct EngineToAcousticsDemoEvent {
    float delta_time;
};

/**
 * @brief 声学系统到引擎的跨线程事件（使用 EventStream）
 */
struct AcousticsToEngineDemoEvent {
    float delta_time;
};

// ============================================================================
// 音频播放事件（单线程 EventBus）
// ============================================================================

/// 请求播放音频资源
struct PlayAudioEvent {
    std::uint64_t resource_id{0};
    bool loop{false};
};

/// 请求停止音频资源
struct StopAudioEvent {
    std::uint64_t resource_id{0};
};

}  // namespace Corona::Events
