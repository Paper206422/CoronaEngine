#pragma once

#include <corona/events/network_system_events.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/kernel/system/system_base.h>

#include <cstdint>
#include <memory>
#include <string>

namespace Corona::Systems {

/**
 * @brief 网络系统 (Network System) —— Omniverse Nucleus (USD) 联合开发骨架
 *
 * 为多人协作（Nucleus live layer 上的 USD 实时同步）铺底。本次只交付
 * 可编译、可注册、有清晰扩展点的骨架：
 * - 出站：本地 SharedDataHub 中变化的 Transform → 推送到 Nucleus live layer；
 * - 入站：远端协作者的 Transform 变更 → 写回 SharedDataHub。
 *
 * 当前不链接真实 Omniverse Client Library，connect/push/pull 均为占位实现。
 *
 * 优先级 55：在 ScriptSystem(60) 之后、ImguiSystem(40) 之前。所有逻辑系统
 * （几何/物理/脚本）都更新完成、Transform 落定后，再做网络同步，避免推送到
 * 半完成的帧状态。
 */
class NetworkSystem : public Kernel::SystemBase {
   public:
    /// 与 Nucleus 服务器的连接状态
    enum class ConnectionState : uint8_t {
        Disconnected = 0,  ///< 未连接（默认）
        Connecting,        ///< 正在建立连接
        Connected,         ///< 已连接，可收发同步
        Error              ///< 连接出错
    };

    NetworkSystem();
    ~NetworkSystem() override;

    // ========================================
    // ISystem 接口实现
    // ========================================

    std::string_view get_name() const override {
        return "Network";
    }

    int get_priority() const override {
        return 55;  // 逻辑系统更新完后再做网络同步
    }

    bool initialize(Kernel::ISystemContext* ctx) override;
    void update() override;
    void shutdown() override;

    // ========================================
    // 协作连接接口（扩展点，当前为占位）
    // ========================================

    /**
     * @brief 连接到 Omniverse Nucleus 服务器
     * @param url Nucleus 服务器 URL（如 "omniverse://localhost/Projects/scene.usd"）
     * @return 发起连接成功返回 true（骨架阶段总是返回 false 表示未实现）
     *
     * 接入真实 SDK 后：建立 Omniverse Client 连接、打开/创建 live layer。
     */
    bool connect_to_nucleus(const std::string& url);

    /// 主动断开当前连接
    void disconnect();

    [[nodiscard]] ConnectionState connection_state() const;

   private:
    // ========================================
    // 同步扩展点（当前为占位实现）
    // ========================================

    /// 出站：扫描 SharedDataHub 中变化的 Transform，推送到 Nucleus live layer。
    /// 使用 Impl 内维护的 handle → last_synced_transform 做差异比对
    /// （Storage<T> 本身无版本号/脏标记）。
    void push_local_changes();

    /// 入站：从 Nucleus live layer 拉取远端变更，发布 RemoteTransformReceivedEvent
    /// 并写回 SharedDataHub。
    void pull_remote_changes();

    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace Corona::Systems
