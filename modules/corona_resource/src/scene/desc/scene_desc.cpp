#include "corona/scene/desc/scene_desc.h"

#include <fstream>

namespace Corona::Resource::Scene {

void SceneDesc::init_material_descs(const JsonWrapper& materials) noexcept {
    if (materials.is_null() || !materials.is_array()) {
        return;
    }

    for (std::size_t i = 0; i < materials.size(); ++i) {
        MaterialDesc md;
        md.init(materials[i]);
        material_descs.push_back(md);
    }
}

void SceneDesc::init_shape_descs(const JsonWrapper& shapes) noexcept {
    if (shapes.is_null() || !shapes.is_array()) {
        return;
    }

    for (const auto& shape : shapes) {
        ShapeDesc sd;
        sd.init(shape);
        shape_descs.push_back(sd);
    }
}

void SceneDesc::init_medium_descs(const JsonWrapper& mediums) noexcept {
    if (mediums.is_null()) {
        return;
    }

    auto global_item = mediums.find("global");
    if (global_item != mediums.end() && global_item->is_string()) {
        mediums_desc.global = global_item->get<std::string>();
    }

    auto process_item = mediums.find("process");
    if (process_item != mediums.end() && process_item->is_boolean()) {
        mediums_desc.process = process_item->get<bool>();
    } else {
        mediums_desc.process = true;  // 默认值
    }

    auto list_item = mediums.find("list");
    if (list_item != mediums.end() && list_item->is_array()) {
        for (const auto& elm : *list_item) {
            MediumDesc desc;
            desc.init(elm);
            mediums_desc.mediums.push_back(desc);
        }
    }
}

void SceneDesc::init(const JsonWrapper& data) noexcept {
    if (data.is_null()) {
        return;
    }

    // 初始化积分器
    integrator_desc.init(data.value("integrator", JsonWrapper::object()));

    // 初始化光谱
    spectrum_desc.init(data.value("spectrum", JsonWrapper::object()));

    // 初始化灯光采样器
    light_sampler_desc.init(data.value("light_sampler", JsonWrapper::object()));

    // 初始化采样器
    sampler_desc.init(data.value("sampler", JsonWrapper::object()));

    // 初始化变换器
    warper_desc = WarperDesc("Warper");
    warper_desc.sub_type = "alias";

    // 初始化材质列表
    init_material_descs(data.value("materials", JsonWrapper::array()));

    // 初始化介质列表
    init_medium_descs(data.value("mediums", JsonWrapper::object()));

    // 初始化形状列表
    init_shape_descs(data.value("shapes", JsonWrapper::array()));

    // 初始化相机/传感器
    sensor_desc.init(data.value("camera", JsonWrapper::object()));
    sensor_desc.medium.name = mediums_desc.global;

    // 初始化输出
    output_desc.init(data.value("output", JsonWrapper::object()));

    // 初始化渲染设置
    render_setting.init(data.value("render_setting", JsonWrapper::object()));

    // 初始化去噪器
    denoiser_desc.init(data.value("denoiser", JsonWrapper::object()));

    // 初始化渲染管线
    pipeline_desc.init(data.value("pipeline", JsonWrapper::object()));
}

SceneDesc SceneDesc::from_json(const std::filesystem::path& path) {
    SceneDesc scene_desc;
    scene_desc.scene_path = path.parent_path();

    try {
        std::ifstream file(path);
        if (!file.is_open()) {
            return scene_desc;
        }

        JsonWrapper data = JsonWrapper::parse(file);
        scene_desc.init(data);
    } catch (const std::exception& e) {
        // Error parsing JSON
    }

    return scene_desc;
}

}  // namespace Corona::Resource::Scene
