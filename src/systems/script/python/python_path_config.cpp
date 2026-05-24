//
// Created by 25473 on 2025/11/19.
//
#include <algorithm>
#include <filesystem>
#include <regex>
#include <string>

namespace Corona::Script::Python::PathCfg {

static auto normalize(std::string s) -> std::string {
    std::ranges::replace(s, '\\', '/');
    return s;
}

auto engine_root() -> const std::string& {
    static std::string root = [] {
        std::string resultPath;
        std::string runtimePath = std::filesystem::current_path().string();
        std::regex pattern(R"((.*)CoronaEngine\b)");
        std::smatch matches;
        if (std::regex_search(runtimePath, matches, pattern)) {
            if (matches.size() > 1) {
                resultPath = matches[1].str() + "CoronaEngine";
            } else {
                throw std::runtime_error("Failed to resolve source path.");
            }
        }
        return normalize(resultPath);
    }();
    return root;
}

auto editor_backend_rel() -> const std::string& {
    static const std::string rel = "editor";
    return rel;
}

auto editor_backend_abs() -> const std::string& {
    static const std::string abs = normalize(engine_root() + "/" + editor_backend_rel());
    return abs;
}

auto runtime_backend_abs() -> std::string {
    auto p = std::filesystem::current_path() / "CabbageEditor";
    return normalize(p.string());
}

auto site_packages_dir() -> std::string {
    return normalize(std::string(CORONA_PYTHON_MODULE_LIB_DIR) + "/site-packages");
}

}  // namespace Corona::Script::Python::PathCfg