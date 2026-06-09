#pragma once

#include <corona/events/acoustics_system_events.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/kernel/system/system_base.h>

#include <SDL3/SDL_audio.h>

#include <atomic>
#include <memory>
#include <mutex>
#include <vector>

namespace Corona::Systems {

/**
 * @brief 声学系统 (Acoustics System)
 *
 * 负责管理声音播放、混音和音频处理。
 * 运行在独立线程，以 60 FPS 处理声学逻辑。
 *
 * 当前实现：简单全局播放器（非空间音效）。
 * 使用 SDL3 AudioStream 自动混音，支持同时播放多个音频。
 * 每个活跃音频拥有独立的 SDL_AudioStream（绑定到共享设备），
 * PCM 格式按资源实际声道数/采样率构造 src_spec。
 */
class AcousticsSystem : public Kernel::SystemBase {
   public:
    AcousticsSystem() { set_target_fps(60); }
    ~AcousticsSystem() override = default;

    std::string_view get_name() const override { return "Acoustics"; }
    int get_priority() const override { return 70; }

    bool initialize(Kernel::ISystemContext* ctx) override;
    void update() override;
    void shutdown() override;

   private:
    /// 单个活跃播放状态
    struct ActivePlayback {
        std::uint64_t resource_id;
        std::vector<float> pcm;       // 已解码的完整 PCM（交错 float32）
        bool loop{false};
        SDL_AudioStream* stream{nullptr};
    };

    /// 处理播放命令（在 update 线程中调用）
    void process_play_request(std::uint64_t resource_id, bool loop);
    /// 处理停止命令
    void process_stop_request(std::uint64_t resource_id);

    // SDL3 音频后端
    SDL_AudioDeviceID device_id_{0};

    // 播放状态
    std::mutex playback_mutex_;
    std::vector<ActivePlayback> active_playbacks_;

    // 命令队列（由 API/主线程写入，update 线程消费）
    std::mutex cmd_mutex_;
    std::vector<Events::PlayAudioEvent> pending_plays_;
    std::vector<Events::StopAudioEvent> pending_stops_;
};

}  // namespace Corona::Systems
