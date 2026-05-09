#pragma once

#include "node_desc.h"

namespace Corona::Resource::Scene {

/**
 * @brief 辐射缓存描述
 * @details 用于描述辐射缓存的配置参数
 */
struct RadianceCacheDesc : public NodeDesc {
   public:
    RadianceCacheDesc();
    explicit RadianceCacheDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

/**
 * @brief 去噪器描述
 * @details 用于描述去噪器的配置参数
 */
struct DenoiserDesc : public NodeDesc {
   public:
    DenoiserDesc();
    explicit DenoiserDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

/**
 * @brief 滤波器描述
 * @details 用于描述像素滤波器的配置参数
 */
struct FilterDesc : public NodeDesc {
   public:
    FilterDesc();
    explicit FilterDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

/**
 * @brief 积分器描述
 * @details 用于描述光线追踪积分器的配置参数，包含去噪器和辐射缓存
 */
struct IntegratorDesc : public NodeDesc {
   public:
    DenoiserDesc denoiser_desc;
    RadianceCacheDesc cache_desc;

   public:
    IntegratorDesc();
    explicit IntegratorDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

}  // namespace Corona::Resource::Scene
