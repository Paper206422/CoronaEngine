#pragma once

#include <cstdint>
#include <string>

namespace Corona::Events {

// ============================================================================
// NetworkSystem 事件 — 多人协同编辑
// ============================================================================

/**
 * @brief 远端 peer 已连接。
 */
struct PeerConnectedEvent {
    std::string peer_id;    ///< "ip:port" 格式的唯一标识
    std::string peer_name;  ///< 实例名（用于 UI 显示）
};

/**
 * @brief 远端 peer 已断开。
 */
struct PeerDisconnectedEvent {
    std::string peer_id;
};

/**
 * @brief 收到远端数据同步（供 UI / 脚本层消费的通知）。
 */
struct RemoteSyncReceivedEvent {
    std::string peer_id;
};

/**
 * @brief NetworkSystem 成为主机（当前是 full-mesh，无真实主机概念；
 *        但初始的 LAN 房间第一个实例可视为"局域网主机"）。
 */
struct NetworkHostStartedEvent {
    uint16_t port;
};

/**
 * @brief NetworkSystem 已停止。
 */
struct NetworkHostStoppedEvent {};

}  // namespace Corona::Events
