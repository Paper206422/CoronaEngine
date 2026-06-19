#include "vision_render_mode_config.h"

#include <string>

namespace Corona::Systems::Vision {

std::string_view vision_render_mode_name(CameraVisionRenderMode mode) noexcept {
    switch (mode) {
        case CameraVisionRenderMode::SVGF:
            return "svgf";
        case CameraVisionRenderMode::SSAT:
            return "ssat";
        case CameraVisionRenderMode::PathTracing:
        default:
            return "path_tracing";
    }
}

bool vision_render_mode_uses_denoise(CameraVisionRenderMode mode) noexcept {
    return mode != CameraVisionRenderMode::PathTracing;
}

namespace {

::vision::DataWrap& ensure_vision_json_object(::vision::DataWrap& parent,
                                              std::string_view key) {
    const auto name = std::string(key);
    if (!parent.contains(name) || !parent[name].is_object()) {
        parent[name] = ::vision::DataWrap::object();
    }
    return parent[name];
}

}  // namespace

void configure_vision_scene_for_mode(::vision::DataWrap& data,
                                     CameraVisionRenderMode mode) {
    auto& output = ensure_vision_json_object(data, "output");
    output["denoise"] = vision_render_mode_uses_denoise(mode);

    auto& render = ensure_vision_json_object(data, "render");
    auto& integrator = ensure_vision_json_object(render, "integrator");
    auto& integrator_param = ensure_vision_json_object(integrator, "param");
    auto& denoiser = ensure_vision_json_object(integrator_param, "denoiser");
    denoiser["type"] = mode == CameraVisionRenderMode::SSAT ? "SSAT" : "svgf";
    ensure_vision_json_object(denoiser, "param");

    auto& pipeline = ensure_vision_json_object(data, "pipeline");
    auto& pipeline_param = ensure_vision_json_object(pipeline, "param");
    auto& frame_buffer = ensure_vision_json_object(pipeline_param, "frame_buffer");
    frame_buffer["type"] =
        mode == CameraVisionRenderMode::SSAT ? "lightfield" : "normal";
    ensure_vision_json_object(frame_buffer, "param");
}

}  // namespace Corona::Systems::Vision
