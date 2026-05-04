#pragma once

#include <CabbageHardware.h>

#include <cstdint>

namespace Corona::Events {
/**
 * @brief 显示系统内部事件（单线程使用 EventBus）
 */
struct DisplaySystemDemoEvent {
    int demo_value;
};

/**
 * @brief 引擎到显示系统的跨线程事件（使用 EventStream）
 */
struct EngineToDisplayDemoEvent {
    float delta_time;
};

/**
 * @brief 显示系统到引擎的跨线程事件（使用 EventStream）
 */
struct DisplayToEngineDemoEvent {
    float delta_time;
};

/**
 * @brief 显示表面变化事件（使用 EventBus）
 */
struct DisplaySurfaceChangedEvent {
    void* surface;
};

/**
 * @brief Optics layer frame ready (published by OpticsSystem, consumed by DisplaySystem)
 */
struct OpticsFrameReadyEvent {
    void* surface = nullptr;
    std::uintptr_t image_handle = 0;
    uint64_t frame_index = 0;
    uint32_t width = 0;
    uint32_t height = 0;
};

/**
 * @brief UI layer frame ready (published by VulkanBackend, consumed by DisplaySystem)
 */
struct UIFrameReadyEvent {
    void* surface = nullptr;
    std::uintptr_t image_handle = 0;
    uint64_t frame_index = 0;
    uint32_t width = 0;
    uint32_t height = 0;
};

}  // namespace Corona::Events
