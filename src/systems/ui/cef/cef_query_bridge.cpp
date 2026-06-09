#include "browser_manager.h"
#include "cef_client.h"

#include <corona/events/acoustics_system_events.h>
#include <corona/kernel/core/kernel_context.h>
#include <corona/systems/network/network_system.h>

#include <iostream>
#include <memory>
#include <stdexcept>

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
                    // args: [instance_name, project_id, port]
                    std::string name = args.size() > 0 ? args[0].get<std::string>() : "";
                    uint64_t project_id = args.size() > 1 ? args[1].get<uint64_t>() : 0;
                    uint16_t port = args.size() > 2 ? args[2].get<uint16_t>() : 27960;

                    bool ok = sys->start_session(name, project_id, port);
                    nlohmann::json payload;
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
                    nlohmann::json payload;
                    payload["ok"] = true;
                    payload["peer_count"] = static_cast<int>(sys->peer_count());
                    callback->Success(create_success_json("get_peer_count", payload));
                    return true;
                }

                callback->Failure(1, "Unknown Network function: " + func);
                return true;
            }
        } catch (const nlohmann::json::parse_error&) {
            // 非合法 JSON，继续走后续路径
        }
    }

    // ── __cross_tab__ 跨窗口通信：C++ 直接处理，不走 Python ──
    // 快速路径：用字符串搜索代替完整 JSON parse，避免对每个高频
    // cefQuery（update_drag_regions 等）都在 UI 线程上做全量 JSON 解析。
    // __cross_tab__ 请求很少（仅 pop-out/close/broadcast），先搜再 parse。
    if (req.find("\"__cross_tab__\"") != std::string::npos) {
        try {
            auto j = nlohmann::json::parse(req);
            if (j.value("module", "") == "__cross_tab__") {
            std::string func = j.value("function", "");
            auto args = j.value("args", nlohmann::json::array());
            auto& bm = BrowserManager::instance();

            auto do_broadcast = [&](const std::string& event,
                                    const nlohmann::json& payload) {
                // Spread array elements individually, pass objects as-is.
                // Tail with {_fromCross:1} to prevent relay loops in Vue.
                std::string args_js;
                if (payload.is_array()) {
                    for (size_t i = 0; i < payload.size(); i++) {
                        if (i > 0) args_js += ",";
                        args_js += payload[i].dump();
                    }
                    if (!args_js.empty()) args_js += ",";
                } else {
                    args_js = payload.dump();
                    args_js += ",";
                }
                args_js += "{\"_fromCross\":1}";
                std::string js =
                    "if(window.__coronaEmit)window.__coronaEmit('" + event +
                    "'," + args_js + ")";
                for (auto& [id, tab] : bm.get_tabs()) {
                    if (!tab->minimized && tab->client &&
                        tab->client->GetBrowser()) {
                        tab->client->GetBrowser()
                            ->GetMainFrame()
                            ->ExecuteJavaScript(js, "", 0);
                    }
                }
            };

            if (func == "broadcast") {
                // args: [event, payload]
                std::string event =
                    args.size() > 0 ? args[0].get<std::string>() : "";
                nlohmann::json payload = args.size() > 1 ? args[1]
                                                         : nlohmann::json::object();
                do_broadcast(event, payload);
                callback->Success(create_success_json("broadcast", event));
                return true;
            }

            if (func == "create-panel-tab") {
                // args: [panelId, routePath, width, height]
                std::string panel_id =
                    args.size() > 0 ? args[0].get<std::string>() : "";
                std::string route =
                    args.size() > 1 ? args[1].get<std::string>() : "";
                int w = args.size() > 2 ? args[2].get<int>() : 400;
                int h = args.size() > 3 ? args[3].get<int>() : 600;

                // Strip leading # if present
                if (!route.empty() && route[0] == '#')
                    route = route.substr(1);

                // Construct full URL with standalone marker from current
                // browser's URL, so the new tab knows it is a pop-out
                std::string main_url =
                    browser->GetMainFrame()->GetURL().ToString();
                auto hash_pos = main_url.find('#');
                std::string base_url =
                    (hash_pos != std::string::npos)
                        ? main_url.substr(0, hash_pos)
                        : main_url;
                std::string full_url =
                    base_url + "#" + route + "?standalone=1";

                int tab_id = bm.create_tab(full_url, route + "?standalone=1",
                                           "right_top", w, h, false);
                nlohmann::json result;
                result["tab_id"] = tab_id;
                result["panel_id"] = panel_id;
                callback->Success(
                    create_success_json("create-panel-tab", result));
                return true;
            }

            if (func == "close-this-tab") {
                // Find tab belonging to the calling browser and remove it
                auto& tabs = bm.get_tabs();
                int found_id = -1;
                int bid = browser->GetIdentifier();
                for (auto& [id, tab] : tabs) {
                    if (tab->client && tab->client->GetBrowser() &&
                        tab->client->GetBrowser()->GetIdentifier() == bid) {
                        found_id = id;
                        break;
                    }
                }
                if (found_id >= 0) {
                    bm.remove_tab(found_id);
                }
                std::string panel_id =
                    args.size() > 0 ? args[0].get<std::string>() : "";
                nlohmann::json payload;
                payload["panelId"] = panel_id;
                do_broadcast("panel-closed", payload);
                callback->Success(
                    create_success_json("close-this-tab", payload));
                return true;
            }

            if (func == "close-panel-tab") {
                // args: [tabId, panelId]
                int tab_id = args.size() > 0 ? args[0].get<int>() : -1;
                std::string panel_id =
                    args.size() > 1 ? args[1].get<std::string>() : "";
                if (tab_id >= 0) {
                    bm.remove_tab(tab_id);
                }
                nlohmann::json payload;
                payload["panelId"] = panel_id;
                do_broadcast("panel-closed", payload);
                callback->Success(
                    create_success_json("close-panel-tab", payload));
                return true;
            }

            callback->Failure(1, "Unknown __cross_tab__ function: " + func);
            return true;
            }
        } catch (const nlohmann::json::parse_error&) {
            // 不是合法 JSON 或非 __cross_tab__，继续走 Python 路径
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