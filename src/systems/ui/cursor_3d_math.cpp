#include "cursor_3d_math.h"

#include <algorithm>
#include <cmath>

namespace Corona::Systems::UI {

namespace {

constexpr float kEpsilon = 1.0e-6f;
constexpr double kPi = 3.14159265358979323846;

Vec3 add(Vec3 a, Vec3 b) {
    return {a.x + b.x, a.y + b.y, a.z + b.z};
}

Vec3 sub(Vec3 a, Vec3 b) {
    return {a.x - b.x, a.y - b.y, a.z - b.z};
}

Vec3 mul(Vec3 v, float scalar) {
    return {v.x * scalar, v.y * scalar, v.z * scalar};
}

float dot(Vec3 a, Vec3 b) {
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

Vec3 cross(Vec3 a, Vec3 b) {
    return {
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x,
    };
}

float length(Vec3 v) {
    return std::sqrt(dot(v, v));
}

bool finite(Vec3 v) {
    return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z);
}

Vec3 normalize(Vec3 v, Vec3 fallback = {0.0f, 0.0f, 1.0f}) {
    const float len = length(v);
    if (len <= kEpsilon || !std::isfinite(len)) {
        return fallback;
    }
    return mul(v, 1.0f / len);
}

}  // namespace

CursorRaySurfaceResult compute_cursor_ray_surface(const CursorRaySurfaceInput& input) {
    CursorRaySurfaceResult result;

    const double viewport_width = std::max(input.camera.viewport_width, 1.0);
    const double viewport_height = std::max(input.camera.viewport_height, 1.0);
    const float base_radius = std::max(input.base_radius, 1.0f);

    const Vec3 forward = normalize(input.camera.forward);
    Vec3 up = normalize(input.camera.up, {0.0f, 1.0f, 0.0f});
    Vec3 right = normalize(cross(up, forward), {});
    if (length(right) <= kEpsilon) {
        up = std::abs(forward.y) < 0.95f ? Vec3{0.0f, 1.0f, 0.0f} : Vec3{1.0f, 0.0f, 0.0f};
        right = normalize(cross(up, forward), {1.0f, 0.0f, 0.0f});
    }
    up = normalize(cross(forward, right), {0.0f, 1.0f, 0.0f});

    const double fov = std::clamp(static_cast<double>(input.camera.fov_degrees), 1.0, 175.0);
    const double half_tan = std::tan(fov * kPi / 360.0);
    const double aspect = viewport_width / viewport_height;
    const double nx = (std::clamp(input.x, 0.0, viewport_width) / viewport_width) * 2.0 - 1.0;
    const double sy = 1.0 - (std::clamp(input.y, 0.0, viewport_height) / viewport_height) * 2.0;

    const Vec3 ray_dir = normalize(add(forward,
                                       add(mul(right, static_cast<float>(nx * half_tan * aspect)),
                                           mul(up, static_cast<float>(sy * half_tan)))),
                                   forward);
    const float cos_theta = std::clamp(dot(ray_dir, forward), 0.0f, 1.0f);
    const float radius = std::max(base_radius * cos_theta, 1.0f);
    result.corrected_radius = radius;

    const Vec3 oc = sub(input.camera.position, input.center);
    const float b = 2.0f * dot(ray_dir, oc);
    const float c = dot(oc, oc) - radius * radius;
    const float discriminant = b * b - 4.0f * c;

    if (discriminant >= 0.0f && std::isfinite(discriminant)) {
        const float root = std::sqrt(discriminant);
        float t = (-b - root) * 0.5f;
        if (t <= kEpsilon || !std::isfinite(t)) {
            t = (-b + root) * 0.5f;
        }
        if (t > kEpsilon && std::isfinite(t)) {
            result.position = add(input.camera.position, mul(ray_dir, t));
            result.normal = normalize(sub(result.position, input.center), mul(forward, -1.0f));
            result.hit = finite(result.position) && finite(result.normal);
            return result;
        }
    }

    const float closest_t = std::max(0.0f, dot(sub(input.center, input.camera.position), ray_dir));
    const Vec3 closest = add(input.camera.position, mul(ray_dir, closest_t));
    result.normal = normalize(sub(closest, input.center), ray_dir);
    result.position = add(input.center, mul(result.normal, radius));
    result.used_fallback = true;
    result.hit = finite(result.position) && finite(result.normal);
    return result;
}

Vec3 compute_camera_look_at_anchor(const CursorRaySurfaceCamera& camera,
                                   Vec3 scene_center,
                                   float scene_radius) {
    (void)scene_center;
    const float radius = std::isfinite(scene_radius) ? std::max(scene_radius, 1.0f) : 1.0f;
    const Vec3 forward = normalize(camera.forward);
    const Vec3 anchor = add(camera.position, mul(forward, radius));
    return finite(anchor) ? anchor : camera.position;
}

}  // namespace Corona::Systems::UI
