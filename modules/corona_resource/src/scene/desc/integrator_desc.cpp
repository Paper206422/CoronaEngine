#include "corona/scene/desc/integrator_desc.h"

namespace Corona::Resource::Scene {

// RadianceCacheDesc 实现
RadianceCacheDesc::RadianceCacheDesc() : NodeDesc("RadianceCache") {}

RadianceCacheDesc::RadianceCacheDesc(std::string name) : NodeDesc("RadianceCache", std::move(name)) {}

void RadianceCacheDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);
    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        sub_type = type_item->get<std::string>();
    } else {
        sub_type = "sharc";  // 默认值
    }
    auto param_item = params.find("param");
    if (param_item != params.end() && param_item->is_object()) {
        update_parameters(*param_item);
    }
}

// DenoiserDesc 实现
DenoiserDesc::DenoiserDesc() : NodeDesc("Denoiser") {}

DenoiserDesc::DenoiserDesc(std::string name) : NodeDesc("Denoiser", std::move(name)) {}

void DenoiserDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);
    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        sub_type = type_item->get<std::string>();
    } else {
        sub_type = "svgf";  // 默认值
    }
    auto param_item = params.find("param");
    if (param_item != params.end() && param_item->is_object()) {
        update_parameters(*param_item);
    }
}

// FilterDesc 实现
FilterDesc::FilterDesc() : NodeDesc("Filter") {}

FilterDesc::FilterDesc(std::string name) : NodeDesc("Filter", std::move(name)) {}

void FilterDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);
    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        sub_type = type_item->get<std::string>();
    } else {
        sub_type = "gaussian";  // 默认值
    }
    auto param_item = params.find("param");
    if (param_item != params.end() && param_item->is_object()) {
        update_parameters(*param_item);
    }
}

// IntegratorDesc 实现
IntegratorDesc::IntegratorDesc() : NodeDesc("Integrator") {}

IntegratorDesc::IntegratorDesc(std::string name) : NodeDesc("Integrator", std::move(name)) {}

void IntegratorDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);
    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        sub_type = type_item->get<std::string>();
    } else {
        sub_type = "pt";  // 默认值
    }
    auto param_item = params.find("param");
    if (param_item != params.end() && param_item->is_object()) {
        update_parameters(*param_item);
    }

    // 初始化 denoiser
    JsonWrapper denoiser_param = value("denoiser");
    if (denoiser_param.is_null() || denoiser_param.empty()) {
        denoiser_param = JsonWrapper::object();
        denoiser_param["type"] = "svgf";
    } else if (!denoiser_param.contains("type")) {
        denoiser_param["type"] = "svgf";
    }
    denoiser_desc.init(denoiser_param);

    // 初始化 cache
    JsonWrapper cache_param = value("cache");
    cache_desc.init(cache_param);
}

}  // namespace Corona::Resource::Scene
