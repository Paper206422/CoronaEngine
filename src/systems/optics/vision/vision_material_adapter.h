#pragma once

// Vision material adapter - maps CoronaEngine OpticsDevice + MeshDevice material
// parameters to a Vision PrincipledBSDF material.
// Only compiled when CORONA_ENABLE_VISION is defined.

#ifdef CORONA_ENABLE_VISION

#include <array>
#include <memory>

// Forward declarations
namespace vision {
class Material;
}  // namespace vision

namespace Corona {
struct OpticsDevice;
struct MeshDevice;
}  // namespace Corona

namespace Corona::Systems::Vision {

// Maps a single CoronaEngine material to a Vision Material (PrincipledBSDF).
// Mapping rules (first version, flat color only):
//   MeshDevice::materialColor[0..2] -> baseColor
//   OpticsDevice::roughness          -> roughness
//   OpticsDevice::metallic           -> metallic
//   all other Vision principled params -> Vision defaults
//
// Returns nullptr on failure.
std::shared_ptr<::vision::Material> create_vision_material(
    const OpticsDevice& optics,
    const MeshDevice& mesh_dev);

}  // namespace Corona::Systems::Vision

#endif  // CORONA_ENABLE_VISION
