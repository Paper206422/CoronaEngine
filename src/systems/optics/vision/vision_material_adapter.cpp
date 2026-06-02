#include "vision_material_adapter.h"

#ifdef CORONA_ENABLE_VISION

#include <corona/shared_data_hub.h>

#include "base/import/node_desc.h"
#include "base/scattering/material.h"

namespace Corona::Systems::Vision {

std::shared_ptr<::vision::Material> create_vision_material(
    const OpticsDevice& optics,
    const MeshDevice& mesh_dev) {

    // Build a MaterialDesc for principled_bsdf.
    // Pass an empty JSON object (not a default-constructed null ParameterSet):
    // MaterialDesc::init -> GraphDesc::init -> NodeDesc::set_parameter asserts
    // is_object() and uses nlohmann value()/at(), which abort()/SIGABRT on a
    // null payload under JSON_NOEXCEPTION.
    ::vision::MaterialDesc desc("principled_bsdf");
    desc.init(::vision::ParameterSet{::vision::DataWrap::object()});

    // baseColor from MeshDevice::materialColor (RGBA, use RGB)
    float r = mesh_dev.materialColor[0];
    float g = mesh_dev.materialColor[1];
    float b = mesh_dev.materialColor[2];
    desc.set_value("color", ::vision::DataWrap::array({r, g, b}));

    // roughness and metallic from OpticsDevice
    desc.set_value("roughness", optics.roughness);
    desc.set_value("metallic", optics.metallic);

    return ::vision::Material::create_root(desc);
}

}  // namespace Corona::Systems::Vision

#endif  // CORONA_ENABLE_VISION
