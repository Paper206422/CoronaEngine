#include "cef_bridge_helpers.h"

#include <corona/kernel/core/i_logger.h>
#include <corona/resource/resource_manager.h>
#include <corona/resource/types/scene.h>
#include <corona/shared_data_hub.h>
#include <include/cef_values.h>
#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

#include "browser_manager.h"
#include "cef_client.h"

namespace Corona::Systems::UI {

namespace {

static std::mutex s_input_mutex;
static std::vector<InputEvent> s_input_queue;

[[nodiscard]] std::uintptr_t select_scene_camera_handle(const Corona::SceneDevice& scene) {
    if (scene.active_camera_handle != 0 &&
        std::find(scene.camera_handles.begin(),
                  scene.camera_handles.end(),
                  scene.active_camera_handle) != scene.camera_handles.end()) {
        return scene.active_camera_handle;
    }
    return scene.camera_handles.empty() ? 0 : scene.camera_handles.front();
}

[[nodiscard]] ktm::fvec3 make_fvec3(float x, float y, float z) {
    ktm::fvec3 value;
    value[0] = x;
    value[1] = y;
    value[2] = z;
    return value;
}

[[nodiscard]] ktm::fvec4 make_fvec4(float x, float y, float z, float w) {
    ktm::fvec4 value;
    value[0] = x;
    value[1] = y;
    value[2] = z;
    value[3] = w;
    return value;
}

[[nodiscard]] ktm::fvec3 transform_local_point_to_world(const ktm::fmat4x4& matrix,
                                                        const ktm::fvec3& local_point) {
    const ktm::fvec4 local_h = make_fvec4(local_point[0], local_point[1], local_point[2], 1.0f);
    const ktm::fvec4 world_h = matrix * local_h;
    return make_fvec3(world_h[0], world_h[1], world_h[2]);
}

}  // namespace (input queue)

// ── drain_input_events: 消费所有积攒的输入事件 ──
// 开放给 ScriptSystem 调用（通过头文件声明），每帧由 Python show_log_on_js 消费
std::vector<InputEvent> drain_input_events() {
    std::lock_guard<std::mutex> lock(s_input_mutex);
    std::vector<InputEvent> events;
    events.swap(s_input_queue);
    return events;
}

namespace {

bool parse_vec3_list(const CefRefPtr<CefListValue>& list, ktm::fvec3& out) {
    if (!list || list->GetSize() != 3) {
        return false;
    }

    auto read_value = [list](size_t index, float& value) -> bool {
        const auto type = list->GetType(index);
        if (type == VTYPE_INT) {
            value = static_cast<float>(list->GetInt(index));
            return true;
        }
        if (type == VTYPE_DOUBLE) {
            value = static_cast<float>(list->GetDouble(index));
            return true;
        }
        return false;
    };

    return read_value(0, out[0]) && read_value(1, out[1]) && read_value(2, out[2]);
}

bool handle_camera_move_fast(const CefRefPtr<CefProcessMessage>& message) {
    auto args = message->GetArgumentList();
    if (!args || args->GetSize() < 5) {
        return true;
    }

    const auto handle_type = args->GetType(0);
    if (handle_type != VTYPE_INT && handle_type != VTYPE_DOUBLE) {
        return true;
    }

    const auto handle_value =
        handle_type == VTYPE_INT ? static_cast<double>(args->GetInt(0)) : args->GetDouble(0);
    const auto camera_handle = static_cast<std::uintptr_t>(handle_value);
    if (camera_handle == 0) {
        return true;
    }

    ktm::fvec3 position{};
    ktm::fvec3 forward{};
    ktm::fvec3 world_up{};
    if (!parse_vec3_list(args->GetList(1), position) ||
        !parse_vec3_list(args->GetList(2), forward) ||
        !parse_vec3_list(args->GetList(3), world_up)) {
        return true;
    }

    float fov = 45.0f;
    const auto fov_type = args->GetType(4);
    if (fov_type == VTYPE_INT) {
        fov = static_cast<float>(args->GetInt(4));
    } else if (fov_type == VTYPE_DOUBLE) {
        fov = static_cast<float>(args->GetDouble(4));
    }

    Corona::CameraMoveCommand move;
    move.camera_handle = camera_handle;
    move.position = position;
    move.forward = forward;
    move.world_up = world_up;
    move.fov = fov;
    Corona::SharedDataHub::instance().enqueue_camera_move(move);

    return true;
}

void append_geometry_handle(std::vector<std::uintptr_t>& handles, std::uintptr_t geometry_handle) {
    if (geometry_handle == 0) {
        return;
    }
    if (std::find(handles.begin(), handles.end(), geometry_handle) == handles.end()) {
        handles.push_back(geometry_handle);
    }
}

std::vector<std::uintptr_t> resolve_profile_handles(std::uintptr_t actor_handle) {
    std::vector<std::uintptr_t> profile_handles;
    if (auto actor = Corona::SharedDataHub::instance().actor_storage().try_acquire_read(actor_handle)) {
        profile_handles = actor->profile_handles;
    }
    return profile_handles;
}

std::vector<std::uintptr_t> resolve_actor_geometry_handles(std::uintptr_t actor_handle) {
    std::vector<std::uintptr_t> profile_handles;
    if (auto actor = Corona::SharedDataHub::instance().actor_storage().try_acquire_read(actor_handle)) {
        profile_handles = actor->profile_handles;
    }

    std::vector<std::uintptr_t> geometry_handles;
    auto& hub = Corona::SharedDataHub::instance();
    for (const auto profile_handle : profile_handles) {
        if (auto profile = hub.profile_storage().try_acquire_read(profile_handle)) {
            append_geometry_handle(geometry_handles, profile->geometry_handle);
            if (auto mechanics = hub.mechanics_storage().try_acquire_read(profile->mechanics_handle)) {
                append_geometry_handle(geometry_handles, mechanics->geometry_handle);
            }
            if (auto optics = hub.optics_storage().try_acquire_read(profile->optics_handle)) {
                append_geometry_handle(geometry_handles, optics->geometry_handle);
            }
            if (auto acoustics = hub.acoustics_storage().try_acquire_read(profile->acoustics_handle)) {
                append_geometry_handle(geometry_handles, acoustics->geometry_handle);
            }
        }
    }

    return geometry_handles;
}

struct FocusBounds {
    ktm::fvec3 min{};
    ktm::fvec3 max{};
    bool valid{false};
};

struct FocusGeometrySource {
    std::uintptr_t geometry_handle{};
    bool has_local_bounds{false};
    ktm::fvec3 local_min{};
    ktm::fvec3 local_max{};
};

void append_focus_geometry_source(std::vector<FocusGeometrySource>& sources,
                                  std::uintptr_t geometry_handle,
                                  bool has_local_bounds,
                                  const ktm::fvec3& local_min,
                                  const ktm::fvec3& local_max) {
    if (geometry_handle == 0) {
        return;
    }

    for (auto& source : sources) {
        if (source.geometry_handle != geometry_handle) {
            continue;
        }
        if (!source.has_local_bounds && has_local_bounds) {
            source.has_local_bounds = true;
            source.local_min = local_min;
            source.local_max = local_max;
        }
        return;
    }

    FocusGeometrySource source;
    source.geometry_handle = geometry_handle;
    source.has_local_bounds = has_local_bounds;
    source.local_min = local_min;
    source.local_max = local_max;
    sources.push_back(source);
}

std::vector<FocusGeometrySource> resolve_actor_focus_geometry_sources(std::uintptr_t actor_handle) {
    std::vector<std::uintptr_t> profile_handles;
    if (auto actor = Corona::SharedDataHub::instance().actor_storage().try_acquire_read_nowait(actor_handle)) {
        profile_handles = actor->profile_handles;
    }

    std::vector<FocusGeometrySource> sources;
    auto& hub = Corona::SharedDataHub::instance();
    const ktm::fvec3 zero = make_fvec3(0.0f, 0.0f, 0.0f);

    for (const auto profile_handle : profile_handles) {
        if (auto profile = hub.profile_storage().try_acquire_read_nowait(profile_handle)) {
            append_focus_geometry_source(sources, profile->geometry_handle, false, zero, zero);

            if (auto mechanics = hub.mechanics_storage().try_acquire_read_nowait(profile->mechanics_handle)) {
                append_focus_geometry_source(sources,
                                             mechanics->geometry_handle,
                                             true,
                                             mechanics->min_xyz,
                                             mechanics->max_xyz);
            }
            if (auto optics = hub.optics_storage().try_acquire_read_nowait(profile->optics_handle)) {
                append_focus_geometry_source(sources, optics->geometry_handle, false, zero, zero);
            }
            if (auto acoustics = hub.acoustics_storage().try_acquire_read_nowait(profile->acoustics_handle)) {
                append_focus_geometry_source(sources, acoustics->geometry_handle, false, zero, zero);
            }
        }
    }

    return sources;
}

void expand_focus_bounds(FocusBounds& bounds, const ktm::fvec3& point) {
    if (!bounds.valid) {
        bounds.min = point;
        bounds.max = point;
        bounds.valid = true;
        return;
    }

    bounds.min[0] = std::min(bounds.min[0], point[0]);
    bounds.min[1] = std::min(bounds.min[1], point[1]);
    bounds.min[2] = std::min(bounds.min[2], point[2]);
    bounds.max[0] = std::max(bounds.max[0], point[0]);
    bounds.max[1] = std::max(bounds.max[1], point[1]);
    bounds.max[2] = std::max(bounds.max[2], point[2]);
}

bool append_geometry_focus_bounds(const FocusGeometrySource& source, FocusBounds& bounds) {
    auto& hub = Corona::SharedDataHub::instance();
    std::uintptr_t transform_handle = 0;
    std::uintptr_t model_resource_handle = 0;
    if (auto geometry = hub.geometry_storage().try_acquire_read_nowait(source.geometry_handle)) {
        transform_handle = geometry->transform_handle;
        model_resource_handle = geometry->model_resource_handle;
    }

    if (transform_handle == 0) {
        return false;
    }

    ktm::fvec3 local_min{};
    ktm::fvec3 local_max{};
    if (source.has_local_bounds) {
        local_min = source.local_min;
        local_max = source.local_max;
    } else {
        if (model_resource_handle == 0) {
            return false;
        }

        std::uint64_t model_id = 0;
        if (auto resource = hub.model_resource_storage().try_acquire_read_nowait(model_resource_handle)) {
            model_id = resource->model_id;
        }
        if (model_id == 0) {
            return false;
        }

        auto scene_resource =
            Corona::Resource::ResourceManager::get_instance()
                .acquire_read<Corona::Resource::Scene>(model_id);
        if (!scene_resource) {
            return false;
        }

        const auto aabb = scene_resource->get_scene_aabb();
        local_min = make_fvec3(aabb.min[0], aabb.min[1], aabb.min[2]);
        local_max = make_fvec3(aabb.max[0], aabb.max[1], aabb.max[2]);
    }

    auto transform = hub.model_transform_storage().try_acquire_read_nowait(transform_handle);
    if (!transform) {
        return false;
    }

    const ktm::fvec3 corners[8] = {
        make_fvec3(local_min[0], local_min[1], local_min[2]),
        make_fvec3(local_max[0], local_min[1], local_min[2]),
        make_fvec3(local_min[0], local_max[1], local_min[2]),
        make_fvec3(local_max[0], local_max[1], local_min[2]),
        make_fvec3(local_min[0], local_min[1], local_max[2]),
        make_fvec3(local_max[0], local_min[1], local_max[2]),
        make_fvec3(local_min[0], local_max[1], local_max[2]),
        make_fvec3(local_max[0], local_max[1], local_max[2]),
    };

    const ktm::fmat4x4 matrix = transform->compute_matrix();
    for (const auto& corner : corners) {
        expand_focus_bounds(bounds, transform_local_point_to_world(matrix, corner));
    }

    return true;
}

void send_focus_pose_result(const CefRefPtr<CefFrame>& frame,
                            const std::string& request_id,
                            const nlohmann::json& payload) {
    if (!frame || request_id.empty()) {
        return;
    }

    const std::string js = "window.__coronaFocusPoseResult&&window.__coronaFocusPoseResult(" +
                           nlohmann::json(request_id).dump() + "," + payload.dump() + ")";
    frame->ExecuteJavaScript(js, "", 0);
}

bool get_numeric_arg(const CefRefPtr<CefListValue>& args, size_t index, double& out) {
    if (!args || index >= args->GetSize()) {
        return false;
    }

    const auto type = args->GetType(index);
    if (type == VTYPE_INT) {
        out = static_cast<double>(args->GetInt(index));
        return true;
    }
    if (type == VTYPE_DOUBLE) {
        out = args->GetDouble(index);
        return true;
    }
    return false;
}

bool handle_compute_actor_focus_pose_fast(const CefRefPtr<CefFrame>& frame,
                                          const CefRefPtr<CefProcessMessage>& message) {
    auto args = message->GetArgumentList();
    if (!args || args->GetSize() < 2 || args->GetType(1) != VTYPE_STRING) {
        return true;
    }

    const std::string request_id = args->GetString(1).ToString();
    auto fail = [&](const std::string& message_text) {
        nlohmann::json payload;
        payload["status"] = "error";
        payload["message"] = message_text;
        send_focus_pose_result(frame, request_id, payload);
        return true;
    };

    double actor_handle_value = 0.0;
    if (!get_numeric_arg(args, 0, actor_handle_value)) {
        return fail("actor handle is invalid");
    }

    const auto actor_handle = static_cast<std::uintptr_t>(actor_handle_value);
    if (actor_handle == 0) {
        return fail("actor handle is empty");
    }

    FocusBounds bounds;
    for (const auto& source : resolve_actor_focus_geometry_sources(actor_handle)) {
        append_geometry_focus_bounds(source, bounds);
    }

    if (!bounds.valid) {
        return fail("actor bounds are unavailable");
    }

    const ktm::fvec3 center = make_fvec3(
        (bounds.min[0] + bounds.max[0]) * 0.5f,
        (bounds.min[1] + bounds.max[1]) * 0.5f,
        (bounds.min[2] + bounds.max[2]) * 0.5f);
    const float dx = bounds.max[0] - bounds.min[0];
    const float dy = bounds.max[1] - bounds.min[1];
    const float dz = bounds.max[2] - bounds.min[2];
    const float diagonal = std::sqrt(dx * dx + dy * dy + dz * dz);
    const float distance = std::max(diagonal * 2.0f, 1.0f);

    nlohmann::json payload;
    payload["status"] = "success";
    payload["position"] = {center[0], center[1], center[2] - distance};
    payload["forward"] = {0.0f, 0.0f, 1.0f};
    payload["up"] = {0.0f, 1.0f, 0.0f};
    payload["center"] = {center[0], center[1], center[2]};
    payload["distance"] = distance;
    send_focus_pose_result(frame, request_id, payload);
    return true;
}

bool handle_actor_transform_fast(const CefRefPtr<CefProcessMessage>& message) {
    auto args = message->GetArgumentList();
    if (!args || args->GetSize() < 3) {
        CFW_LOG_WARNING("ActorTransformFast dropped: expected 3 args");
        return true;
    }

    const auto handle_type = args->GetType(0);
    if (handle_type != VTYPE_INT && handle_type != VTYPE_DOUBLE) {
        CFW_LOG_WARNING("ActorTransformFast dropped: actor handle type is invalid");
        return true;
    }

    const auto handle_value =
        handle_type == VTYPE_INT ? static_cast<double>(args->GetInt(0)) : args->GetDouble(0);
    const auto actor_handle = static_cast<std::uintptr_t>(handle_value);
    if (actor_handle == 0 || args->GetType(1) != VTYPE_INT) {
        CFW_LOG_WARNING("ActorTransformFast dropped: actor handle={}, operation type={}", actor_handle, static_cast<int>(args->GetType(1)));
        return true;
    }

    ktm::fvec3 value{};
    if (!parse_vec3_list(args->GetList(2), value)) {
        CFW_LOG_WARNING("ActorTransformFast dropped: vector is invalid for actor {}", actor_handle);
        return true;
    }

    const auto operation = args->GetInt(1);
    auto& hub = Corona::SharedDataHub::instance();
    for (const auto geometry_handle : resolve_actor_geometry_handles(actor_handle)) {
        auto geometry = hub.geometry_storage().try_acquire_read(geometry_handle);
        if (!geometry || geometry->transform_handle == 0) {
            continue;
        }
        if (auto transform = hub.model_transform_storage().try_acquire_write(geometry->transform_handle)) {
            switch (operation) {
                case 0:
                    transform->position = value;
                    break;
                case 1:
                    transform->euler_rotation = value;
                    break;
                case 2:
                    transform->scale = value;
                    break;
                default:
                    break;
            }
        }
    }

    return true;
}

bool handle_viewport_pick(const CefRefPtr<CefProcessMessage>& message) {
    auto args = message->GetArgumentList();
    if (!args || args->GetSize() < 5) {
        CFW_LOG_WARNING("ViewportPick dropped: expected 5 args");
        return true;
    }

    // args: [scene_handle: double, x: double, y: double, vp_width: double, vp_height: double]
    const auto read_double = [&](int index) -> double {
        const auto type = args->GetType(index);
        if (type == VTYPE_INT) return static_cast<double>(args->GetInt(index));
        if (type == VTYPE_DOUBLE) return args->GetDouble(index);
        return 0.0;
    };

    const auto scene_handle = static_cast<std::uintptr_t>(read_double(0));
    const double x = read_double(1);
    const double y = read_double(2);
    const double vp_w = read_double(3);
    const double vp_h = read_double(4);

    if (scene_handle == 0 || vp_w <= 0.0 || vp_h <= 0.0) {
        CFW_LOG_WARNING("ViewportPick: invalid params (scene={}, vp={}x{})", scene_handle, vp_w, vp_h);
        return true;
    }

    auto& hub = Corona::SharedDataHub::instance();

    // Get the scene's active camera
    std::uintptr_t camera_handle = 0;
    if (auto scene = hub.scene_storage().try_acquire_read(scene_handle)) {
        camera_handle = select_scene_camera_handle(*scene);
    }
    if (camera_handle == 0) {
        CFW_LOG_WARNING("ViewportPick: no camera found for scene {}", scene_handle);
        return true;
    }

    // Read camera dimensions for coordinate scaling
    float cam_w = 1920.0f;
    float cam_h = 1080.0f;
    if (auto cam = hub.camera_storage().try_acquire_read(camera_handle)) {
        cam_w = static_cast<float>(cam->width);
        cam_h = static_cast<float>(cam->height);
    }

    int pick_x = static_cast<int>(x * cam_w / vp_w);
    int pick_y = static_cast<int>(y * cam_h / vp_h);

    // Call the pick API via SharedDataHub
    std::uintptr_t picked_actor = 0;
    if (auto cam = hub.camera_storage().try_acquire_read(camera_handle)) {
        std::uintptr_t actor_pick_handle = cam->actor_pick_handle;
        if (actor_pick_handle != 0) {
            auto pick = hub.actor_pick_storage().try_acquire_write(actor_pick_handle);
            if (pick) {
                const auto ux = static_cast<std::uint32_t>(pick_x);
                const auto uy = static_cast<std::uint32_t>(pick_y);
                picked_actor = (pick->result_ready && pick->result_x == ux && pick->result_y == uy)
                                   ? pick->actor_handle
                                   : 0;
                pick->x = ux;
                pick->y = uy;
                pick->pending = true;
                pick->result_ready = false;
            }
        }
    }

    // Result will be emitted to Vue via __coronaEmit by the actor pick system
    // For now, the Python fallback path still handles the JS notification
    (void)picked_actor;
    CFW_LOG_DEBUG("ViewportPick: scene={} pos=({},{}) -> cam_px=({},{}) -> handle=0x{:x}",
                  scene_handle, x, y, pick_x, pick_y, picked_actor);

    return true;
}

bool handle_property_fast(const CefRefPtr<CefProcessMessage>& message) {
    auto args = message->GetArgumentList();
    if (!args || args->GetSize() < 3) {
        CFW_LOG_WARNING("PropertyFast dropped: expected 3 args");
        return true;
    }

    const auto handle_type = args->GetType(0);
    if (handle_type != VTYPE_INT && handle_type != VTYPE_DOUBLE) {
        CFW_LOG_WARNING("PropertyFast dropped: actor handle type is invalid");
        return true;
    }

    const auto handle_value =
        handle_type == VTYPE_INT ? static_cast<double>(args->GetInt(0)) : args->GetDouble(0);
    const auto actor_handle = static_cast<std::uintptr_t>(handle_value);
    if (actor_handle == 0 || args->GetType(1) != VTYPE_INT) {
        CFW_LOG_WARNING("PropertyFast dropped: actor handle={}, propertyType type={}",
                        actor_handle, static_cast<int>(args->GetType(1)));
        return true;
    }

    const auto property_type = args->GetInt(1);
    double value = 0.0;
    const auto value_type = args->GetType(2);
    if (value_type == VTYPE_INT) {
        value = static_cast<double>(args->GetInt(2));
    } else if (value_type == VTYPE_DOUBLE) {
        value = args->GetDouble(2);
    } else {
        CFW_LOG_WARNING("PropertyFast dropped: value type is invalid");
        return true;
    }

    auto& hub = Corona::SharedDataHub::instance();
    for (const auto profile_handle : resolve_profile_handles(actor_handle)) {
        auto profile = hub.profile_storage().try_acquire_read(profile_handle);
        if (!profile) continue;

        switch (property_type) {
            case 0:  // Mass
                if (profile->mechanics_handle != 0) {
                    if (auto mech = hub.mechanics_storage().try_acquire_write(profile->mechanics_handle)) {
                        mech->mass = static_cast<float>(value);
                    }
                }
                break;
            case 1:  // Restitution
                if (profile->mechanics_handle != 0) {
                    if (auto mech = hub.mechanics_storage().try_acquire_write(profile->mechanics_handle)) {
                        mech->restitution = static_cast<float>(value);
                    }
                }
                break;
            case 2:  // Damping
                if (profile->mechanics_handle != 0) {
                    if (auto mech = hub.mechanics_storage().try_acquire_write(profile->mechanics_handle)) {
                        mech->damping = static_cast<float>(value);
                    }
                }
                break;
            case 3:  // Visible
                if (profile->optics_handle != 0) {
                    if (auto opt = hub.optics_storage().try_acquire_write(profile->optics_handle)) {
                        opt->visible = (value != 0.0);
                    }
                }
                break;
            case 4:  // CollisionEnabled
                if (profile->mechanics_handle != 0) {
                    if (auto mech = hub.mechanics_storage().try_acquire_write(profile->mechanics_handle)) {
                        mech->bEnableCollision = (value != 0.0);
                    }
                }
                break;
            case 5:  // PhysicsEnabled
                if (profile->mechanics_handle != 0) {
                    if (auto mech = hub.mechanics_storage().try_acquire_write(profile->mechanics_handle)) {
                        mech->physics_enabled = (value != 0.0);
                    }
                }
                break;
            case 6:  // LinearLockMask (bit0=X, bit1=Y, bit2=Z)
                if (profile->mechanics_handle != 0) {
                    if (auto mech = hub.mechanics_storage().try_acquire_write(profile->mechanics_handle)) {
                        mech->linear_lock_mask = static_cast<uint8_t>(value);
                    }
                }
                break;
            case 7:  // AngularLockMask (bit0=X, bit1=Y, bit2=Z)
                if (profile->mechanics_handle != 0) {
                    if (auto mech = hub.mechanics_storage().try_acquire_write(profile->mechanics_handle)) {
                        mech->angular_lock_mask = static_cast<uint8_t>(value);
                    }
                }
                break;
            default:
                CFW_LOG_WARNING("PropertyFast: unknown propertyType {}", property_type);
                break;
        }
    }

    return true;
}

bool handle_input_inject(const CefRefPtr<CefProcessMessage>& message) {
    auto args = message->GetArgumentList();
    if (!args || args->GetSize() < 1) {
        CFW_LOG_WARNING("InputInject dropped: expected at least 1 arg");
        return true;
    }

    InputEvent evt{};
    evt.type = args->GetInt(0);

    switch (evt.type) {
        case 0:  // keyDown(code, modifiers?, displayKey?)
            evt.arg0 = args->GetSize() > 1 ? args->GetString(1).ToString() : "";
            evt.arg1 = args->GetSize() > 2 ? args->GetString(2).ToString() : "";
            evt.arg2 = args->GetSize() > 3 ? args->GetString(3).ToString() : evt.arg0;
            break;
        case 1:  // keyUp(code, displayKey?)
            evt.arg0 = args->GetSize() > 1 ? args->GetString(1).ToString() : "";
            evt.arg1 = args->GetSize() > 2 ? args->GetString(2).ToString() : evt.arg0;
            break;
        case 2:  // mouseEvent(eventType, button?, x?, y?)
            evt.arg0 = args->GetSize() > 1 ? args->GetString(1).ToString() : "";
            evt.arg1 = args->GetSize() > 2 ? args->GetString(2).ToString() : "";
            evt.arg3 = args->GetSize() > 3 ? (args->GetType(3) == VTYPE_INT ? static_cast<double>(args->GetInt(3)) : args->GetDouble(3)) : 0.0;
            evt.arg4 = args->GetSize() > 4 ? (args->GetType(4) == VTYPE_INT ? static_cast<double>(args->GetInt(4)) : args->GetDouble(4)) : 0.0;
            break;
        default:
            CFW_LOG_WARNING("InputInject: unknown type {}", evt.type);
            return true;
    }

    {
        std::lock_guard<std::mutex> lock(s_input_mutex);
        s_input_queue.push_back(std::move(evt));
    }

    return true;
}

int find_tab_id_for_browser(const CefRefPtr<CefBrowser>& browser) {
    if (!browser) {
        return -1;
    }

    const int browser_id = browser->GetIdentifier();
    for (auto& [tab_id, tab] : BrowserManager::instance().get_tabs()) {
        if (tab->client && tab->client->GetBrowser() &&
            tab->client->GetBrowser()->GetIdentifier() == browser_id) {
            return tab_id;
        }
    }

    return -1;
}

std::string source_base_url(const CefRefPtr<CefBrowser>& browser) {
    if (!browser || !browser->GetMainFrame()) {
        return {};
    }

    std::string url = browser->GetMainFrame()->GetURL().ToString();
    const auto hash_pos = url.find('#');
    if (hash_pos != std::string::npos) {
        url = url.substr(0, hash_pos);
    }
    return url;
}

void execute_tab_javascript(BrowserTab* tab, const std::string& js) {
    if (tab && tab->client && tab->client->GetBrowser()) {
        tab->client->GetBrowser()->GetMainFrame()->ExecuteJavaScript(js, "", 0);
    }
}

void send_dock_callback(const CefRefPtr<CefFrame>& frame,
                        const std::string& request_id,
                        const nlohmann::json& error,
                        const nlohmann::json& result) {
    if (!frame || request_id.empty()) {
        return;
    }

    std::string js = "window.__dockCallback&&window.__dockCallback(" +
                     nlohmann::json(request_id).dump() + "," +
                     (error.is_null() ? "null" : error.dump()) + "," +
                     (result.is_null() ? "null" : result.dump()) + ")";
    frame->ExecuteJavaScript(js, "", 0);
}

void broadcast_dock_event(const std::string& event, const nlohmann::json& payload) {
    std::string args_js;
    if (payload.is_array()) {
        for (size_t i = 0; i < payload.size(); ++i) {
            if (i > 0) {
                args_js += ",";
            }
            args_js += payload[i].dump();
        }
        if (!args_js.empty()) {
            args_js += ",";
        }
    } else {
        args_js = payload.dump();
        args_js += ",";
    }

    args_js += "{\"_fromCross\":1}";
    std::string js = "if(window.__coronaEmit)window.__coronaEmit(" +
                     nlohmann::json(event).dump() + "," + args_js + ")";

    for (auto& [tab_id, tab] : BrowserManager::instance().get_tabs()) {
        if (!tab->minimized) {
            execute_tab_javascript(tab.get(), js);
        }
    }
}

bool handle_dock_command(CefRefPtr<CefBrowser> browser,
                         CefRefPtr<CefFrame> frame,
                         const CefRefPtr<CefProcessMessage>& message) {
    auto args = message->GetArgumentList();
    if (!args || args->GetSize() < 1 || args->GetType(0) != VTYPE_STRING) {
        return true;
    }

    std::string request_id;
    try {
        auto command = nlohmann::json::parse(args->GetString(0).ToString());
        request_id = command.value("requestId", "");
        const std::string cmd = command.value("cmd", "");
        auto& bm = BrowserManager::instance();

        if (cmd == "createPanelTab") {
            std::string panel_id = command.value("panelId", "");
            std::string route = command.value("routePath", "");
            int width = command.value("width", 400);
            int height = command.value("height", 600);

            if (!route.empty() && route[0] == '#') {
                route = route.substr(1);
            }
            std::string standalone_route = route;
            standalone_route += (standalone_route.find('?') == std::string::npos) ? "?standalone=1" : "&standalone=1";

            int tab_id = bm.create_tab(source_base_url(browser), standalone_route,
                                       "right_top", width, height, false);
            nlohmann::json result;
            result["tab_id"] = tab_id;
            result["panel_id"] = panel_id;
            send_dock_callback(frame, request_id, nullptr, result);
            return true;
        }

        if (cmd == "closeThisTab") {
            std::string panel_id = command.value("panelId", "");
            nlohmann::json result;
            result["panel_id"] = panel_id;
            send_dock_callback(frame, request_id, nullptr, result);

            nlohmann::json payload;
            payload["panelId"] = panel_id;
            broadcast_dock_event("panel-closed", payload);

            int tab_id = find_tab_id_for_browser(browser);
            if (tab_id >= 0) {
                bm.remove_tab(tab_id);
            }
            return true;
        }

        if (cmd == "closePanelTab") {
            int tab_id = command.value("tabId", -1);
            std::string panel_id = command.value("panelId", "");
            if (tab_id >= 0) {
                bm.remove_tab(tab_id);
            }

            nlohmann::json payload;
            payload["panelId"] = panel_id;
            broadcast_dock_event("panel-closed", payload);
            send_dock_callback(frame, request_id, nullptr, payload);
            return true;
        }

        if (cmd == "broadcast") {
            std::string event = command.value("event", "");
            nlohmann::json payload = command.value("payload", nlohmann::json::object());
            broadcast_dock_event(event, payload);
            send_dock_callback(frame, request_id, nullptr, event);
            return true;
        }

        if (cmd == "setDragRegions") {
            int tab_id = find_tab_id_for_browser(browser);
            if (command.contains("tabId") && command["tabId"].is_number_integer()) {
                tab_id = command.value("tabId", -1);
            }
            std::vector<DragRegion> regions;
            for (const auto& region : command.value("regions", nlohmann::json::array())) {
                regions.push_back({
                    region.value("x", 0.0f),
                    region.value("y", 0.0f),
                    region.value("w", 0.0f),
                    region.value("h", 0.0f),
                });
            }
            if (tab_id >= 0) {
                bm.set_tab_drag_regions(tab_id, regions);
            }
            nlohmann::json result;
            result["ok"] = tab_id >= 0;
            send_dock_callback(frame, request_id, nullptr, result);
            return true;
        }

        nlohmann::json error;
        error["message"] = "Unknown DockCommand: " + cmd;
        send_dock_callback(frame, request_id, error, nullptr);
        return true;
    } catch (const std::exception& e) {
        nlohmann::json error;
        error["message"] = e.what();
        send_dock_callback(frame, request_id, error, nullptr);
        return true;
    }
}

}  // namespace

bool handle_realtime_process_message(CefRefPtr<CefBrowser> browser,
                                     CefRefPtr<CefFrame> frame,
                                     const CefRefPtr<CefProcessMessage>& message) {
    if (!message) {
        return false;
    }

    if (message->GetName() == "DockCommand") {
        return handle_dock_command(browser, frame, message);
    }

    if (message->GetName() == "CameraMoveFast") {
        return handle_camera_move_fast(message);
    }

    if (message->GetName() == "ComputeActorFocusPoseFast") {
        return handle_compute_actor_focus_pose_fast(frame, message);
    }

    if (message->GetName() == "ActorTransformFast") {
        return handle_actor_transform_fast(message);
    }

    if (message->GetName() == "PropertyFast") {
        return handle_property_fast(message);
    }

    if (message->GetName() == "ViewportPick") {
        return handle_viewport_pick(message);
    }

    if (message->GetName() == "InputInject") {
        return handle_input_inject(message);
    }

    return false;
}

bool forward_process_message_to_router(const CefRefPtr<CefMessageRouterBrowserSide>& browser_side_router,
                                       CefRefPtr<CefBrowser> browser,
                                       CefRefPtr<CefFrame> frame,
                                       CefProcessId source_process,
                                       CefRefPtr<CefProcessMessage> message) {
    if (!browser_side_router) {
        return false;
    }

    return browser_side_router->OnProcessMessageReceived(browser, frame, source_process, message);
}

}  // namespace Corona::Systems::UI
