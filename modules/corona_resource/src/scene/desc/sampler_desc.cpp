#include "corona/scene/desc/sampler_desc.h"

namespace Corona::Resource::Scene {

// SamplerDesc 实现
SamplerDesc::SamplerDesc() : NodeDesc("Sampler") {}

SamplerDesc::SamplerDesc(std::string name) : NodeDesc("Sampler", std::move(name)) {}

void SamplerDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);
    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        sub_type = type_item->get<std::string>();
    } else {
        sub_type = "independent";  // 默认值
    }
    auto param_item = params.find("param");
    if (param_item != params.end() && param_item->is_object()) {
        update_parameters(*param_item);
    }
}

// LightSamplerDesc 实现
LightSamplerDesc::LightSamplerDesc() : NodeDesc("LightSampler") {}

LightSamplerDesc::LightSamplerDesc(std::string name) : NodeDesc("LightSampler", std::move(name)) {}

void LightSamplerDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);
    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        sub_type = type_item->get<std::string>();
    } else {
        sub_type = "uniform";  // 默认值
    }
    auto param_item = params.find("param");
    if (param_item != params.end() && param_item->is_object()) {
        update_parameters(*param_item);

        // 初始化灯光列表
        auto lights_item = param_item->find("lights");
        if (lights_item != param_item->end() && lights_item->is_array()) {
            for (const auto& light_data : *lights_item) {
                LightDesc light_desc;
                light_desc.init(light_data);
                light_descs.push_back(light_desc);
            }
        }
    }
}

// WarperDesc 实现
WarperDesc::WarperDesc() : NodeDesc("Warper") {}

WarperDesc::WarperDesc(std::string name) : NodeDesc("Warper", std::move(name)) {}

void WarperDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);
    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        sub_type = type_item->get<std::string>();
    } else {
        sub_type = "alias_table";  // 默认值
    }
}

}  // namespace Corona::Resource::Scene
