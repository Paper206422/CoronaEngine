#pragma once

#include <filesystem>
#include <vector>

#include "integrator_desc.h"
#include "material_desc.h"
#include "output_desc.h"
#include "pipeline_desc.h"
#include "sampler_desc.h"
#include "scene_element_desc.h"

namespace Corona::Resource::Scene {

/**
 * @brief 介质集合描述
 * @details 用于管理场景中所有介质的配置
 */
struct MediumsDesc {
    std::vector<MediumDesc> mediums;
    bool process{false};
    std::string global;
};

/**
 * @brief 场景描述
 * @details 包含完整场景的所有配置信息，包括相机、采样器、积分器、材质、形状等
 */
struct SceneDesc {
   public:
    SensorDesc sensor_desc;
    SamplerDesc sampler_desc;
    SpectrumDesc spectrum_desc;
    LightSamplerDesc light_sampler_desc;
    IntegratorDesc integrator_desc;
    WarperDesc warper_desc;
    std::vector<MaterialDesc> material_descs;
    std::vector<ShapeDesc> shape_descs;
    OutputDesc output_desc;
    PipelineDesc pipeline_desc;
    std::filesystem::path scene_path;
    MediumsDesc mediums_desc;
    DenoiserDesc denoiser_desc;
    RenderSettingDesc render_setting;

   public:
    SceneDesc() = default;

    /**
     * @brief 从 JSON 文件加载场景描述
     * @param path JSON 文件路径
     * @return 场景描述对象
     */
    static SceneDesc from_json(const std::filesystem::path& path);

    /**
     * @brief 初始化场景描述
     * @param data JSON 数据包装器
     */
    void init(const JsonWrapper& data) noexcept;

    /**
     * @brief 初始化材质描述列表
     * @param materials 材质 JSON 数据
     */
    void init_material_descs(const JsonWrapper& materials) noexcept;

    /**
     * @brief 初始化形状描述列表
     * @param shapes 形状 JSON 数据
     */
    void init_shape_descs(const JsonWrapper& shapes) noexcept;

    /**
     * @brief 初始化介质描述列表
     * @param mediums 介质 JSON 数据
     */
    void init_medium_descs(const JsonWrapper& mediums) noexcept;
};

}  // namespace Corona::Resource::Scene