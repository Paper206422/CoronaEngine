#pragma once

#include <cstdint>
#include <string>

namespace Corona::Events {

// ============================================================================
// NetworkSystem 事件（为 Omniverse Nucleus (USD) 协作铺底）
//
// 当前为占位定义：NetworkSystem 仅交付骨架，未接入真实 Omniverse Client SDK。
// 这些事件描述了未来的入站/出站同步契约，便于其它系统提前订阅。
// ============================================================================

/**
 * @brief 已连接到 Nucleus 服务器（出站方向就绪）
 */
struct NucleusConnectedEvent {
    std::string url;  ///< 连接的 Nucleus 服务器 URL（如 omniverse://server/path）
};

/**
 * @brief 与 Nucleus 服务器断开连接
 */
struct NucleusDisconnectedEvent {
    std::string url;     ///< 断开的服务器 URL
    std::string reason;  ///< 断开原因（主动关闭 / 网络错误 / 服务端断开）
};

/**
 * @brief 收到远端 Transform 变更（入站方向）
 *
 * NetworkSystem 从 Nucleus live layer 拉取到远端协作者的变换更新后，
 * 发布此事件；由 GeometrySystem / 脚本层消费并写回 SharedDataHub。
 * position / rotation(欧拉角) / scale 均为世界空间，单位与 ModelTransform 一致。
 */
struct RemoteTransformReceivedEvent {
    std::uintptr_t actor_handle = 0;
    float position[3] = {0.0f, 0.0f, 0.0f};
    float rotation[3] = {0.0f, 0.0f, 0.0f};  ///< 欧拉角（与 ModelTransform.euler_rotation 对齐）
    float scale[3]    = {1.0f, 1.0f, 1.0f};
};

}  // namespace Corona::Events
