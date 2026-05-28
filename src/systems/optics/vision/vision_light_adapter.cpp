#include "vision_light_adapter.h"

#ifdef CORONA_ENABLE_VISION

#include <cmath>

#include <corona/shared_data_hub.h>

#include "base/illumination/light.h"
#include "base/import/node_desc.h"
#include "base/mgr/scene.h"

namespace Corona::Systems::Vision {

void setup_vision_lights(::vision::Scene& scene, const EnvironmentDevice& env) {
    // -------------------------------------------------------------------------
    // 1. DirectionalLight from sun_position + sun_color + sun_intensity
    // -------------------------------------------------------------------------
    // sun_position is a world-space point; compute a normalised direction from
    // origin to that point to get the "direction toward the sun".
    float sx = env.sun_position.x;
    float sy = env.sun_position.y;
    float sz = env.sun_position.z;
    float slen = std::sqrt(sx * sx + sy * sy + sz * sz);
    if (slen < 1e-6f) { sx = 0.f; sy = 1.f; sz = 0.f; }
    else { sx /= slen; sy /= slen; sz /= slen; }

    // Vision DirectionalLight "direction" field is the *light direction vector*
    // (from surface toward light, i.e. toward the sun):
    ::vision::LightDesc dir_desc("directional");
    dir_desc.init();
    dir_desc.set_value("direction", ocarina::DataWrap::array({sx, sy, sz}));
    dir_desc.set_value("scale", env.sun_intensity);

    // color: {channels:"xyz", node:{type:"number", param:{value:[r,g,b]}}}
    float cr = env.sun_color.x;
    float cg = env.sun_color.y;
    float cb = env.sun_color.z;
    ::vision::ShaderNodeDesc color_node(ocarina::make_float3(cr, cg, cb), ::vision::AttrTag::Albedo);
    ::vision::SlotDesc color_slot(color_node, 3u, ::vision::AttrTag::Albedo);
    dir_desc.set_value("color", ocarina::DataWrap::array({cr, cg, cb}));
    dir_desc.set_value("strength", env.sun_intensity);

    auto dir_light = scene.load_light(dir_desc);
    if (dir_light) {
        scene.add_light(std::move(dir_light));
    }

    // -------------------------------------------------------------------------
    // 2. Constant environment light for ambient sky
    //    Use a spherical light with a constant grey color scaled by sky_intensity
    //    (Vision "spherical" with a "number" color node acts as a sky dome).
    // -------------------------------------------------------------------------
    float sky = env.sky_intensity;
    // Clamp to a reasonable range to avoid blown-out results
    if (sky < 0.f) sky = 0.f;

    ::vision::LightDesc sky_desc("spherical");
    sky_desc.init();
    // Uniform white colour; the strength node controls the total radiance
    sky_desc.set_value("color", ocarina::DataWrap::array({1.f, 1.f, 1.f}));
    sky_desc.set_value("strength", sky);
    sky_desc.set_value("scale", 1.f);

    auto sky_light = scene.load_light(sky_desc);
    if (sky_light) {
        scene.add_light(std::move(sky_light));
    }
}

}  // namespace Corona::Systems::Vision

#endif  // CORONA_ENABLE_VISION
