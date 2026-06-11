#include "browser_manager.h"
#include "cef_client.h"

#include <corona/events/acoustics_system_events.h>
#include <corona/kernel/core/kernel_context.h>
#include <corona/systems/network/network_system.h>

#include <cstdint>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <vector>

#include <nlohmann/json.hpp>

namespace Corona::Systems::UI {

namespace {
std::string create_success_json(const std::string& func,
                                const nlohmann::json& data) {
    nlohmann::json r;
    r["success"] = true;
    r["data"] = data;
    r["function"] = func;
    return r.dump();
}

// Resolve the NetworkSystem from the kernel's system manager.
// Returns nullptr if unavailable.
std::shared_ptr<Corona::Systems::NetworkSystem> get_network_system() {
    auto sys_mgr = Corona::Kernel::KernelContext::instance().system_manager();
    if (!sys_mgr) return nullptr;
    return std::dynamic_pointer_cast<Corona::Systems::NetworkSystem>(
        sys_mgr->get_system("Network"));
}

std::uintptr_t json_to_uintptr(const nlohmann::json& value) {
    try {
        if (value.is_string()) {
            return static_cast<std::uintptr_t>(std::stoull(value.get<std::string>()));
        }
        if (value.is_number_unsigned()) {
            return static_cast<std::uintptr_t>(value.get<uint64_t>());
        }
        if (value.is_number_integer()) {
            auto v = value.get<int64_t>();
            return v > 0 ? static_cast<std::uintptr_t>(v) : 0;
        }
    } catch (...) {
    }
    return 0;
}

Corona::Systems::NetworkSystem::SessionRole parse_network_session_role(
    const nlohmann::json& value) {
    if (!value.is_string()) {
        return Corona::Systems::NetworkSystem::SessionRole::Host;
    }
    auto role = value.get<std::string>();
    if (role == "client") {
        return Corona::Systems::NetworkSystem::SessionRole::Client;
    }
    if (role == "none") {
        return Corona::Systems::NetworkSystem::SessionRole::None;
    }
    return Corona::Systems::NetworkSystem::SessionRole::Host;
}

nlohmann::json build_network_session_info(
    const std::shared_ptr<Corona::Systems::NetworkSystem>& sys) {
    nlohmann::json payload;
    payload["ok"] = true;
    payload["active"] =
        sys->session_state() == Corona::Systems::NetworkSystem::SessionState::Active;
    payload["role"] = std::string(sys->session_role_name());
    payload["peer_count"] = static_cast<int>(sys->peer_count());
    payload["host_address"] = sys->host_address();
    payload["host_port"] = sys->host_port();
    return payload;
}
}  // namespace

BrowserSideJSHandler::~BrowserSideJSHandler() {
    PyGILState_STATE state = PyGILState_Ensure();
    Py_XDECREF(pFunc_);
    PyGILState_Release(state);
}

void BrowserSideJSHandler::initialize_python() {
    if (!Py_IsInitialized()) {
        Py_Initialize();
        PyEval_SaveThread();
    }

    PyGILState_STATE state = PyGILState_Ensure();
    PyObject* pModule = nullptr;

    try {
        PyRun_SimpleString("import sys");
        PyRun_SimpleString("import os");
        PyRun_SimpleString("sys.path.insert(0, os.path.join(os.getcwd(), 'CabbageEditor'))");

        PyObject* pName = PyUnicode_FromString("main");
        if (!pName) {
            throw std::runtime_error("Failed to create module name");
        }

        pModule = PyImport_Import(pName);
        Py_DECREF(pName);

        if (!pModule) {
            PyErr_Print();
            PyGILState_Release(state);
            throw std::runtime_error("Failed to import Python module 'main'");
        }

        PyObject* pClass = PyObject_GetAttrString(pModule, "editor");
        if (!pClass) {
            Py_DECREF(pModule);
            PyErr_Print();
            PyGILState_Release(state);
            throw std::runtime_error("Failed to get 'editor' attribute from module");
        }

        if (PyCallable_Check(pClass)) {
            pFunc_ = PyObject_GetAttrString(pClass, "deal_func_from_js");
        }

        Py_DECREF(pClass);
        Py_DECREF(pModule);

    } catch (const std::exception&) {
        if (pModule) {
            Py_DECREF(pModule);
        }
        PyErr_Print();
        PyGILState_Release(state);
        throw;
    }

    PyGILState_Release(state);
}

bool BrowserSideJSHandler::OnQuery(CefRefPtr<CefBrowser> browser,
                                   CefRefPtr<CefFrame> frame,
                                   int64_t query_id,
                                   const CefString& request,
                                   bool persistent,
                                   CefRefPtr<Callback> callback) {
    CEF_REQUIRE_UI_THREAD();
    std::string req = request.ToString();

    // ── SceneTools.play_audio / stop_audio：C++ 快速通道，不走 Python ──
    // 前端 Bridge.callCEF(\"SceneTools\", \"play_audio\", [rid, loop]) 直接在此处理，
    // 避免持有 GIL 阻塞 Python 线程。
    if (req.find("\"SceneTools\"") != std::string::npos) {
        try {
            auto j = nlohmann::json::parse(req);
            if (j.value("module", "") == "SceneTools") {
                std::string func = j.value("function", "");
                auto args = j.value("args", nlohmann::json::array());

                if (func == "play_audio" || func == "stop_audio") {
                    auto* event_bus = Corona::Kernel::KernelContext::instance().event_bus();
                    if (!event_bus) {
                        callback->Failure(2, "event_bus unavailable");
                        return true;
                    }

                    // resource_id 以字符串传递（JS number 无法精确表示 64 位整数）。
                    // 兼容字符串和数字两种 JSON 形态。
                    uint64_t rid = 0;
                    if (args.size() > 0) {
                        if (args[0].is_string()) {
                            try {
                                rid = std::stoull(args[0].get<std::string>());
                            } catch (...) {
                                rid = 0;
                            }
                        } else if (args[0].is_number_unsigned()) {
                            rid = args[0].get<uint64_t>();
                        }
                    }
                    if (rid == 0) {
                        callback->Failure(2, "invalid resource_id");
                        return true;
                    }

                    if (func == "play_audio") {
                        bool loop = args.size() > 1 ? args[1].get<bool>() : false;
                        event_bus->publish<::Corona::Events::PlayAudioEvent>({rid, loop});
                    } else {
                        event_bus->publish<::Corona::Events::StopAudioEvent>({rid});
                    }

                    nlohmann::json payload;
                    payload["ok"] = true;
                    callback->Success(create_success_json(func, payload));
                    return true;
                }
            }
        } catch (...) {
            callback->Failure(2, "SceneTools fast path error");
            return true;
        }
    }

    // ── Network 模块：C++ 直接处理，不走 Python ──
    // LAN 协同编辑的 start/stop/peer_count 全部由 C++ 直接响应，避免高频
    // get_peer_count 轮询在持有 GIL 时阻塞 SystemManager 锁导致的关闭死锁。
    if (req.find("\"Network\"") != std::string::npos) {
        try {
            auto j = nlohmann::json::parse(req);
            if (j.value("module", "") == "Network") {
                std::string func = j.value("function", "");
                auto args = j.value("args", nlohmann::json::array());

                auto sys = get_network_system();
                if (!sys) {
                    callback->Failure(2, "NetworkSystem unavailable");
                    return true;
                }

                if (func == "start_session") {
                    // args: [instance_name, project_id, port, role]
                    std::string name = args.size() > 0 ? args[0].get<std::string>() : "";
                    uint64_t project_id = args.size() > 1 ? args[1].get<uint64_t>() : 0;
                    uint16_t port = args.size() > 2 ? args[2].get<uint16_t>() : 27960;
                    auto role = args.size() > 3
                        ? parse_network_session_role(args[3])
                        : Corona::Systems::NetworkSystem::SessionRole::Host;

                    bool ok = sys->start_session(name, project_id, port, role);
                    nlohmann::json payload = build_network_session_info(sys);
                    payload["ok"] = ok;
                    callback->Success(create_success_json("start_session", payload));
                    return true;
                }

                if (func == "stop_session") {
                    sys->stop_session();
                    nlohmann::json payload;
                    payload["ok"] = true;
                    callback->Success(create_success_json("stop_session", payload));
                    return true;
                }

                if (func == "get_peer_count") {
                    nlohmann::json payload = build_network_session_info(sys);
                    callback->Success(create_success_json("get_peer_count", payload));
                    return true;
                }

                if (func == "get_session_info") {
                    callback->Success(create_success_json(
                        "get_session_info", build_network_session_info(sys)));
                    return true;
                }

                if (func == "connect_to_peer") {
                    // args: [ip, port, peer_name]
                    std::string ip = args.size() > 0 ? args[0].get<std::string>() : "";
                    uint16_t port = args.size() > 1 ? args[1].get<uint16_t>() : 27960;
                    std::string peer_name = args.size() > 2 ? args[2].get<std::string>() : "";

                    bool ok = sys->connect_to_peer(ip, port, peer_name);
                    nlohmann::json payload = build_network_session_info(sys);
                    payload["ok"] = ok;
                    callback->Success(create_success_json("connect_to_peer", payload));
                    return true;
                }

                if (func == "set_project_root") {
                    // args: [project_root_path]
                    std::string root = args.size() > 0 ? args[0].get<std::string>() : "";
                    if (!root.empty()) {
                        sys->set_project_root(root);
                    }
                    nlohmann::json payload;
                    payload["ok"] = true;
                    callback->Success(create_success_json("set_project_root", payload));
                    return true;
                }

                if (func == "poll_pending_actor_create") {
                    // Called by frontend every ~500ms when session is active.
                    // Returns the next pending actor create entry, so Python
                    // can call SceneTools.create_actor_internal.
                    nlohmann::json payload;
                    std::string actor_guid, scene_name, model_path;
                    Network::ActorCreatePacked packed;
                    if (sys->pop_pending_actor_create(actor_guid, scene_name, model_path,
                                                       &packed, sizeof(packed))) {
                        payload["has_pending"] = true;
                        payload["actor_guid"] = actor_guid;
                        payload["scene_name"] = scene_name;
                        payload["model_path"] = model_path;
                        // Convert transform (9 floats) and optics for Python
                        nlohmann::json actor_data;
                        actor_data["geometry"]["position"] = {
                            packed.transform[0], packed.transform[1], packed.transform[2]
                        };
                        actor_data["geometry"]["rotation"] = {
                            packed.transform[3], packed.transform[4], packed.transform[5]
                        };
                        actor_data["geometry"]["scale"] = {
                            packed.transform[6], packed.transform[7], packed.transform[8]
                        };
                        payload["actor_data"] = actor_data;
                    } else {
                        payload["has_pending"] = false;
                    }
                    payload["ok"] = true;
                    callback->Success(create_success_json("poll_pending_actor_create", payload));
                    return true;
                }

                if (func == "set_sync_paused") {
                    bool paused = args.size() > 0 ? args[0].get<bool>() : false;
                    sys->set_sync_paused(paused);
                    nlohmann::json payload;
                    payload["ok"] = true;
                    callback->Success(create_success_json("set_sync_paused", payload));
                    return true;
                }

                if (func == "register_actor_identity") {
                    // args: [actor_guid, actor_handle, locally_owned]
                    std::string actor_guid = args.size() > 0 ? args[0].get<std::string>() : "";
                    std::uintptr_t actor_handle = args.size() > 1 ? json_to_uintptr(args[1]) : 0;
                    bool locally_owned = args.size() > 2 ? args[2].get<bool>() : true;
                    bool ok = sys->register_actor_identity(
                        actor_guid, actor_handle, locally_owned);
                    nlohmann::json payload;
                    payload["ok"] = ok;
                    callback->Success(create_success_json("register_actor_identity", payload));
                    return true;
                }

                if (func == "claim_actor_ownership") {
                    // args: [actor_guid]
                    std::string actor_guid = args.size() > 0 ? args[0].get<std::string>() : "";
                    bool ok = sys->claim_actor_ownership(actor_guid);
                    nlohmann::json payload;
                    payload["ok"] = ok;
                    callback->Success(create_success_json("claim_actor_ownership", payload));
                    return true;
                }

                if (func == "broadcast_actor_create") {
                    // args: [actor_guid, scene_name, model_path, actor_data_dict]
                    std::string actor_guid = args.size() > 0 ? args[0].get<std::string>() : "";
                    std::string scene_name = args.size() > 1 ? args[1].get<std::string>() : "";
                    std::string model_path = args.size() > 2 ? args[2].get<std::string>() : "";
                    // actor_data is a dict with geometry.position/rotation/scale
                    // Extract transform (9 floats) — default to identity
                    float transform[9] = {0,0,0, 0,0,0, 1,1,1};
                    std::vector<std::string> dependency_paths;
                    if (args.size() > 3 && args[3].is_object()) {
                        auto& ad = args[3];
                        if (actor_guid.empty() && ad.contains("actor_guid") && ad["actor_guid"].is_string()) {
                            actor_guid = ad["actor_guid"].get<std::string>();
                        }
                        if (ad.contains("model_dependencies") && ad["model_dependencies"].is_array()) {
                            for (const auto& dep : ad["model_dependencies"]) {
                                if (dep.is_string()) {
                                    dependency_paths.push_back(dep.get<std::string>());
                                }
                            }
                        }
                        if (ad.contains("geometry")) {
                            auto& geo = ad["geometry"];
                            if (geo.contains("position") && geo["position"].is_array() && geo["position"].size() >= 3) {
                                transform[0] = geo["position"][0].get<float>();
                                transform[1] = geo["position"][1].get<float>();
                                transform[2] = geo["position"][2].get<float>();
                            }
                            if (geo.contains("rotation") && geo["rotation"].is_array() && geo["rotation"].size() >= 3) {
                                transform[3] = geo["rotation"][0].get<float>();
                                transform[4] = geo["rotation"][1].get<float>();
                                transform[5] = geo["rotation"][2].get<float>();
                            }
                            if (geo.contains("scale") && geo["scale"].is_array() && geo["scale"].size() >= 3) {
                                transform[6] = geo["scale"][0].get<float>();
                                transform[7] = geo["scale"][1].get<float>();
                                transform[8] = geo["scale"][2].get<float>();
                            }
                        }
                    }
                    if (actor_guid.empty()) {
                        actor_guid = scene_name + ":" + model_path;
                    }
                    // Build default optics (all defaults)
                    Network::ActorCreatePacked opt;
                    std::memset(&opt, 0, sizeof(opt));
                    opt.visible = true;
                    opt.bEnableLighting = true;
                    opt.metallic = 0.0f;
                    opt.roughness = 0.5f;
                    opt.specular = 0.5f;
                    opt.specularTint = 0.0f;
                    opt.sheen = 0.0f;
                    opt.sheenTint = 0.5f;
                    opt.clearcoat = 0.0f;
                    opt.clearcoatGloss = 1.0f;
                    opt.ambient[0] = 0.2f; opt.ambient[1] = 0.2f; opt.ambient[2] = 0.2f;
                    opt.diffuse[0] = 0.8f; opt.diffuse[1] = 0.8f; opt.diffuse[2] = 0.8f;
                    opt.specular_color[0] = 1.0f; opt.specular_color[1] = 1.0f; opt.specular_color[2] = 1.0f;
                    opt.shininess = 32.0f;

                    sys->broadcast_actor_create(actor_guid, scene_name, model_path,
                                                dependency_paths, transform,
                                                &opt, sizeof(opt));
                    nlohmann::json payload;
                    payload["ok"] = true;
                    callback->Success(create_success_json("broadcast_actor_create", payload));
                    return true;
                }

                callback->Failure(1, "Unknown Network function: " + func);
                return true;
            }
        } catch (const nlohmann::json::parse_error&) {
            // 非合法 JSON，继续走后续路径
        }
    }

    if (!Py_IsInitialized()) {
        Py_Initialize();
        PyEval_SaveThread();
    }

    PyGILState_STATE gstate = PyGILState_Ensure();

    try {
        if (!pFunc_) {
            initialize_python();
        }

        PyObject* args = PyTuple_Pack(1, PyUnicode_FromString(req.c_str()));
        PyObject* object = PyObject_CallObject(pFunc_, args);
        Py_DECREF(args);

        if (!object) {
            PyErr_Print();
            VUE_LOG_ERROR("Python function call failed for request");
            callback->Failure(0, "Python function call failed");
        } else {
            if (PyUnicode_Check(object)) {
                const char* result = PyUnicode_AsUTF8(object);
                callback->Success(result);
            } else {
                if (PyObject* str_obj = PyObject_Str(object)) {
                    const char* result = PyUnicode_AsUTF8(str_obj);
                    callback->Success(result);
                    Py_DECREF(str_obj);
                }
            }
            Py_DECREF(object);
        }

    } catch (const std::exception& e) {
        std::cerr << "Exception in OnQuery: " << e.what() << std::endl;
        callback->Failure(0, e.what());
        PyGILState_Release(gstate);
        return false;
    }

    PyGILState_Release(gstate);
    return true;
}

}  // namespace Corona::Systems::UI
