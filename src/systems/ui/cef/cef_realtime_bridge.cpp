#include "cef_bridge_helpers.h"

#include <corona/kernel/core/i_logger.h>
#include <corona/shared_data_hub.h>
#include <include/cef_values.h>

#include <algorithm>
#include <mutex>
#include <string>
#include <vector>

namespace Corona::Systems::UI {

namespace {

static std::mutex s_input_mutex;
static std::vector<InputEvent> s_input_queue;

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

    if (auto accessor = Corona::SharedDataHub::instance().camera_storage().try_acquire_write_nowait(camera_handle)) {
        accessor->position = position;
        accessor->forward = forward;
        accessor->world_up = world_up;
        accessor->fov = fov;
    }

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
        if (!scene->camera_handles.empty()) {
            camera_handle = scene->camera_handles[0];  // First camera = active
        }
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

}  // namespace

bool handle_realtime_process_message(const CefRefPtr<CefProcessMessage>& message) {
    if (!message) {
        return false;
    }

    if (message->GetName() == "CameraMoveFast") {
        return handle_camera_move_fast(message);
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