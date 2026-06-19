//
// Created by Z on 2025/11/29.
//

#pragma once

#include "base/import/project_desc.h"
#include "global.h"
#include "base/sensor/sensor.h"
#include "base/shape.h"
#include "base/illumination/lightsampler.h"
#include "base/scattering/material.h"
#include "base/scattering/medium.h"
#include "base/warper.h"
#include "registries.h"
#include "geometry.h"
#include "UI/GUI.h"
#include "hotfix/hotfix.h"
#include "base/using.h"

namespace vision {

class LightManager : public GUI, public hotfix::Observer {
protected:
    PolymorphicGUI<TLight> lights_{};
    TEnvironment env_light_{};

public:
    LightManager() = default;
    OC_MAKE_MEMBER_GETTER(lights, &)
    VS_MAKE_GUI_STATUS_FUNC(GUI, lights_)
    bool render_UI(Widgets *widgets) noexcept override;
    void init(const vector<LightDesc> &light_descs) noexcept;
    void add_light(TLight light) noexcept;
    void remove_light(TLight light) noexcept;
    [[nodiscard]] const Environment *env_light() const noexcept { return env_light_.get(); }
    [[nodiscard]] Environment *env_light() noexcept { return env_light_.get(); }
    [[nodiscard]] uint env_index() const noexcept { return env_light()->index(); }
    void update_runtime_object(const vision::IObjectConstructor *constructor) noexcept override;
    void upload_immediately() noexcept;
    [[nodiscard]] CommandBatch upload(bool async = true) noexcept;
    void tidy_up() noexcept;

    template<typename Func>
    void for_each(Func &&func) noexcept {
        if constexpr (std::invocable<Func, TLight>) {
            for (TLight light : lights()) {
                func(light);
            }
        } else {
            uint i = 0u;
            for (TLight light : lights()) {
                func(light, i++);
            }
        }
    }

    template<typename Func>
    void for_each(Func &&func) const noexcept {
        if constexpr (std::invocable<Func, SP<const Light>>) {
            for (const TLight &light : lights()) {
                func(light);
            }
        } else {
            uint i = 0u;
            for (const TLight &light : lights()) {
                func(light, i++);
            }
        }
    }
};

class Scene : public GUI, public hotfix::Observer {
private:
    Geometry geometry_;
    Box3f aabb_;
    PolymorphicGUI<TSensor> sensors_{};
    uint cur_sensor_index_{0};
    TSensor *sensor_override_{nullptr};
    SP<Material> black_body_{};
    LightManager light_manager_{};
    MaterialRegistry *material_registry_{&MaterialRegistry::instance()};
    MediumRegistry *medium_registry_{&MediumRegistry::instance()};
    vector<SP<ShapeGroup>> groups_;
    vector<SP<ShapeInstance>> instances_;
    float min_radius_{};
    friend class Pipeline;

public:
    Scene() = default;
    void init(const SceneDesc &scene_desc);
    OC_MAKE_MEMBER_SETTER(min_radius)
    void prepare() noexcept;
    void update_runtime_object(const vision::IObjectConstructor *constructor) noexcept override;

    VS_MAKE_GUI_ALL_FUNC(GUI, sensors_, light_manager_, material_registry_, medium_registry_)

    void update_resolution(uint2 res) noexcept { sensor()->update_resolution(res); }

    // Sensor access
    [[nodiscard]] TSensor &sensor() noexcept {
        return sensor_override_ != nullptr ? *sensor_override_ : sensors_[cur_sensor_index_];
    }
    [[nodiscard]] const TSensor &sensor() const noexcept {
        return sensor_override_ != nullptr ? *sensor_override_ : sensors_[cur_sensor_index_];
    }
    void set_sensor_override(TSensor *sensor) noexcept { sensor_override_ = sensor; }
    void add_sensor(TSensor s) noexcept { sensors_.push_back(ocarina::move(s)); }
    void remove_sensor(const TSensor &s) noexcept {
        std::erase_if(sensors_, [&](const TSensor &elm) { return elm.get() == s.get(); });
    }
    OC_MAKE_MEMBER_GETTER_SETTER(cur_sensor_index, )

    // Geometry
    OC_MAKE_MEMBER_GETTER(geometry, &)
    void update_geometry_instances() noexcept { geometry_.update_instances(instances_); }

    // Shapes
    OC_MAKE_MEMBER_GETTER(groups, &)
    OC_MAKE_MEMBER_GETTER(instances, &)
    void load_shapes(const vector<ShapeDesc> &descs);
    void add_shape(const SP<ShapeGroup> &group, ShapeDesc desc = {});
    void clear_shapes() noexcept;

    // Materials
    [[nodiscard]] const auto &material_registry() const noexcept { return *material_registry_; }
    [[nodiscard]] auto &material_registry() noexcept { return *material_registry_; }
    [[nodiscard]] const auto &materials() const noexcept { return material_registry().elements(); }
    [[nodiscard]] auto &materials() noexcept { return material_registry().elements(); }
    void add_material(SP<Material> material) noexcept;
    void load_materials(const vector<MaterialDesc> &material_descs);
    void prepare_materials();
    [[nodiscard]] SP<Material> obtain_black_body() noexcept;

    // Mediums
    [[nodiscard]] const auto &medium_registry() const noexcept { return *medium_registry_; }
    [[nodiscard]] auto &medium_registry() noexcept { return *medium_registry_; }
    [[nodiscard]] const auto &mediums() const noexcept { return medium_registry_->elements(); }
    [[nodiscard]] auto &mediums() noexcept { return medium_registry_->elements(); }
    [[nodiscard]] bool process_mediums() const noexcept { return medium_registry_->process_mediums(); }
    void load_mediums(const MediumsDesc &desc);

    // Lights
    OC_MAKE_MEMBER_GETTER(light_manager, &)
    void add_light(TLight light) noexcept;
    TLight load_light(const LightDesc &desc) noexcept;

    // Instances
    void fill_instances();
    [[nodiscard]] ShapeInstance *get_instance(uint id) noexcept { return instances_[id].get(); }
    [[nodiscard]] const ShapeInstance *get_instance(uint id) const noexcept { return instances_[id].get(); }

    // World bounds
    [[nodiscard]] float3 world_center() const noexcept { return aabb_.center(); }
    [[nodiscard]] float world_radius() const noexcept { return ocarina::max(aabb_.radius(), min_radius_); }
    [[nodiscard]] float world_diameter() const noexcept { return world_radius() * 2; }

    void tidy_up() noexcept;
};

}// namespace vision
