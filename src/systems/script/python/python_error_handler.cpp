//
// Created by 25473 on 2025/11/19.
//
// src/script/python/python_error_handler.cpp

#include <nanobind/nanobind.h>
#include <windows.h>

#include <iostream>

namespace Corona::Script::Python {

auto log_python_error(const nanobind::python_error& e) -> void {
    try {
        nanobind::gil_scoped_acquire gil;
        std::string formatted;

        try {
            nanobind::module_ traceback = nanobind::module_::import_("traceback");
            nanobind::object format_exception = nanobind::getattr(traceback, "format_exception");
            auto formatted_list = format_exception(e.type(), e.value(), e.traceback());
            nanobind::str sep("");
            auto joined = nanobind::getattr(sep, "join")(formatted_list);
            formatted = nanobind::cast<std::string>(joined);
        } catch (...) {
            formatted = e.what();
        }

        std::cerr << "[Python Error] " << formatted << std::endl;
    } catch (...) {
        std::cerr << "[Python Error] (formatting failed)" << std::endl;
    }
}

auto wstr_to_str(const std::wstring& wstr) -> std::string {
    if (wstr.empty()) return {};
    int len = WideCharToMultiByte(CP_UTF8, 0, wstr.c_str(),
                                  static_cast<int>(wstr.size()),
                                  nullptr, 0, nullptr, nullptr);
    if (len <= 0) return {};
    std::string out(static_cast<size_t>(len), '\0');
    WideCharToMultiByte(CP_UTF8, 0, wstr.c_str(),
                        static_cast<int>(wstr.size()),
                        out.data(), len, nullptr, nullptr);
    return out;
}

}  // namespace Corona::Script::Python
