#include "corona/scene/desc/graph_desc.h"

namespace Corona::Resource::Scene {

SlotDesc GraphDesc::slot(const std::string& key, const JsonWrapper& params, AttrTag tag) const noexcept {
    ShaderNodeDesc node{params, tag};
    node.name = key;
    std::uint32_t size = params.is_number() ? 1 : params.size();
    SlotDesc slot_desc{node, size, tag};
    auto const& item = params.find(key);
    if (item != params.end()) {
        slot_desc.init(*item);
    }
    return slot_desc;
}

void GraphDesc::init(const JsonWrapper& params) {
    NodeDesc::init(params);
    init_node_map(params.value("node_tab", JsonWrapper::object()));
    update_parameters(params.value("param", JsonWrapper::object()));
}

void GraphDesc::init_node_map(const JsonWrapper& params) {
    for (auto const& [key, value] : params.items()) {
        ShaderNodeDesc shader_node_desc;
        shader_node_desc.init(value);
        node_map.insert(make_pair(key, shader_node_desc));
    }
}

}  // namespace Corona::Resource::Scene