#pragma once

#include <corona/events/mechanics_system_events.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/kernel/system/system_base.h>

#include <chrono>
#include <memory>

namespace Corona::Systems {

/**
 * @brief 力学系统 (Mechanics System)
 *
 * 负责物理模拟、刚体动力学、碰撞检测和响应。
 * 运行在独立线程，以 60 FPS 更新物理状态。
 */
class MechanicsSystem : public Kernel::SystemBase {
   public:
    MechanicsSystem() {
        set_target_fps(60);  // 力学系统运行在 60 FPS
    }

    ~MechanicsSystem() override = default;

    // ========================================
    // ISystem 接口实现
    // ========================================

    std::string_view get_name() const override {
        return "Mechanics";
    }

    int get_priority() const override {
        return 75;  // 中高优先级，在几何系统之后
    }

    /**
     * @brief 初始化力学系统
     * @param ctx 系统上下文
     * @return 初始化成功返回 true
     */
    bool initialize(Kernel::ISystemContext* ctx) override;

    /**
     * @brief 每帧更新物理
     *
     * 在独立线程中调用，执行物理模拟
     */
    void update() override;

    /**
     * @brief 关闭力学系统
     *
     * 清理所有物理资源
     */
    void stop() override;

    void shutdown() override;

   private:
    // 力学系统私有成员
    void update_physics();

    Kernel::ISystemContext* m_ctx = nullptr;
    float m_time_accumulator{0.0f};
    std::chrono::steady_clock::time_point m_last_update_time{};
    bool m_first_update{true};
};

}  // namespace Corona::Systems
