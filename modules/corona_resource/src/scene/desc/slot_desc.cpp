#include "corona/scene/desc/shader_desc_s.h"

namespace Corona::Resource::Scene {

std::string SlotDesc::default_channels(std::uint32_t dim) noexcept {
    switch (dim) {
        case 1:
            return "x";
        case 2:
            return "xy";
        case 3:
            return "xyz";
        case 4:
            return "xyzw";
        default:
            return "";
    }
}

std::uint32_t SlotDesc::dim() const noexcept {
    return static_cast<std::uint32_t>(channels.size());
}

SlotDesc::SlotDesc() : NodeDesc("Slot") {}

SlotDesc::SlotDesc(const std::string name) : NodeDesc("Slot", std::move(name)) {}

SlotDesc::SlotDesc(AttrTag tag, std::uint32_t dim)
    : node(tag), channels(default_channels(dim)), attr_tag(tag) {}

SlotDesc::SlotDesc(ShaderNodeDesc node, std::uint32_t dim, AttrTag tag)
    : node(std::move(node)), channels(default_channels(dim)), attr_tag(tag) {}

void SlotDesc::init(const JsonWrapper& params) {
    if (params.is_null()) {
        return;
    }

    // 如果参数包含 channels 字段，说明是完整的 slot 描述
    if (params.contains("channels")) {
        auto channels_item = params.find("channels");
        if (channels_item != params.end() && channels_item->is_string()) {
            channels = channels_item->get<std::string>();
        }

        auto node_item = params.find("node");
        if (node_item != params.end()) {
            node.init(*node_item);
        }

        auto output_key_item = params.find("output_key");
        if (output_key_item != params.end() && output_key_item->is_string()) {
            output_key = output_key_item->get<std::string>();
        }
    } else {
        // 否则将整个参数作为 node 的初始化数据
        node.init(params);
    }

    // 处理标量扩展到向量的情况
    auto value_item = node.value("value");
    if (dim() > 1 && value_item.is_number()) {
        JsonWrapper value_array = JsonWrapper::array();
        for (std::uint32_t i = 0; i < dim(); ++i) {
            value_array.push_back(value_item);
        }
        node["value"] = value_array;
    } else if (params.is_number()) {
        // 处理直接是数字的情况
        channels = "x";
        node.sub_type = "number";
        node["value"] = params;
    }
}

}  // namespace Corona::Resource::Scene