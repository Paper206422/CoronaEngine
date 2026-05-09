#include "corona/scene/desc/scene_element_desc.h"

#include "corona/scene/desc/common.h"

namespace Corona::Resource::Scene {

// LightDesc 实现
LightDesc::LightDesc() : GraphDesc("Light") {}

LightDesc::LightDesc(std::string name) : GraphDesc("Light", std::move(name)) {}

void LightDesc::init(const JsonWrapper& params) noexcept {
    GraphDesc::init(params);

    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        sub_type = type_item->get<std::string>();
    } else {
        sub_type = "area";  // 默认值
    }

    auto param_item = params.find("param");
    if (param_item != params.end() && param_item->is_object()) {
        update_parameters(*param_item);

        // 初始化变换
        auto o2w_item = param_item->find("o2w");
        if (o2w_item != param_item->end()) {
            o2w.init(*o2w_item);
        }
    }
}

bool LightDesc::valid() const noexcept {
    return !sub_type.empty();
}

// ShapeDesc 实现
ShapeDesc::ShapeDesc() : NodeDesc("Shape") {}

ShapeDesc::ShapeDesc(std::string name) : NodeDesc("Shape", std::move(name)) {}

void ShapeDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);

    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        sub_type = type_item->get<std::string>();
    }

    auto name_item = params.find("name");
    if (name_item != params.end() && name_item->is_string()) {
        name = name_item->get<std::string>();
    }

    auto param_item = params.find("param");
    if (param_item != params.end() && param_item->is_object()) {
        update_parameters(*param_item);

        // 初始化变换
        auto transform_item = param_item->find("transform");
        if (transform_item != param_item->end()) {
            o2w.init(*transform_item);
        }
    }

    // 初始化 emission
    auto emission_item = value("emission");
    if (!emission_item.is_null() && emission_item.is_object()) {
        emission.init(emission_item);
    }
}

bool ShapeDesc::operator==(const ShapeDesc& other) const noexcept {
    // TODO: hash 比较逻辑
    return false;
}

// SensorDesc 实现
SensorDesc::SensorDesc() : NodeDesc("Sensor") {}

SensorDesc::SensorDesc(std::string name) : NodeDesc("Sensor", std::move(name)) {}

void SensorDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);

    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        sub_type = type_item->get<std::string>();
    } else {
        sub_type = "thin_lens";  // 默认值
    }

    auto param_item = params.find("param");
    if (param_item != params.end() && param_item->is_object()) {
        update_parameters(*param_item);
    }

    // 初始化变换
    transform_desc.init(value("transform"));

    // 初始化 medium
    auto const& medium_item = params.find("medium");
    if (medium_item != params.end() && medium_item->is_string()) {
        medium.name = medium_item->get<std::string>();
    }
}

// MediumDesc 实现
MediumDesc::MediumDesc() : NodeDesc("Medium") {}

MediumDesc::MediumDesc(std::string name) : NodeDesc("Medium", std::move(name)) {}

void MediumDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);

    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        sub_type = type_item->get<std::string>();
    } else {
        sub_type = "homogeneous";  // 默认值
    }

    auto param_item = params.find("param");
    if (param_item != params.end() && param_item->is_object()) {
        update_parameters(*param_item);
    }

    std::string medium_name;
    auto const& medium_name_item = params_.find("medium_name");
    if (medium_name_item != params_.end() && medium_name_item->is_string()) {
        medium_name = medium_name_item->get<std::string>();
    }

    if (!medium_name.empty()) {
        auto const& [sigma_s_val, sigma_a_val] = get_sigma(medium_name);
        sigma_s.init(JsonWrapper({sigma_s_val.x, sigma_s_val.y, sigma_s_val.z}));
        sigma_a.init(JsonWrapper({sigma_a_val.x, sigma_a_val.y, sigma_a_val.z}));
    } else {
        sigma_s.init(value("sigma_s"));
        sigma_a.init(value("sigma_a"));
    }
    scale.init(value("scale"));
    g.init(value("g"));
}

}  // namespace Corona::Resource::Scene
