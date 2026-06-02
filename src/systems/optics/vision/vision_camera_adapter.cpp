#include "vision_camera_adapter.h"

#ifdef CORONA_ENABLE_VISION

#include <cmath>

#include <corona/shared_data_hub.h>

#include "base/mgr/pipeline.h"
#include "base/sensor/sensor.h"

namespace Corona::Systems::Vision {

namespace {

[[nodiscard]] auto nearly_equal(float lhs, float rhs) -> bool {
    return std::abs(lhs - rhs) <= 1e-5f;
}

}  // namespace

void sync_vision_camera(::vision::Pipeline& pipeline, const CameraDevice& camera) {
    auto& sensor = pipeline.scene().sensor();
    const auto requested_resolution = ocarina::make_uint2(std::max(camera.width, 1u), std::max(camera.height, 1u));

    // Vision's Sensor is parametrised by (yaw, pitch, position) and ALWAYS rebuilds
    // its camera-to-world matrix from those values inside update_device_data():
    //   c2w = translation(position) * scale(1,1,-1) * rotation_y(yaw) * rotation_x(-pitch)
    // The previous code called set_mat() with a hand-built basis, but set_mat() only
    // stores position_ (NOT yaw_/pitch_); the immediately following update_device_data()
    // then overwrote c2w_ from the stale default yaw_/pitch_ (0/0). As a result the
    // Corona camera orientation was silently dropped (camera stuck looking down -Z) and
    // host_c2w() never matched the desired matrix, so invalidate() fired every frame and
    // the path tracer could never accumulate.
    //
    // Drive Vision's own model directly instead. From Vision's basis the forward (c2w
    // column 2) is forward = (sin(yaw)cos(pitch), sin(pitch), -cos(yaw)cos(pitch)), so
    // matching it to Corona's normalised forward gives:
    //   pitch = asin(fy),  yaw = atan2(fx, -fz)
    // Geometry is uploaded in Corona world space unchanged, so aligning Vision's look
    // direction with Corona's forward makes the scene appear in front of the camera.
    // (Roll / arbitrary world_up cannot be expressed by Vision's yaw/pitch-only model
    // and is intentionally ignored; world up is assumed +Y.)
    float fx = camera.forward.x;
    float fy = camera.forward.y;
    float fz = camera.forward.z;
    const float flen = std::sqrt(fx * fx + fy * fy + fz * fz);
    if (flen > 1e-6f) {
        fx /= flen;
        fy /= flen;
        fz /= flen;
    }
    float sin_pitch = fy;
    if (sin_pitch > 1.f) {
        sin_pitch = 1.f;
    } else if (sin_pitch < -1.f) {
        sin_pitch = -1.f;
    }

    constexpr float kRadToDeg = 57.295779513082320876f;
    const float pitch_deg = std::asin(sin_pitch) * kRadToDeg;
    const float yaw_deg = std::atan2(fx, -fz) * kRadToDeg;
    const auto position = ocarina::make_float3(camera.position.x, camera.position.y, camera.position.z);

    bool invalidate = false;
    if (ocarina::any(pipeline.resolution() != requested_resolution)) {
        pipeline.change_resolution(requested_resolution);
        // change_resolution()/FrameBuffer::update_resolution() reallocates all
        // internal per-pixel buffers but does NOT recreate view_texture_, which is
        // only built by prepare_view_texture(). Without rebuilding it here the
        // render-time tone_mapping writes the new (larger) resolution into the stale
        // smaller view texture, causing an out-of-bounds GPU access (ACCESS_VIOLATION).
        pipeline.frame_buffer()->prepare_view_texture();
        invalidate = true;
    }

    // Only reset path-tracing accumulation when the camera actually changed. Comparing
    // against the exact values Vision will store (yaw/pitch/position/fov) lets the
    // integrator keep converging while the camera is held still.
    const auto current_position = sensor->position();
    if (!nearly_equal(sensor->fov_y(), camera.fov) ||
        !nearly_equal(sensor->yaw(), yaw_deg) ||
        !nearly_equal(sensor->pitch(), pitch_deg) ||
        !nearly_equal(current_position.x, position.x) ||
        !nearly_equal(current_position.y, position.y) ||
        !nearly_equal(current_position.z, position.z)) {
        invalidate = true;
    }

    sensor->set_yaw(yaw_deg);
    sensor->set_pitch(pitch_deg);
    sensor->set_position(position);
    sensor->set_fov_y(camera.fov);
    sensor->update_device_data();

    if (invalidate) {
        pipeline.invalidate();
    }
}

}  // namespace Corona::Systems::Vision

#endif  // CORONA_ENABLE_VISION