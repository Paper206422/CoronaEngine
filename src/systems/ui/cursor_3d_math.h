#pragma once

namespace Corona::Systems::UI {

struct Vec3 {
    float x{0.0f};
    float y{0.0f};
    float z{0.0f};
};

struct CursorRaySurfaceCamera {
    Vec3 position{};
    Vec3 forward{0.0f, 0.0f, 1.0f};
    Vec3 up{0.0f, 1.0f, 0.0f};
    float fov_degrees{60.0f};
    double viewport_width{1.0};
    double viewport_height{1.0};
};

struct CursorRaySurfaceInput {
    CursorRaySurfaceCamera camera{};
    Vec3 center{};
    float base_radius{1.0f};
    double x{0.0};
    double y{0.0};
};

struct CursorRaySurfaceResult {
    bool hit{false};
    bool used_fallback{false};
    Vec3 position{};
    Vec3 normal{0.0f, 0.0f, 1.0f};
    float corrected_radius{1.0f};
};

CursorRaySurfaceResult compute_cursor_ray_surface(const CursorRaySurfaceInput& input);
Vec3 compute_camera_look_at_anchor(const CursorRaySurfaceCamera& camera,
                                   Vec3 scene_center,
                                   float scene_radius);

}  // namespace Corona::Systems::UI
