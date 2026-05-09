#pragma once

#include "node_desc.h"

namespace Corona::Resource::Scene {

/**
 * @brief 上采样器描述
 * @details 用于描述图像上采样器的配置参数
 */
struct UpsamplerDesc : public NodeDesc {
   public:
    UpsamplerDesc();
    explicit UpsamplerDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

/**
 * @brief 色调映射器描述
 * @details 用于描述色调映射器的配置参数
 */
struct ToneMapperDesc : public NodeDesc {
   public:
    ToneMapperDesc();
    explicit ToneMapperDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

/**
 * @brief 帧缓冲描述
 * @details 用于描述帧缓冲的配置参数，包含色调映射器和上采样器
 */
struct FrameBufferDesc : public NodeDesc {
   public:
    ToneMapperDesc tone_mapper;
    UpsamplerDesc upsampler_desc;

   public:
    FrameBufferDesc();
    explicit FrameBufferDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

/**
 * @brief 光栅化器描述
 * @details 用于描述光栅化器的配置参数
 */
struct RasterizerDesc : public NodeDesc {
   public:
    RasterizerDesc();
    explicit RasterizerDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

/**
 * @brief UV 展开器描述
 * @details 用于描述 UV 展开器的配置参数
 */
struct UVUnwrapperDesc : public NodeDesc {
   public:
    UVUnwrapperDesc();
    explicit UVUnwrapperDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

/**
 * @brief 渲染通道描述
 * @details 用于描述渲染通道的配置参数
 */
struct PassDesc : public NodeDesc {
   public:
    PassDesc();
    explicit PassDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

/**
 * @brief 渲染管线描述
 * @details 用于描述渲染管线的配置参数，包含 UV 展开器、帧缓冲和光栅化器
 */
struct PipelineDesc : public NodeDesc {
   public:
    UVUnwrapperDesc unwrapper_desc;
    FrameBufferDesc frame_buffer_desc;
    RasterizerDesc rasterizer_desc;

   public:
    PipelineDesc();
    explicit PipelineDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

}  // namespace Corona::Resource::Scene
