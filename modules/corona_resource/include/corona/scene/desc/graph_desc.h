#pragma once

#include <map>

#include "node_desc.h"
#include "shader_desc_s.h"

namespace Corona::Resource::Scene {

struct ShaderNodeDesc;
struct GraphDesc : public AttrDesc {
    using AttrDesc::AttrDesc;

    template <typename T>
    [[nodiscard]] SlotDesc slot(const std::string& key, T defult_value, AttrTag tag = AttrTag::Number) const noexcept;
    [[nodiscard]] SlotDesc slot(const std::string& key, const JsonWrapper& params, AttrTag tag = AttrTag::Number) const noexcept;

    void init(const JsonWrapper& params) override;
    void init_node_map(const JsonWrapper& params);

    std::map<std::string, ShaderNodeDesc> node_map;
};

template <typename T>
SlotDesc GraphDesc::slot(const std::string& key, T defult_value, AttrTag tag) const noexcept {
    return AttrDesc::slot(key, defult_value, tag);
}

}  // namespace Corona::Resource::Scene