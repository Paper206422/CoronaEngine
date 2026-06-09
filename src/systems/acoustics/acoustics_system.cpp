#include <corona/events/acoustics_system_events.h>
#include <corona/kernel/core/i_logger.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/resource/resource_manager.h>
#include <corona/resource/types/audio.h>
#include <corona/systems/acoustics/acoustics_system.h>

#include <SDL3/SDL.h>

namespace Corona::Systems {

bool AcousticsSystem::initialize(Kernel::ISystemContext* ctx) {
    CFW_LOG_NOTICE("AcousticsSystem: Initializing...");

    // --- SDL3 音频初始化 ---
    if (!SDL_InitSubSystem(SDL_INIT_AUDIO)) {
        CFW_LOG_ERROR("AcousticsSystem: SDL_InitSubSystem(SDL_INIT_AUDIO) failed: {}", SDL_GetError());
        return false;
    }

    device_id_ = SDL_OpenAudioDevice(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, nullptr);
    if (device_id_ == 0) {
        CFW_LOG_ERROR("AcousticsSystem: SDL_OpenAudioDevice failed: {}", SDL_GetError());
        SDL_QuitSubSystem(SDL_INIT_AUDIO);
        return false;
    }

    CFW_LOG_NOTICE("AcousticsSystem: SDL3 audio device opened successfully");

    // --- 订阅播放事件 ---
    if (auto* event_bus = ctx->event_bus()) {
        event_bus->subscribe<Events::PlayAudioEvent>(
            [this](const Events::PlayAudioEvent& ev) {
                std::lock_guard lock(cmd_mutex_);
                pending_plays_.push_back(ev);
            });
        event_bus->subscribe<Events::StopAudioEvent>(
            [this](const Events::StopAudioEvent& ev) {
                std::lock_guard lock(cmd_mutex_);
                pending_stops_.push_back(ev);
            });
        CFW_LOG_NOTICE("AcousticsSystem: subscribed to PlayAudioEvent / StopAudioEvent");
    } else {
        CFW_LOG_WARNING("AcousticsSystem: event_bus not available, audio playback commands disabled");
    }

    return true;
}

void AcousticsSystem::process_play_request(std::uint64_t resource_id, bool loop) {
    // 如果已在播放，先停掉旧实例
    process_stop_request(resource_id);

    // 从资源管理器取 Audio
    auto handle = Resource::ResourceManager::get_instance().acquire_read<Resource::IResource>(resource_id);
    if (!handle) {
        CFW_LOG_ERROR("[AcousticsSystem] play: resource {} not found or not ready", resource_id);
        return;
    }
    const auto* audio = dynamic_cast<const Resource::Audio*>(&(*handle));
    if (!audio) {
        CFW_LOG_ERROR("[AcousticsSystem] play: resource {} is not an Audio resource", resource_id);
        return;
    }

    const auto& meta = audio->metadata();
    const auto& pcm = audio->samples();
    if (pcm.empty()) {
        CFW_LOG_WARNING("[AcousticsSystem] play: resource {} has no PCM data", resource_id);
        return;
    }

    // 创建匹配 PCM 实际格式的 SDL AudioStream
    SDL_AudioSpec src_spec{};
    src_spec.format = SDL_AUDIO_F32LE;
    src_spec.channels = meta.channels;
    src_spec.freq = meta.sample_rate;

    SDL_AudioStream* stream = SDL_CreateAudioStream(&src_spec, nullptr);
    if (!stream) {
        CFW_LOG_ERROR("[AcousticsSystem] play: SDL_CreateAudioStream failed: {}", SDL_GetError());
        return;
    }
    if (!SDL_BindAudioStream(device_id_, stream)) {
        CFW_LOG_ERROR("[AcousticsSystem] play: SDL_BindAudioStream failed: {}", SDL_GetError());
        SDL_DestroyAudioStream(stream);
        return;
    }

    ActivePlayback ap;
    ap.resource_id = resource_id;
    ap.pcm = pcm;
    ap.loop = loop;
    ap.stream = stream;

    const int total_bytes = static_cast<int>(ap.pcm.size() * sizeof(float));
    SDL_PutAudioStreamData(ap.stream, ap.pcm.data(), total_bytes);

    std::lock_guard lock(playback_mutex_);
    active_playbacks_.push_back(std::move(ap));

    CFW_LOG_INFO("[AcousticsSystem] play started: rid={} {}Hz {}ch loop={}", resource_id, meta.sample_rate, meta.channels, loop);
}

void AcousticsSystem::process_stop_request(std::uint64_t resource_id) {
    std::lock_guard lock(playback_mutex_);
    for (auto it = active_playbacks_.begin(); it != active_playbacks_.end(); ) {
        if (it->resource_id == resource_id) {
            if (it->stream) {
                SDL_UnbindAudioStream(it->stream);
                SDL_DestroyAudioStream(it->stream);
            }
            it = active_playbacks_.erase(it);
        } else {
            ++it;
        }
    }
}

void AcousticsSystem::update() {
    // --- 消费命令队列 ---
    {
        std::lock_guard lock(cmd_mutex_);
        for (const auto& cmd : pending_plays_) {
            process_play_request(cmd.resource_id, cmd.loop);
        }
        pending_plays_.clear();
        for (const auto& cmd : pending_stops_) {
            process_stop_request(cmd.resource_id);
        }
        pending_stops_.clear();
    }

    // --- 监控各音频流：数据已一次性灌入，这里只处理"播完"和"循环重灌" ---
    {
        std::lock_guard lock(playback_mutex_);

        auto it = active_playbacks_.begin();
        while (it != active_playbacks_.end()) {
            auto& ap = *it;
            if (!ap.stream) {
                ++it;
                continue;
            }

            // SDL 队列里还有未播完的数据 → 继续等
            const int queued_bytes = SDL_GetAudioStreamQueued(ap.stream);
            if (queued_bytes > 0) {
                ++it;
                continue;
            }

            // 队列已排空：循环则重新灌入，否则结束
            if (ap.loop) {
                const int total_bytes = static_cast<int>(ap.pcm.size() * sizeof(float));
                SDL_PutAudioStreamData(ap.stream, ap.pcm.data(), total_bytes);
                ++it;
            } else {
                CFW_LOG_INFO("[AcousticsSystem] playback finished: rid={}", ap.resource_id);
                SDL_UnbindAudioStream(ap.stream);
                SDL_DestroyAudioStream(ap.stream);
                it = active_playbacks_.erase(it);
            }
        }
    }
}

void AcousticsSystem::shutdown() {
    CFW_LOG_NOTICE("AcousticsSystem: Shutting down...");

    {
        std::lock_guard lock(playback_mutex_);
        for (auto& ap : active_playbacks_) {
            if (ap.stream) {
                SDL_UnbindAudioStream(ap.stream);
                SDL_DestroyAudioStream(ap.stream);
                ap.stream = nullptr;
            }
        }
        active_playbacks_.clear();
    }

    if (device_id_ != 0) {
        SDL_CloseAudioDevice(device_id_);
        device_id_ = 0;
    }
    SDL_QuitSubSystem(SDL_INIT_AUDIO);

    CFW_LOG_NOTICE("AcousticsSystem: Shutdown complete");
}

}  // namespace Corona::Systems
