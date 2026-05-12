#pragma once

#include <cstdint>

namespace Corona::Events {

/**
 * @brief 场景系统：actor 进入某相机视锥
 */
struct ActorEnteredFrustumEvent {
    std::uintptr_t scene{};
    std::uintptr_t actor{};
    std::uintptr_t camera{};
};

/**
 * @brief 场景系统：actor 离开某相机视锥
 */
struct ActorLeftFrustumEvent {
    std::uintptr_t scene{};
    std::uintptr_t actor{};
    std::uintptr_t camera{};
};

/**
 * @brief 触发 LRU 卸载请求（M3 起接入 ActorCache）
 */
struct ActorEvictRequestedEvent {
    std::uintptr_t scene{};
    std::uintptr_t actor{};
};

/**
 * @brief 触发 LRU 唤醒请求（M3 起接入 ActorCache）
 */
struct ActorRestoreRequestedEvent {
    std::uintptr_t scene{};
    std::uintptr_t actor{};
};

/**
 * @brief 触发 Actor 的距离预加载请求事件
 */
struct ActorLoadRequestedEvent {
    std::uintptr_t scene{};
    std::uintptr_t actor{};
};

/**
 * @brief Actor 资源加载完成事件（由资源系统发布）
 */
struct ActorLoadCompletedEvent {
    std::uintptr_t scene{};
    std::uintptr_t actor{};
};

/**
 * @brief 触发 Actor 的距离卸载请求事件
 */
struct ActorUnloadRequestedEvent {
    std::uintptr_t scene{};
    std::uintptr_t actor{};
};

/**
 * @brief Actor 资源卸载完成事件（由资源系统发布）
 */
struct ActorUnloadCompletedEvent {
    std::uintptr_t scene{};
    std::uintptr_t actor{};
};
}  // namespace Corona::Events
