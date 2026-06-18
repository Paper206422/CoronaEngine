#pragma once

#include <corona/shared_data_hub.h>

#include "base/import/parameter_set.h"

#include <string_view>

namespace Corona::Systems::Vision {

[[nodiscard]] std::string_view vision_render_mode_name(
    CameraVisionRenderMode mode) noexcept;

[[nodiscard]] bool vision_render_mode_uses_denoise(
    CameraVisionRenderMode mode) noexcept;

void configure_vision_scene_for_mode(::vision::DataWrap& data,
                                     CameraVisionRenderMode mode);

}  // namespace Corona::Systems::Vision
