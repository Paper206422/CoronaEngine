#include "cef_bridge_helpers.h"

#include <corona/kernel/core/i_logger.h>
#include <corona/shared_data_hub.h>
#include <include/cef_values.h>

#include <algorithm>
#include <vector>

namespace Corona::Systems::UI {

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