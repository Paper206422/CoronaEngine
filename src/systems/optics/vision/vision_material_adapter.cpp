#include "vision_material_adapter.h"

#ifdef CORONA_ENABLE_VISION

#include <corona/shared_data_hub.h>

#include "base/import/node_desc.h"
#include "base/scattering/material.h"

namespace Corona::Systems::Vision {

std::shared_ptr<::vision::Material> create_vision_material(
    const OpticsDevice& optics,
    const MeshDevice& mesh_dev) {

    // Build a MaterialDesc for principled_bsdf
    ::vision::MaterialDesc desc("principled_bsdf");
    desc.init();

    // baseColor from MeshDevice::materialColor (RGBA, use RGB)
    float r = mesh_dev.materialColor[0];
    float g = mesh_dev.materialColor[1];
    float b = mesh_dev.materialColor[2];
    desc.set_value("color", ocarina::DataWrap::array({r, g, b}));

    // roughness and metallic from OpticsDevice
    desc.set_value("roughness", optics.roughness);
    desc.set_value("metallic", optics.metallic);

    return ::vision::Material::create_root(desc);
}

}  // namespace Corona::Systems::Vision

#endif  // CORONA_ENABLE_VISION
