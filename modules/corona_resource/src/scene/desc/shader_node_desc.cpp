#include <functional>

#include "corona/scene/desc/common.h"
#include "corona/scene/desc/node_desc.h"
#include "corona/scene/desc/shader_desc_s.h"

namespace Corona::Resource::Scene {

ShaderNodeDesc::ShaderNodeDesc() : AttrDesc("ShaderNode") {}

ShaderNodeDesc::ShaderNodeDesc(AttrTag tag, const std::string& s_type)
    : AttrDesc("ShaderNode"), node_tag(tag) {
    sub_type = s_type;
    params_ = JsonWrapper::object();
}

ShaderNodeDesc::ShaderNodeDesc(std::string name, AttrTag tag)
    : AttrDesc("ShaderNode", std::move(name)), node_tag(tag) {
    sub_type = "constant";
    params_ = JsonWrapper::object();
}

ShaderNodeDesc::ShaderNodeDesc(const JsonWrapper& params, AttrTag tag)
    : AttrDesc("ShaderNode"), node_tag(tag) {
    sub_type = "number";
    params_ = JsonWrapper::object();
    params_["value"] = params;
}

void ShaderNodeDesc::init(const JsonWrapper& params) {
    if (params.is_null()) {
        return;
    }
    NodeDesc::init(params);
    if (params.is_array()) {
        sub_type = "number";
        params_["value"] = params;
    } else if (params.is_object() && !params.contains("param")) {
        auto const& type_item = params.find("type");
        if (type_item != params.end() && type_item->is_string()) {
            sub_type = type_item->get<std::string>();
        } else {
            sub_type = "image";
        }

        if (sub_type == "image") {
            JsonWrapper json = JsonWrapper::object();
            auto const& fn_item = params.find("fn");
            auto const& color_space_item = params.find("color_space");
            if (fn_item != params.end() && fn_item->is_string()) {
                json["fn"] = fn_item->get<std::string>();
            } else {
                json["fn"] = "";
            }
            if (color_space_item != params.end() && color_space_item->is_object()) {
                json["color_space"] = *color_space_item;
            } else {
                json["color_space"] = JsonWrapper::object();
            }
            params_ = json;
        } else if (sub_type == "number") {
            JsonWrapper json = JsonWrapper::object();
            auto const& value_item = params.find("value");
            auto const& max_item = params.find("max");
            auto const& min_item = params.find("min");
            if (value_item != params.end() && value_item->is_object()) {
                json["value"] = *value_item;
            } else {
                json["value"] = JsonWrapper::object();
            }
            if (max_item != params.end() && max_item->is_number()) {
                json["max"] = max_item->get<double>();
            } else {
                json["max"] = 1.0;
            }
            if (min_item != params.end() && min_item->is_number()) {
                json["min"] = min_item->get<double>();
            } else {
                json["min"] = 0.0;
            }
            params_ = json;
        }
    } else if (params.is_number_float()) {
        params_["value"] = params.get<float>();
    } else {
        auto const& type_item = params.find("type");
        if (type_item != params.end() && type_item->is_string()) {
            sub_type = type_item->get<std::string>();
        } else {
            sub_type = "";
        }
        auto const& param_item = params.find("param");
        if (param_item != params.end() && param_item->is_object()) {
            update_parameters(*param_item);
        }
    }
}

std::shared_ptr<SlotDesc> ShaderNodeDesc::slot(const std::string& key, AttrTag tag) const noexcept {
    auto const& kJsonStr = params_.dump();
    ShaderNodeDesc node_desc{params_, tag};
    std::uint32_t size = params_.is_number() ? 1 : params_.size();
    auto slot_desc = std::make_shared<SlotDesc>(node_desc, size, tag);
    slot_desc->init(params_[key]);
    return slot_desc;
}

std::uint64_t ShaderNodeDesc::compute_hash() const noexcept {
    std::uint64_t h1 = NodeDesc::compute_hash();
    std::uint64_t h2 = std::hash<std::string>{}(parameter_string());
    return combine_hash(h1, h2);
}
}  // namespace Corona::Resource::Scene