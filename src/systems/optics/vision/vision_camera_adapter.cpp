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

[[nodiscard]] auto matrix_equal(const ocarina::float4x4& lhs,
                                const ocarina::float4x4& rhs) -> bool {
    for (int col = 0; col < 4; ++col) {
        for (int row = 0; row < 4; ++row) {
            if (!nearly_equal(lhs[col][row], rhs[col][row])) {
                return false;
            }
        }
    }
    return true;
}

[[nodiscard]] auto make_camera_to_world(const CameraDevice& camera) -> ocarina::float4x4 {
    float fx = camera.forward.x;
    float fy = camera.forward.y;
    float fz = camera.forward.z;
    float ux = camera.world_up.x;
    float uy = camera.world_up.y;
    float uz = camera.world_up.z;

    float zx = -fx;
    float zy = -fy;
    float zz = -fz;
    float zlen = std::sqrt(zx * zx + zy * zy + zz * zz);
    if (zlen > 1e-6f) {
        zx /= zlen;
        zy /= zlen;
        zz /= zlen;
    }

    float xx = uy * zz - uz * zy;
    float xy = uz * zx - ux * zz;
    float xz = ux * zy - uy * zx;
    float xlen = std::sqrt(xx * xx + xy * xy + xz * xz);
    if (xlen > 1e-6f) {
        xx /= xlen;
        xy /= xlen;
        xz /= xlen;
    }

    float yx = zy * xz - zz * xy;
    float yy = zz * xx - zx * xz;
    float yz = zx * xy - zy * xx;

    return ocarina::float4x4{
        make_float4(xx, xy, xz, 0.f),
        make_float4(yx, yy, yz, 0.f),
        make_float4(zx, zy, zz, 0.f),
        make_float4(camera.position.x, camera.position.y, camera.position.z, 1.f)};
}

}  // namespace

void sync_vision_camera(::vision::Pipeline& pipeline, const CameraDevice& camera) {
    auto& sensor = pipeline.scene().sensor();
    const auto requested_resolution = make_uint2(std::max(camera.width, 1u), std::max(camera.height, 1u));
    const auto camera_to_world = make_camera_to_world(camera);

    bool invalidate = false;
    if (any(pipeline.resolution() != requested_resolution)) {
        pipeline.change_resolution(requested_resolution);
        invalidate = true;
    }
    if (!nearly_equal(sensor.fov_y(), camera.fov) || !matrix_equal(sensor.host_c2w(), camera_to_world)) {
        invalidate = true;
    }

    sensor.set_mat(camera_to_world);
    sensor.set_fov_y(camera.fov);
    sensor.update_device_data();

    if (invalidate) {
        pipeline.invalidate();
    }
}

}  // namespace Corona::Systems::Vision

#endif  // CORONA_ENABLE_VISION