#include "vision/vision_render_mode_config.h"

#include <cstdlib>
#include <iostream>
#include <string_view>

namespace {

using Corona::CameraVisionRenderMode;

[[noreturn]] void fail(std::string_view message) {
    std::cerr << "FAIL: " << message << '\n';
    std::exit(1);
}

void expect(bool condition, std::string_view message) {
    if (!condition) {
        fail(message);
    }
}

vision::DataWrap make_base_scene() {
    return vision::DataWrap{
        {"scene",
         {{"camera", vision::DataWrap::object()},
          {"materials", vision::DataWrap::array()},
          {"mediums", vision::DataWrap::object()},
          {"shapes", vision::DataWrap::array()},
          {"lights", vision::DataWrap::array()}}},
        {"render",
         {{"integrator",
           {{"type", "pt"},
            {"param",
             {{"denoiser",
               {{"type", "SSAT"},
                {"param", {{"ssat_radius", 7}, {"history", 4}}}}}}}}}}},
        {"pipeline",
         {{"type", "fixed"},
          {"param",
           {{"frame_buffer",
             {{"type", "lightfield"},
              {"param", {{"resolution", {64, 32}}, {"view_count", 8}}}}}}}}},
        {"output", {{"denoise", true}, {"spp", 1}}},
    };
}

void path_tracing_only_disables_output_denoise() {
    auto data = make_base_scene();
    Corona::Systems::Vision::configure_vision_scene_for_mode(
        data, CameraVisionRenderMode::PathTracing);

    expect(!data["output"]["denoise"].get<bool>(),
           "path_tracing should set output.denoise=false");
    expect(data["pipeline"]["param"]["frame_buffer"]["type"].get<std::string>() ==
               "lightfield",
           "path_tracing should not rewrite framebuffer type");
    expect(data["render"]["integrator"]["param"]["denoiser"]["type"].get<std::string>() ==
               "SSAT",
           "path_tracing should not rewrite denoiser type");
}

void svgf_rewrites_ssat_scene_to_normal_svgf() {
    auto data = make_base_scene();
    Corona::Systems::Vision::configure_vision_scene_for_mode(
        data, CameraVisionRenderMode::SVGF);

    expect(data["output"]["denoise"].get<bool>(),
           "svgf should set output.denoise=true");
    expect(data["pipeline"]["param"]["frame_buffer"]["type"].get<std::string>() ==
               "normal",
           "svgf should use normal framebuffer");
    expect(data["render"]["integrator"]["param"]["denoiser"]["type"].get<std::string>() ==
               "svgf",
           "svgf should use svgf integrator denoiser");
    expect(data["render"]["integrator"]["param"]["denoiser"]["param"]["ssat_radius"]
               .get<int>() == 7,
           "svgf compatibility path should preserve existing denoiser params");

}

void ssat_rewrites_svgf_scene_to_lightfield_ssat() {
    auto data = make_base_scene();
    data["pipeline"]["param"]["frame_buffer"]["type"] = "normal";
    data["render"]["integrator"]["param"]["denoiser"]["type"] = "svgf";
    data["output"]["denoise"] = false;

    Corona::Systems::Vision::configure_vision_scene_for_mode(
        data, CameraVisionRenderMode::SSAT);

    expect(data["output"]["denoise"].get<bool>(),
           "ssat should set output.denoise=true");
    expect(data["pipeline"]["param"]["frame_buffer"]["type"].get<std::string>() ==
               "lightfield",
           "ssat should use lightfield framebuffer");
    expect(data["render"]["integrator"]["param"]["denoiser"]["type"].get<std::string>() ==
               "SSAT",
           "ssat should use SSAT integrator denoiser");

}

void missing_blocks_are_created_for_requested_mode() {
    vision::DataWrap data = vision::DataWrap::object();
    Corona::Systems::Vision::configure_vision_scene_for_mode(
        data, CameraVisionRenderMode::SVGF);

    expect(data["output"]["denoise"].get<bool>(),
           "missing output block should be created with denoise=true");
    expect(data["pipeline"]["param"]["frame_buffer"]["type"].get<std::string>() ==
               "normal",
           "missing pipeline block should be created for svgf framebuffer");
    expect(data["render"]["integrator"]["param"]["denoiser"]["type"].get<std::string>() ==
               "svgf",
           "missing render block should be created for svgf denoiser");
}

void mode_names_and_denoise_flags_are_stable() {
    expect(Corona::Systems::Vision::vision_render_mode_name(
               CameraVisionRenderMode::PathTracing) == "path_tracing",
           "path_tracing mode name should be stable");
    expect(Corona::Systems::Vision::vision_render_mode_name(
               CameraVisionRenderMode::SVGF) == "svgf",
           "svgf mode name should be stable");
    expect(Corona::Systems::Vision::vision_render_mode_name(
               CameraVisionRenderMode::SSAT) == "ssat",
           "ssat mode name should be stable");
    expect(!Corona::Systems::Vision::vision_render_mode_uses_denoise(
               CameraVisionRenderMode::PathTracing),
           "path_tracing should disable denoise");
    expect(Corona::Systems::Vision::vision_render_mode_uses_denoise(
               CameraVisionRenderMode::SVGF),
           "svgf should enable denoise");
    expect(Corona::Systems::Vision::vision_render_mode_uses_denoise(
               CameraVisionRenderMode::SSAT),
           "ssat should enable denoise");
}

}  // namespace

int main() {
    mode_names_and_denoise_flags_are_stable();
    path_tracing_only_disables_output_denoise();
    svgf_rewrites_ssat_scene_to_normal_svgf();
    ssat_rewrites_svgf_scene_to_lightfield_ssat();
    missing_blocks_are_created_for_requested_mode();
    return 0;
}
