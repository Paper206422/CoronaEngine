#pragma once

#include "corona/scene/desc/integrator_desc.h"
#include "graph_desc.h"
#include "transform_desc.h"

namespace Corona::Resource::Scene {

/**
 * @brief 灯光描述
 * @details 用于描述场景中的灯光，包含变换信息
 */
struct LightDesc : public GraphDesc {
   public:
    TransformDesc o2w;

   public:
    LightDesc();
    explicit LightDesc(std::string name);

    void init(const JsonWrapper& params) noexcept override;

    /**
     * @brief 检查灯光描述是否有效
     * @return 如果子类型不为空则返回 true
     */
    [[nodiscard]] bool valid() const noexcept;
};

/**
 * @brief 形状描述
 * @details 用于描述场景中的几何形状，包含变换和发光信息
 */
struct ShapeDesc : public NodeDesc {
   public:
    TransformDesc o2w;
    LightDesc emission;

   public:
    ShapeDesc();
    explicit ShapeDesc(std::string name);

    void init(const JsonWrapper& params) noexcept override;

    /**
     * @brief 比较两个形状描述是否相等
     * @param other 另一个形状描述
     * @return 如果哈希值相等则返回 true
     */
    [[nodiscard]] bool operator==(const ShapeDesc& other) const noexcept;
};

/**
 * @brief 传感器描述
 * @details 用于描述相机或传感器，包含变换和滤波器信息
 */
struct SensorDesc : public NodeDesc {
   public:
    TransformDesc transform_desc;
    FilterDesc filter_desc;
    NameID medium;

   public:
    SensorDesc();
    explicit SensorDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

/**
 * @brief 介质描述
 * @details 用于描述参与介质的属性（如烟雾、雾）
 */
struct MediumDesc : public NodeDesc {
   public:
    ShaderNodeDesc sigma_a{AttrTag::Unbound};
    ShaderNodeDesc sigma_s{AttrTag::Unbound};
    ShaderNodeDesc g{AttrTag::Number};
    ShaderNodeDesc scale{AttrTag::Number};

   public:
    MediumDesc();
    explicit MediumDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

}  // namespace Corona::Resource::Scene
