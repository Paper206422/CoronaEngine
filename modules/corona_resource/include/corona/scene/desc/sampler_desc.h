#pragma once

#include <vector>

#include "node_desc.h"
#include "scene_element_desc.h"

namespace Corona::Resource::Scene {

/**
 * @brief 采样器描述
 * @details 用于描述随机数采样器的配置参数
 */
struct SamplerDesc : public NodeDesc {
   public:
    SamplerDesc();
    explicit SamplerDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

/**
 * @brief 灯光采样器描述
 * @details 用于描述灯光采样策略的配置参数，包含灯光列表
 */
struct LightSamplerDesc : public NodeDesc {
   public:
    std::vector<LightDesc> light_descs;

   public:
    LightSamplerDesc();
    explicit LightSamplerDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

/**
 * @brief 变换器描述
 * @details 用于描述坐标变换或扭曲函数的配置参数
 */
struct WarperDesc : public NodeDesc {
   public:
    WarperDesc();
    explicit WarperDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

}  // namespace Corona::Resource::Scene
