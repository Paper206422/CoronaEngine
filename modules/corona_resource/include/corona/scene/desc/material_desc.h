#pragma once

#include <memory>

#include "graph_desc.h"

namespace Corona::Resource::Scene {

/**
 * @brief 材质描述
 * @details 用于描述材质的属性和着色器节点图，支持材质混合
 */
struct MaterialDesc : public GraphDesc {
   public:
    std::shared_ptr<MaterialDesc> mat0;
    std::shared_ptr<MaterialDesc> mat1;

   public:
    MaterialDesc();
    explicit MaterialDesc(std::string name);
    void init(const JsonWrapper& params) noexcept override;
};

}  // namespace Corona::Resource::Scene
