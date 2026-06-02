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

// Structured outcome of a geometry build pass. Lets callers distinguish a
// genuinely empty scene (no candidate objects at all) from a transient
// "data-not-ready" state (candidates existed but their CPU/GPU mesh data could
// not be loaded yet), so dynamic-scene rebuilds can retry only when warranted.
struct VisionBuildResult {
    int instance_count = 0;   ///< ShapeInstances successfully added.
    int candidate_count = 0;  ///< Visible objects with geometry that passed all filters.
    int skipped_no_data = 0;  ///< Candidates skipped because mesh data was unavailable.
};

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
// Returns a VisionBuildResult describing how many instances were added and
// whether any candidate objects were skipped due to missing mesh data.
VisionBuildResult build_vision_geometry(::vision::Scene& scene);

}  // namespace Corona::Systems::Vision

#endif  // CORONA_ENABLE_VISION
