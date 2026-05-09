#pragma once

#include "common.h"
#include "node_desc.h"

namespace Corona::Resource::Scene {

struct SlotDesc;
struct ShaderNodeDesc;  // 前置声明

struct AttrDesc : public NodeDesc {
    using NodeDesc::NodeDesc;

    template <typename T>
    [[nodiscard]] SlotDesc slot(const std::string& key, T default_value, AttrTag tag = AttrTag::Number) const noexcept;
};

struct ShaderNodeDesc : public AttrDesc {
   public:
    ShaderNodeDesc();
    explicit ShaderNodeDesc(AttrTag tag, const std::string& s_type = "constant");
    ShaderNodeDesc(std::string name, AttrTag tag);
    ShaderNodeDesc(const JsonWrapper& params, AttrTag tag);

    [[nodiscard]] std::shared_ptr<SlotDesc> slot(const std::string& key, AttrTag tag = AttrTag::Number) const noexcept;

    void init(const JsonWrapper& params) override;

   protected:
    [[nodiscard]] std::uint64_t compute_hash() const noexcept override;

   public:
    AttrTag node_tag{};
};

struct SlotDesc : public NodeDesc {
    [[nodiscard]] static std::string default_channels(std::uint32_t dim) noexcept;
    [[nodiscard]] std::uint32_t dim() const noexcept;

    SlotDesc();
    explicit SlotDesc(const std::string name);
    SlotDesc(AttrTag tag, std::uint32_t dim);
    SlotDesc(ShaderNodeDesc node, std::uint32_t dim, AttrTag tag);

    void init(const JsonWrapper& params) override;

    std::string channels;
    std::string output_key;
    AttrTag attr_tag{};
    ShaderNodeDesc node;
};

template <typename T>
SlotDesc AttrDesc::slot(const std::string& key, T default_value, AttrTag tag) const noexcept {
    // TODO: Vision中未使用 暂时留空
    return SlotDesc{};
}

}  // namespace Corona::Resource::Scene