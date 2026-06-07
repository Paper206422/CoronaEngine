#pragma once

#include <corona/events/network_system_events.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/kernel/system/system_base.h>

#include <corona/systems/network/protocol.h>
#include <corona/systems/network/discovery.h>
#include <corona/systems/network/peer_manager.h>
#include <corona/systems/network/sync_engine.h>

#include <cstdint>
#include <memory>
#include <string>

namespace Corona::Systems {

/**
 * @brief 网络系统 — 基于 ENet 可靠 UDP 的局域网多人协同编辑。
 *
 * 每个实例既是服务端也是客户端（full-mesh）。
 * 采用 Last-Write-Wins (LWW) 冲突解决策略。
 *
 * 架构：
 *   Discovery   — LAN UDP 广播发现
 *   PeerManager — ENet host + full-mesh peer 管理
 *   SyncEngine  — SharedDataHub 脏轮询 + LWW 合并
 *
 * 优先级 55：在 ScriptSystem(60) 之后、ImguiSystem(40) 之前。
 */
class NetworkSystem : public Kernel::SystemBase {
public:
    /// 网络会话状态
    enum class SessionState : uint8_t {
        Idle = 0,     ///< 未启动
        Starting,     ///< 正在启动
        Active,       ///< 已启动，可收发同步
        Error         ///< 启动失败
    };

    NetworkSystem();
    ~NetworkSystem() override;

    // ========================================
    // ISystem 接口
    // ========================================

    std::string_view get_name() const override { return "Network"; }
    int get_priority() const override { return 55; }

    bool initialize(Kernel::ISystemContext* ctx) override;
    void update() override;
    void shutdown() override;

    // ========================================
    // 公共接口
    // ========================================

    /**
     * @brief 启动局域网协同会话（广播发现 + ENet host）。
     * @param instance_name 本实例名（用于 UI 显示，最多 31 字符）
     * @param project_id    项目标识 hash（仅同项目 peer 互联）
     * @param port          UDP 端口（默认 kDefaultPort = 27960）
     * @return true 成功
     */
    bool start_session(const std::string& instance_name, uint64_t project_id,
                       uint16_t port = Network::kDefaultPort);

    /// 停止会话，断开所有 peer，关闭 host。
    void stop_session();

    /// 当前会话状态。
    [[nodiscard]] SessionState session_state() const;

    /// 已连接的 peer 数量。
    [[nodiscard]] size_t peer_count() const;

private:
    // ========================================
    // 内部回调
    // ========================================

    void on_peer_discovered(const std::string& ip, const std::string& name, uint64_t project_id);
    void on_peer_connected(const Network::PeerManager::PeerInfo& info);
    void on_peer_disconnected(const Network::PeerManager::PeerInfo& info);
    void on_data_received(const std::string& peer_id, const uint8_t* data, size_t len);

    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace Corona::Systems
