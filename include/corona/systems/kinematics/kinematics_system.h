#pragma once

#include <corona/events/kinematics_system_events.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/kernel/system/system_base.h>

#include <memory>

namespace Corona::Systems {

/**
 * @brief 运动学系统
 *
 * 负责管理和更新物体的运动学状态。
 * 运行在独立线程，以 60 FPS 更新运动学逻辑。
 */
class KinematicsSystem : public Kernel::SystemBase {
   public:
    KinematicsSystem() {
        set_target_fps(60);  // 动画系统运行在 60 FPS
    }

    ~KinematicsSystem() override = default;

    // ========================================
    // ISystem 接口实现
    // ========================================

    std::string_view get_name() const override {
        return "Animation";
    }

    int get_priority() const override {
        return 80;  // 高优先级，在渲染前更新
    }

    /**
     * @brief 初始化动画系统
     * @param ctx 系统上下文
     * @return 初始化成功返回 true
     */
    bool initialize(Kernel::ISystemContext* ctx) override;

    /**
     * @brief 每帧更新动画
     *
     * 在独立线程中调用，根据 delta_time() 更新动画状态
     */
    void update() override;

    /**
     * @brief 关闭动画系统
     *
     * 清理所有动画资源
     */
    void shutdown() override;

   private:
};

}  // namespace Corona::Systems
