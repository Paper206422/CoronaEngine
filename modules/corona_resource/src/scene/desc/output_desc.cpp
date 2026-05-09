#include "corona/scene/desc/output_desc.h"

namespace Corona::Resource::Scene {

// SpectrumDesc 实现
SpectrumDesc::SpectrumDesc() : NodeDesc("Spectrum") {}

SpectrumDesc::SpectrumDesc(std::string name) : NodeDesc("Spectrum", std::move(name)) {}

void SpectrumDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);
    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        sub_type = type_item->get<std::string>();
    } else {
        sub_type = "srgb";  // 默认值
    }
    auto param_item = params.find("param");
    if (param_item != params.end() && param_item->is_object()) {
        update_parameters(*param_item);
    }
}

// OutputDesc 实现
OutputDesc::OutputDesc() : NodeDesc("Output") {}

OutputDesc::OutputDesc(std::string name) : NodeDesc("Output", std::move(name)) {}

void OutputDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);

    if (params.is_null()) {
        return;
    }

    auto const& fn_item = params.find("fn");
    if (fn_item != params.end() && fn_item->is_string()) {
        fn = fn_item->get<std::string>();
    } else {
        fn = "output.png";  // 默认值
    }

    auto const& spp_item = params.find("spp");
    if (spp_item != params.end() && spp_item->is_number_unsigned()) {
        spp = spp_item->get<std::uint32_t>();
    }

    auto const& save_exit_item = params.find("save_exit");
    if (save_exit_item != params.end()) {
        if (save_exit_item->is_boolean()) {
            save_exit = save_exit_item->get<bool>();
        } else if (save_exit_item->is_number_unsigned()) {
            save_exit = save_exit_item->get<std::uint32_t>() != 0;
        }
    }

    auto const& denoise_item = params.find("denoise");
    if (denoise_item != params.end() && denoise_item->is_boolean()) {
        denoise = denoise_item->get<bool>();
    }
}

// RenderSettingDesc 实现
RenderSettingDesc::RenderSettingDesc() : NodeDesc("RenderSetting") {}

RenderSettingDesc::RenderSettingDesc(std::string name) : NodeDesc("RenderSetting", std::move(name)) {}

void RenderSettingDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);

    auto const& polymorphic_mode_item = params.find("polymorphic_mode");
    if (polymorphic_mode_item != params.end() && polymorphic_mode_item->is_number_integer()) {
        int mode = polymorphic_mode_item->get<int>();
        if (mode == 0) {
            polymorphic_mode = PolymorphicMode::EInstance;
        } else if (mode == 1) {
            polymorphic_mode = PolymorphicMode::ETopology;
        }
    } else {
        polymorphic_mode = PolymorphicMode::ETopology;  // 默认值
    }

    auto const& min_world_radius_item = params.find("min_world_radius");
    if (min_world_radius_item != params.end() && min_world_radius_item->is_number_float()) {
        min_world_radius = min_world_radius_item->get<float>();
    } else if (min_world_radius_item != params.end() && min_world_radius_item->is_number_integer()) {
        min_world_radius = static_cast<float>(min_world_radius_item->get<int>());
    } else {
        min_world_radius = 10.0f;  // 默认值
    }

    auto const& ray_offset_factor_item = params.find("ray_offset_factor");
    if (ray_offset_factor_item != params.end() && ray_offset_factor_item->is_number_float()) {
        ray_offset_factor = ray_offset_factor_item->get<float>();
    } else if (ray_offset_factor_item != params.end() && ray_offset_factor_item->is_number_integer()) {
        ray_offset_factor = static_cast<float>(ray_offset_factor_item->get<int>());
    } else {
        ray_offset_factor = 1.0f;  // 默认值
    }
}

}  // namespace Corona::Resource::Scene
