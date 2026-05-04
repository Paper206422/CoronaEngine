#pragma once

#include <cef_app.h>
#include <nanobind/nanobind.h>

#include "browser_manager.h"
#include "cef_client.h"
namespace nb = nanobind;

namespace EngineScripts {

void BindCef(nanobind::module_& m) {
    // 向python注册创建浏览器标签页函数绑定
    m.def("create_browser_tab", [](nb::object py_url, nb::object py_path, nb::object py_docking_pos, nb::object py_dock_width, nb::object py_dock_height, nb::object py_dock_fixed) -> int {
            try {
                if (!py_url.is_valid()) {
                    return -1;
                }
                
                nb::str py_url_str = nb::str(py_url);
                std::string url = py_url_str.c_str();
                
                nb::str py_path_str = nb::str(py_path);
                std::string path = py_path_str.c_str();
                
                // 处理docking参数
                std::string docking_pos = "";
                int dock_width = 0;
                int dock_height = 0;
                bool dock_fixed = false;
                
                if (py_docking_pos.is_valid()) {
                    nb::str pos_str = nb::str(py_docking_pos);
                    docking_pos = pos_str.c_str();
                }
                
                if (py_dock_width.is_valid() && !py_dock_width.is_none()) {
                    dock_width = nb::cast<int>(py_dock_width);
                }
                
                if (py_dock_height.is_valid() && !py_dock_height.is_none()) {
                    dock_height = nb::cast<int>(py_dock_height);
                }
                
                if (py_dock_fixed.is_valid() && !py_dock_fixed.is_none()) {
                    dock_fixed = nb::cast<bool>(py_dock_fixed);
                }
                
                // Use BrowserManager
                return Corona::Systems::UI::BrowserManager::instance().create_tab(
                    url, path, docking_pos, dock_width, dock_height, dock_fixed);
            } catch (const std::exception& e) {
                CFW_LOG_ERROR("Unexpected error: %s", e.what());
                return -1;
            } }, nb::arg("url") = "", nb::arg("path") = "", nb::arg("docking_pos") = "", nb::arg("dock_width") = 0, nb::arg("dock_height") = 0, nb::arg("dock_fixed") = false, nb::rv_policy::take_ownership);

    // 向python注册执行JavaScript代码函数绑定
    m.def("execute_javascript", [](int tab_id, nb::object py_js_code) -> nb::str {
            try {
                // Use BrowserManager
                auto* tab = Corona::Systems::UI::BrowserManager::instance().get_tab(tab_id);
                if (!tab) {
                    return nb::str("{\"success\": false, \"error\": \"Tab not found\"}");
                }
                nb::str py_str = nb::str(py_js_code);
                std::string js_code = py_str.c_str();

                if (tab->client && tab->client->GetBrowser()) {
                    if (CefRefPtr<CefFrame> frame = tab->client->GetBrowser()->GetMainFrame()) {
                        frame->ExecuteJavaScript(js_code, "", 0);
                    }
                }
                return nb::str("{\"success\": true}");
            } catch (const std::exception&) {
                return nb::str("{\"success\": false \"}");
            } }, nb::arg("tab_id"), nb::arg("js_code"));

    // 最小化浏览器标签页
    m.def("minimize_browser_tab", [](int tab_id, bool if_close) -> bool {
            try {
                return Corona::Systems::UI::BrowserManager::instance().hide_tab(tab_id, if_close);
            } catch (const std::exception& e) {
                CFW_LOG_ERROR("Unexpected error in minimize_browser_tab: %s", e.what());
                return false;
            } }, nb::arg("tab_id"), nb::arg("if_close") = false, nb::rv_policy::take_ownership);

    // 恢复最小化的浏览器标签页
    m.def("restore_browser_tab", [](int tab_id) -> bool {
            try {
                return Corona::Systems::UI::BrowserManager::instance().show_tab(tab_id);
            } catch (const std::exception& e) {
                CFW_LOG_ERROR("Unexpected error in restore_browser_tab: %s", e.what());
                return false;
            } }, nb::arg("tab_id"), nb::rv_policy::take_ownership);

    m.def("set_tab_drag_regions", [](int tab_id, nb::list py_regions) {
            std::vector<Corona::Systems::UI::DragRegion> regions;
            for (auto item : py_regions) {
                auto dict = nb::cast<nb::dict>(item);
                regions.push_back({
                    nb::cast<float>(dict["x"]),
                    nb::cast<float>(dict["y"]),
                    nb::cast<float>(dict["w"]),
                    nb::cast<float>(dict["h"])
                });
            }
            Corona::Systems::UI::BrowserManager::instance().set_tab_drag_regions(tab_id, regions); }, nb::arg("tab_id"), nb::arg("regions"));
}

}  // namespace EngineScripts