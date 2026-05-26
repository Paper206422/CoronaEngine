#pragma once

#ifdef CORONA_ENABLE_VISION

namespace vision {
class Pipeline;
}

namespace Corona {
struct CameraDevice;
}

namespace Corona::Systems::Vision {

void sync_vision_camera(::vision::Pipeline& pipeline, const CameraDevice& camera);

}  // namespace Corona::Systems::Vision

#endif  // CORONA_ENABLE_VISION