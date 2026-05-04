#pragma once

#include <string>

namespace Corona::Script::Python::PathCfg {

const std::string& engine_root();
const std::string& editor_backend_rel();
const std::string& editor_backend_abs();
std::string runtime_backend_abs();
std::string site_packages_dir();

}  // namespace Corona::Script::Python::PathCfg
