#pragma once

// Vision geometry adapter - converts CoronaEngine scene geometry (CPU mesh data,
// transforms, per-mesh materials) into Vision ShapeGroup / ShapeInstance objects
// and adds them to the Vision scene.
// Only compiled when CORONA_ENABLE_VISION is defined.

#ifdef CORONA_ENABLE_VISION

// Forward declarations
namespace vision {
class Scene;
}  // namespace vision

namespace Corona::Systems::Vision {

// Clears the Vision scene's existing shapes and repopulates it from the
// CoronaEngine SharedDataHub (all enabled SceneDevice → actors → geometry).
//
// For each GeometryDevice that has a valid model_resource_handle:
//   - Reads CPU mesh vertices/indices from the Corona resource layer.
//   - Creates a Vision Mesh.
//   - Creates a Vision ShapeInstance with the object-to-world transform and
//     a PrincipledBSDF material mapped from the corresponding OpticsDevice.
//   - Adds it to the Vision scene via a ShapeGroup.
//
// After this call, caller must invoke:
//   pipeline->geometry()->build_accel() / upload()
//
// Returns the number of ShapeInstances successfully added.
int build_vision_geometry(::vision::Scene& scene);

}  // namespace Corona::Systems::Vision

#endif  // CORONA_ENABLE_VISION
