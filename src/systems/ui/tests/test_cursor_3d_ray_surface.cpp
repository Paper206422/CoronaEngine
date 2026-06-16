#include "cursor_3d_math.h"

#include <cmath>
#include <iostream>
#include <limits>

namespace {

using Corona::Systems::UI::CursorRaySurfaceCamera;
using Corona::Systems::UI::CursorRaySurfaceInput;
using Corona::Systems::UI::Vec3;

bool nearly_equal(float actual, float expected, float epsilon = 1.0e-4f) {
    return std::abs(actual - expected) <= epsilon;
}

float length(Vec3 v) {
    return std::sqrt(v.x * v.x + v.y * v.y + v.z * v.z);
}

Vec3 sub(Vec3 a, Vec3 b) {
    return {a.x - b.x, a.y - b.y, a.z - b.z};
}

bool expect_near(const char* label, float actual, float expected, float epsilon = 1.0e-4f) {
    if (nearly_equal(actual, expected, epsilon)) {
        return true;
    }
    std::cerr << label << ": expected " << expected << ", got " << actual << '\n';
    return false;
}

bool expect_true(const char* label, bool value) {
    if (value) {
        return true;
    }
    std::cerr << label << ": expected true\n";
    return false;
}

bool finite(Vec3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

CursorRaySurfaceCamera make_camera() {
    return {
        .position = {0.0f, 0.0f, -5.0f},
        .forward = {0.0f, 0.0f, 1.0f},
        .up = {0.0f, 1.0f, 0.0f},
        .fov_degrees = 60.0f,
        .viewport_width = 1000.0,
        .viewport_height = 1000.0,
    };
}

}  // namespace

int main() {
    bool ok = true;

    const Vec3 center{0.0f, 0.0f, 0.0f};
    const auto anchor_center = Corona::Systems::UI::compute_camera_look_at_anchor(
        make_camera(),
        center,
        2.0f);
    ok &= expect_true("center anchor finite", finite(anchor_center));
    ok &= expect_near("center anchor x", anchor_center.x, 0.0f);
    ok &= expect_near("center anchor y", anchor_center.y, 0.0f);
    ok &= expect_near("center anchor z", anchor_center.z, -3.0f);

    auto offset_camera = make_camera();
    offset_camera.position = {1.0f, 0.0f, -5.0f};
    const auto anchor_offset = Corona::Systems::UI::compute_camera_look_at_anchor(
        offset_camera,
        center,
        2.0f);
    ok &= expect_true("offset anchor finite", finite(anchor_offset));
    ok &= expect_near("offset anchor x", anchor_offset.x, 1.0f);
    ok &= expect_near("offset anchor y", anchor_offset.y, 0.0f);
    ok &= expect_near("offset anchor z", anchor_offset.z, -3.0f);

    const auto anchor_min_radius = Corona::Systems::UI::compute_camera_look_at_anchor(
        make_camera(),
        center,
        0.25f);
    ok &= expect_true("min radius anchor finite", finite(anchor_min_radius));
    ok &= expect_near("min radius anchor x", anchor_min_radius.x, 0.0f);
    ok &= expect_near("min radius anchor y", anchor_min_radius.y, 0.0f);
    ok &= expect_near("min radius anchor z", anchor_min_radius.z, -4.0f);

    const auto anchor_nan_radius = Corona::Systems::UI::compute_camera_look_at_anchor(
        make_camera(),
        center,
        std::numeric_limits<float>::quiet_NaN());
    ok &= expect_true("nan radius anchor finite", finite(anchor_nan_radius));
    ok &= expect_near("nan radius anchor x", anchor_nan_radius.x, 0.0f);
    ok &= expect_near("nan radius anchor y", anchor_nan_radius.y, 0.0f);
    ok &= expect_near("nan radius anchor z", anchor_nan_radius.z, -4.0f);

    auto missed_camera = make_camera();
    missed_camera.position = {5.0f, 0.0f, -5.0f};
    const auto anchor_fallback = Corona::Systems::UI::compute_camera_look_at_anchor(
        missed_camera,
        center,
        1.0f);
    ok &= expect_true("fallback anchor finite", finite(anchor_fallback));
    ok &= expect_near("fallback anchor x", anchor_fallback.x, 5.0f);
    ok &= expect_near("fallback anchor y", anchor_fallback.y, 0.0f);
    ok &= expect_near("fallback anchor z", anchor_fallback.z, -4.0f);

    const auto center_result = Corona::Systems::UI::compute_cursor_ray_surface({
        .camera = make_camera(),
        .center = center,
        .base_radius = 2.0f,
        .x = 500.0,
        .y = 500.0,
    });
    ok &= center_result.hit;
    ok &= !center_result.used_fallback;
    ok &= expect_near("center corrected radius", center_result.corrected_radius, 2.0f);
    ok &= expect_near("center position x", center_result.position.x, 0.0f);
    ok &= expect_near("center position y", center_result.position.y, 0.0f);
    ok &= expect_near("center position z", center_result.position.z, -2.0f);
    ok &= expect_near("center normal z", center_result.normal.z, -1.0f);

    const auto edge_result = Corona::Systems::UI::compute_cursor_ray_surface({
        .camera = make_camera(),
        .center = center,
        .base_radius = 2.0f,
        .x = 1000.0,
        .y = 500.0,
    });
    ok &= edge_result.hit;
    ok &= edge_result.used_fallback;
    ok &= expect_near("edge corrected radius", edge_result.corrected_radius, 1.7320508f, 1.0e-3f);
    ok &= expect_near("edge distance to center",
                      length(sub(edge_result.position, center)),
                      edge_result.corrected_radius,
                      1.0e-3f);

    const auto repeated_edge_result = Corona::Systems::UI::compute_cursor_ray_surface({
        .camera = make_camera(),
        .center = center,
        .base_radius = 2.0f,
        .x = 1000.0,
        .y = 500.0,
    });
    ok &= expect_near("repeat position x", repeated_edge_result.position.x, edge_result.position.x);
    ok &= expect_near("repeat position y", repeated_edge_result.position.y, edge_result.position.y);
    ok &= expect_near("repeat position z", repeated_edge_result.position.z, edge_result.position.z);

    return ok ? 0 : 1;
}
