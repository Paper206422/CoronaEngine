#pragma once

#include <corona/shared_data_hub.h>

#include <cstddef>
#include <functional>
#include <string>
#include <string_view>

namespace Corona::Systems::Vision {

enum class VisionPipelineSource {
    EngineBuilt,
    ExternalFile,
    ExternalLive,
};

struct VisionPipelineKey {
    std::string scene_path;
    CameraVisionRenderMode mode{CameraVisionRenderMode::PathTracing};
    VisionPipelineSource source{VisionPipelineSource::EngineBuilt};

    friend bool operator==(const VisionPipelineKey& lhs,
                           const VisionPipelineKey& rhs) noexcept {
        return lhs.scene_path == rhs.scene_path && lhs.mode == rhs.mode &&
               lhs.source == rhs.source;
    }
};

struct VisionPipelineKeyHash {
    [[nodiscard]] std::size_t operator()(const VisionPipelineKey& key) const noexcept {
        std::size_t seed = std::hash<std::string>{}(key.scene_path);
        auto mix = [&seed](std::size_t value) noexcept {
            seed ^= value + 0x9e3779b97f4a7c15ull + (seed << 6u) + (seed >> 2u);
        };
        mix(std::hash<int>{}(static_cast<int>(key.mode)));
        mix(std::hash<int>{}(static_cast<int>(key.source)));
        return seed;
    }
};

[[nodiscard]] constexpr std::string_view vision_pipeline_source_name(
    VisionPipelineSource source) noexcept {
    switch (source) {
        case VisionPipelineSource::EngineBuilt:
            return "engine_built";
        case VisionPipelineSource::ExternalFile:
            return "external_file";
        case VisionPipelineSource::ExternalLive:
            return "external_live";
    }
    return "engine_built";
}

}  // namespace Corona::Systems::Vision
