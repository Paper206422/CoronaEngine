#include "cursor_3d_manager.h"

#include "cursor_3d_math.h"

#include <corona/kernel/core/i_logger.h>
#include <corona/shared_data_hub.h>

#include <algorithm>
#include <cmath>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

namespace Corona::Systems::UI {

namespace {

constexpr float kEpsilon = 1.0e-6f;

struct CursorState {
    bool active{false};
    SDL_Window* window{nullptr};
    SDL_WindowID window_id{0};
    std::uintptr_t camera_handle{0};
    std::uintptr_t actor_handle{0};
    std::string scene_id;
    Vec3 center{};
    float radius{1.0f};
    float scale{0.1f};
    double viewport_x{0.0};
    double viewport_y{0.0};
    double viewport_width{1.0};
    double viewport_height{1.0};
    double virtual_x{0.0};
    double virtual_y{0.0};
    Vec3 cursor_position{};
    Vec3 cursor_normal{0.0f, 0.0f, 1.0f};
};

std::mutex s_mutex;
CursorState s_state;

ktm::fvec3 make_fvec3(const Vec3& value) {
    ktm::fvec3 out;
    out[0] = value.x;
    out[1] = value.y;
    out[2] = value.z;
    return out;
}

Vec3 from_fvec3(const ktm::fvec3& value) {
    return {value[0], value[1], value[2]};
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

float length(Vec3 v) {
    return std::sqrt(dot(v, v));
}

float clamp_float(float value, float min_value, float max_value) {
    return std::max(min_value, std::min(max_value, value));
}

double clamp_double(double value, double min_value, double max_value) {
    return std::max(min_value, std::min(max_value, value));
}

Vec3 normalize(Vec3 v, Vec3 fallback = {0.0f, 0.0f, 1.0f}) {
    const float len = length(v);
    if (len <= kEpsilon || !std::isfinite(len)) {
        return fallback;
    }
    return mul(v, 1.0f / len);
}

std::vector<std::uintptr_t> resolve_profile_handles(std::uintptr_t actor_handle) {
    std::vector<std::uintptr_t> profile_handles;
    if (auto actor = Corona::SharedDataHub::instance().actor_storage().try_acquire_read_nowait(actor_handle)) {
        profile_handles = actor->profile_handles;
    }
    return profile_handles;
}

void append_geometry_handle(std::vector<std::uintptr_t>& handles, std::uintptr_t geometry_handle) {
    if (geometry_handle == 0) {
        return;
    }
    if (std::find(handles.begin(), handles.end(), geometry_handle) == handles.end()) {
        handles.push_back(geometry_handle);
    }
}

std::vector<std::uintptr_t> resolve_geometry_handles(std::uintptr_t actor_handle) {
    std::vector<std::uintptr_t> geometry_handles;
    auto& hub = Corona::SharedDataHub::instance();
    for (const auto profile_handle : resolve_profile_handles(actor_handle)) {
        std::uintptr_t mechanics_handle = 0;
        std::uintptr_t optics_handle = 0;
        std::uintptr_t acoustics_handle = 0;
        if (auto profile = hub.profile_storage().try_acquire_read_nowait(profile_handle)) {
            append_geometry_handle(geometry_handles, profile->geometry_handle);
            mechanics_handle = profile->mechanics_handle;
            optics_handle = profile->optics_handle;
            acoustics_handle = profile->acoustics_handle;
        }
        if (auto mechanics = hub.mechanics_storage().try_acquire_read_nowait(mechanics_handle)) {
            append_geometry_handle(geometry_handles, mechanics->geometry_handle);
        }
        if (auto optics = hub.optics_storage().try_acquire_read_nowait(optics_handle)) {
            append_geometry_handle(geometry_handles, optics->geometry_handle);
        }
        if (auto acoustics = hub.acoustics_storage().try_acquire_read_nowait(acoustics_handle)) {
            append_geometry_handle(geometry_handles, acoustics->geometry_handle);
        }
    }
    return geometry_handles;
}

void set_actor_visible(std::uintptr_t actor_handle, bool visible) {
    auto& hub = Corona::SharedDataHub::instance();
    for (const auto profile_handle : resolve_profile_handles(actor_handle)) {
        if (auto profile = hub.profile_storage().try_acquire_read_nowait(profile_handle)) {
            if (profile->optics_handle != 0) {
                if (auto optics = hub.optics_storage().try_acquire_write(profile->optics_handle)) {
                    optics->visible = visible;
                }
            }
        }
    }
}

void disable_actor_physics(std::uintptr_t actor_handle) {
    auto& hub = Corona::SharedDataHub::instance();
    for (const auto profile_handle : resolve_profile_handles(actor_handle)) {
        if (auto profile = hub.profile_storage().try_acquire_read_nowait(profile_handle)) {
            if (profile->mechanics_handle != 0) {
                if (auto mechanics = hub.mechanics_storage().try_acquire_write(profile->mechanics_handle)) {
                    mechanics->physics_enabled = false;
                    mechanics->bEnableCollision = false;
                }
            }
        }
    }
}

Vec3 look_at_euler(Vec3 position, Vec3 target) {
    const Vec3 direction = normalize(sub(target, position), {0.0f, 0.0f, 1.0f});
    const float yaw = std::atan2(direction.x, direction.z);
    const float pitch = -std::asin(clamp_float(direction.y, -1.0f, 1.0f));
    return {pitch, yaw, 0.0f};
}

bool write_cursor_transform(const CursorState& state) {
    const Vec3 rotation = look_at_euler(state.cursor_position, state.center);
    const Vec3 scale{state.scale, state.scale, state.scale};

    bool wrote = false;
    auto& hub = Corona::SharedDataHub::instance();
    for (const auto geometry_handle : resolve_geometry_handles(state.actor_handle)) {
        auto geometry = hub.geometry_storage().try_acquire_read_nowait(geometry_handle);
        if (!geometry || geometry->transform_handle == 0) {
            continue;
        }
        if (auto transform = hub.model_transform_storage().try_acquire_write(geometry->transform_handle)) {
            transform->position = make_fvec3(state.cursor_position);
            transform->euler_rotation = make_fvec3(rotation);
            transform->scale = make_fvec3(scale);
            wrote = true;
        }
    }
    return wrote;
}

bool read_camera_snapshot(const CursorState& state, CursorRaySurfaceCamera& out) {
    if (auto camera = Corona::SharedDataHub::instance().camera_storage().try_acquire_read_nowait(
            state.camera_handle)) {
        out.position = from_fvec3(camera->position);
        out.forward = from_fvec3(camera->forward);
        out.up = from_fvec3(camera->world_up);
        out.fov_degrees = camera->fov;
        out.viewport_width = state.viewport_width;
        out.viewport_height = state.viewport_height;
        return true;
    }
    return false;
}

bool compute_scene_anchor(std::uintptr_t camera_handle, Vec3& center, float& radius) {
    auto& hub = Corona::SharedDataHub::instance();
    for (const auto& scene : hub.scene_storage()) {
        if (std::find(scene.camera_handles.begin(),
                      scene.camera_handles.end(),
                      camera_handle) == scene.camera_handles.end()) {
            continue;
        }
        center = from_fvec3(scene.center_world);
        const Vec3 min_world = from_fvec3(scene.min_world);
        const Vec3 max_world = from_fvec3(scene.max_world);
        const Vec3 diagonal = sub(max_world, min_world);
        const float diagonal_len = length(diagonal);
        radius = std::max(diagonal_len * 0.5f, 1.0f);
        if (!std::isfinite(radius)) {
            radius = 1.0f;
            center = {};
        }
        return true;
    }

    center = {};
    radius = 1.0f;
    return false;
}

bool update_cursor_surface_locked() {
    Vec3 scene_center{};
    compute_scene_anchor(s_state.camera_handle, scene_center, s_state.radius);
    s_state.scale = clamp_float(s_state.radius * 0.035f, 0.05f, 0.5f);

    CursorRaySurfaceCamera camera;
    if (!read_camera_snapshot(s_state, camera)) {
        return false;
    }
    s_state.center = compute_camera_look_at_anchor(camera, scene_center, s_state.radius);

    const auto result = compute_cursor_ray_surface({
        .camera = camera,
        .center = s_state.center,
        .base_radius = s_state.radius,
        .x = s_state.virtual_x,
        .y = s_state.virtual_y,
    });
    if (!result.hit) {
        return false;
    }

    s_state.cursor_position = result.position;
    s_state.cursor_normal = result.normal;
    return write_cursor_transform(s_state);
}

void apply_mouse_capture(SDL_Window* window, bool enabled) {
    if (!window) {
        return;
    }
    if (enabled) {
        SDL_SetWindowMouseGrab(window, true);
        SDL_CaptureMouse(true);
        SDL_SetWindowRelativeMouseMode(window, true);
        SDL_HideCursor();
    } else {
        SDL_SetWindowRelativeMouseMode(window, false);
        SDL_CaptureMouse(false);
        SDL_SetWindowMouseGrab(window, false);
        SDL_ShowCursor();
    }
}

void disable_locked() {
    if (!s_state.active) {
        return;
    }
    const std::uintptr_t actor_handle = s_state.actor_handle;
    SDL_Window* window = s_state.window;
    s_state = {};
    apply_mouse_capture(window, false);
    set_actor_visible(actor_handle, false);
}

}  // namespace

Cursor3DManager& Cursor3DManager::instance() {
    static Cursor3DManager manager;
    return manager;
}

bool Cursor3DManager::set_mode(SDL_Window* window,
                               std::uintptr_t camera_handle,
                               std::string scene_id,
                               std::uintptr_t cursor_actor_handle,
                               bool enabled,
                               double viewport_x,
                               double viewport_y,
                               double viewport_width,
                               double viewport_height,
                               double start_x,
                               double start_y) {
    std::lock_guard<std::mutex> lock(s_mutex);
    if (!enabled) {
        disable_locked();
        return true;
    }

    if (!window || camera_handle == 0 || cursor_actor_handle == 0 ||
        viewport_width <= 0.0 || viewport_height <= 0.0) {
        CFW_LOG_WARNING("3D cursor enable skipped: invalid window/camera/actor/viewport");
        disable_locked();
        return false;
    }

    if (s_state.active && s_state.actor_handle != cursor_actor_handle) {
        set_actor_visible(s_state.actor_handle, false);
    }

    s_state.active = true;
    s_state.window = window;
    s_state.window_id = SDL_GetWindowID(window);
    s_state.camera_handle = camera_handle;
    s_state.actor_handle = cursor_actor_handle;
    s_state.scene_id = std::move(scene_id);
    s_state.viewport_x = viewport_x;
    s_state.viewport_y = viewport_y;
    s_state.viewport_width = viewport_width;
    s_state.viewport_height = viewport_height;
    s_state.virtual_x = clamp_double(start_x, 0.0, viewport_width);
    s_state.virtual_y = clamp_double(start_y, 0.0, viewport_height);

    disable_actor_physics(s_state.actor_handle);
    set_actor_visible(s_state.actor_handle, true);
    if (!update_cursor_surface_locked()) {
        CFW_LOG_WARNING("3D cursor enable skipped: failed to compute cursor surface point");
        disable_locked();
        return false;
    }
    apply_mouse_capture(window, true);
    return true;
}

bool Cursor3DManager::handle_mouse_motion(const SDL_Event& event) {
    std::lock_guard<std::mutex> lock(s_mutex);
    if (!s_state.active || event.type != SDL_EVENT_MOUSE_MOTION) {
        return false;
    }
    if (s_state.window_id != 0 && event.motion.windowID != 0 &&
        event.motion.windowID != s_state.window_id) {
        return false;
    }

    const float dx = event.motion.xrel;
    const float dy = event.motion.yrel;
    if (dx == 0.0f && dy == 0.0f) {
        return true;
    }

    s_state.virtual_x = clamp_double(s_state.virtual_x + static_cast<double>(dx),
                                     0.0,
                                     s_state.viewport_width);
    s_state.virtual_y = clamp_double(s_state.virtual_y + static_cast<double>(dy),
                                     0.0,
                                     s_state.viewport_height);

    if (!update_cursor_surface_locked()) {
        disable_locked();
    }
    return true;
}

void Cursor3DManager::handle_window_focus_lost(SDL_Window* window, SDL_WindowID window_id) {
    std::lock_guard<std::mutex> lock(s_mutex);
    if (!s_state.active) {
        return;
    }
    if ((window && s_state.window == window) ||
        (window_id != 0 && s_state.window_id == window_id)) {
        disable_locked();
    }
}

void Cursor3DManager::force_disable() {
    std::lock_guard<std::mutex> lock(s_mutex);
    disable_locked();
}

}  // namespace Corona::Systems::UI
