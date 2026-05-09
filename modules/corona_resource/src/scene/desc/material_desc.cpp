#include "corona/scene/desc/material_desc.h"

namespace Corona::Resource::Scene {

// MaterialDesc 实现
MaterialDesc::MaterialDesc() : GraphDesc("Material") {}

MaterialDesc::MaterialDesc(std::string name) : GraphDesc("Material", std::move(name)) {}

void MaterialDesc::init(const JsonWrapper& params) noexcept {
    GraphDesc::init(params);
    init_node_map(params.value("node_tab", JsonWrapper::object()));

    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        sub_type = type_item->get<std::string>();
    } else {
        sub_type = "diffuse";  // 默认值
    }

    // 处理 mix 或 add 材质
    if (sub_type == "mix" || sub_type == "add") {
        auto param_item = params.find("param");
        if (param_item != params.end() && param_item->is_object()) {
            auto mat0_item = param_item->find("mat0");
            if (mat0_item != param_item->end() && mat0_item->is_object()) {
                mat0 = std::make_shared<MaterialDesc>();
                mat0->init(*mat0_item);
            }

            auto mat1_item = param_item->find("mat1");
            if (mat1_item != param_item->end() && mat1_item->is_object()) {
                mat1 = std::make_shared<MaterialDesc>();
                mat1->init(*mat1_item);
            }

            update_parameters(*param_item);
        }
    } else {
        auto param_item = params.find("param");
        if (param_item != params.end() && param_item->is_object()) {
            update_parameters(*param_item);
        }
    }
}

}  // namespace Corona::Resource::Scene
