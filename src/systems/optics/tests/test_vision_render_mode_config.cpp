#include "vision/vision_render_mode_config.h"

#include "base/import/json_util.h"
#include "base/import/project_desc.h"

#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <optional>
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

std::optional<std::filesystem::path> find_external_ssat_scene() {
    const std::filesystem::path relative =
        std::filesystem::path{"test_vision"} / "render_scene" / "cbox-lf" /
        "vision_scene.json";
    const std::filesystem::path fixed =
        std::filesystem::path{"D:/Documents/GitHub/CoronaExample"} / relative;
    if (std::filesystem::exists(fixed)) {
        return fixed;
    }

    for (auto cursor = std::filesystem::current_path(); !cursor.empty();) {
        const auto candidate = cursor.parent_path() / "CoronaExample" / relative;
        if (std::filesystem::exists(candidate)) {
            return candidate;
        }
        const auto parent = cursor.parent_path();
        if (parent == cursor) {
            break;
        }
        cursor = parent;
    }
    return std::nullopt;
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

void path_tracing_rewrites_ssat_scene_to_normal_framebuffer() {
    auto data = make_base_scene();
    Corona::Systems::Vision::configure_vision_scene_for_mode(
        data, CameraVisionRenderMode::PathTracing);

    expect(!data["output"]["denoise"].get<bool>(),
           "path_tracing should set output.denoise=false");
    expect(data["pipeline"]["param"]["frame_buffer"]["type"].get<std::string>() ==
               "normal",
           "path_tracing should use normal framebuffer");
    expect(data["render"]["integrator"]["param"]["denoiser"]["type"].get<std::string>() ==
               "svgf",
           "path_tracing should not keep SSAT denoiser descriptor");
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

void cbox_lf_scene_supports_pt_and_ssat_mode_import() {
    const auto scene_path = find_external_ssat_scene();
    if (!scene_path) {
        std::cout << "SKIP: cbox-lf external Vision scene sample not found\n";
        return;
    }

    auto pt_data = vision::create_json_from_file(*scene_path);
    Corona::Systems::Vision::configure_vision_scene_for_mode(
        pt_data, CameraVisionRenderMode::PathTracing);
    vision::ProjectDesc pt_desc;
    pt_desc.scene_path = scene_path->parent_path();
    pt_desc.init(pt_data);

    expect(!pt_desc.output_desc.denoise,
           "PT import from cbox-lf should disable realtime denoise");
    expect(pt_desc.pipeline_desc.frame_buffer_desc.sub_type == "normal",
           "PT import from cbox-lf should use a normal framebuffer");
    expect(pt_desc.renderer_desc.integrator_desc.denoiser_desc.sub_type == "svgf",
           "PT import from cbox-lf should not keep the SSAT denoiser descriptor");

    auto ssat_data = vision::create_json_from_file(*scene_path);
    Corona::Systems::Vision::configure_vision_scene_for_mode(
        ssat_data, CameraVisionRenderMode::SSAT);
    vision::ProjectDesc ssat_desc;
    ssat_desc.scene_path = scene_path->parent_path();
    ssat_desc.init(ssat_data);

    expect(ssat_desc.output_desc.denoise,
           "SSAT import from cbox-lf should enable realtime denoise");
    expect(ssat_desc.pipeline_desc.frame_buffer_desc.sub_type == "lightfield",
           "SSAT import should use a lightfield framebuffer");
    expect(ssat_desc.renderer_desc.integrator_desc.denoiser_desc.sub_type == "SSAT",
           "SSAT import should use the SSAT integrator denoiser");
    expect(ssat_data["render"]["integrator"]["param"]["denoiser"]["param"]
                    ["angular_samples"]
                        .get<int>() == 7,
           "SSAT import should preserve cbox-lf angular_samples parameter");
}

}  // namespace

int main() {
    mode_names_and_denoise_flags_are_stable();
    path_tracing_rewrites_ssat_scene_to_normal_framebuffer();
    svgf_rewrites_ssat_scene_to_normal_svgf();
    ssat_rewrites_svgf_scene_to_lightfield_ssat();
    missing_blocks_are_created_for_requested_mode();
    cbox_lf_scene_supports_pt_and_ssat_mode_import();
    return 0;
}
