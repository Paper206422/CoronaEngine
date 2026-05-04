#pragma once

#include <nanobind/nanobind.h>

#include <string>

namespace Corona::Script::Python {

void log_python_error(const nanobind::python_error& e);
std::string wstr_to_str(const std::wstring& wstr);

}  // namespace Corona::Script::Python
