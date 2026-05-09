#pragma once

#include <cstdint>

#include "common.h"
#include "node_desc.h"

namespace Corona::Resource::Scene {

/**
 * @brief 光谱描述
 * @details 用于描述光谱采样的配置参数
 */
struct SpectrumDesc : public NodeDesc {
   public:
    SpectrumDesc();
    explicit SpectrumDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

/**
 * @brief 输出描述
 * @details 用于描述渲染输出的配置参数
 */
struct OutputDesc : public NodeDesc {
   public:
    std::string fn;
    std::uint32_t spp{0u};
    bool save_exit{false};
    bool denoise{false};

   public:
    OutputDesc();
    explicit OutputDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

/**
 * @brief 渲染设置描述
 * @details 用于描述全局渲染设置的配置参数
 */
struct RenderSettingDesc : public NodeDesc {
   public:
    PolymorphicMode polymorphic_mode{};
    float min_world_radius{0.0f};
    float ray_offset_factor{1.0f};

   public:
    RenderSettingDesc();
    explicit RenderSettingDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

}  // namespace Corona::Resource::Scene
