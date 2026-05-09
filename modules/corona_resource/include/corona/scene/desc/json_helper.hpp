#pragma once

#include <iostream>
#include <nlohmann/json.hpp>

#include "ktm/type_mat.h"
#include "ktm/type_vec.h"

namespace Corona::Resource::Scene {
/// @brief 参数包装器类型，使用 JSON 对象存储参数
using JsonWrapper = nlohmann::json;

namespace JsonHelpers {

// 辅助函数:从 JSON 数组转换为 fvec3
inline ktm::fvec3 parse_vec3(const JsonWrapper& json_array) {
    if (!json_array.is_array() ||
        json_array.size() != 3) {
#ifdef _DEBUG
        std::cerr << "JsonHelpers::parse_vec3 - Invalid vec3 array format." << std::endl;
#endif
        return ktm::fvec3(0.0f, 0.0f, 0.0f);
    }
    auto const& v0 = json_array.at(0);
    auto const& v1 = json_array.at(1);
    auto const& v2 = json_array.at(2);
    if (!v0.is_number_float() ||
        !v1.is_number_float() ||
        !v2.is_number_float()) {
#ifdef _DEBUG
        std::cerr << "JsonHelpers::parse_vec3 - Non-float values in vec3 array." << std::endl;
#endif
        return ktm::fvec3(0.0f, 0.0f, 0.0f);
    }
    return ktm::fvec3(v0.get<float>(), v1.get<float>(), v2.get<float>());
}

inline ktm::fvec4 parse_vec4(const JsonWrapper& json_array) {
    if (!json_array.is_array() ||
        json_array.size() != 4) {
#ifdef _DEBUG
        std::cerr << "JsonHelpers::parse_vec4 - Invalid vec4 array format." << std::endl;
#endif
        return ktm::fvec4(0.0f, 0.0f, 0.0f, 0.0f);
    }
    auto const& v0 = json_array.at(0);
    auto const& v1 = json_array.at(1);
    auto const& v2 = json_array.at(2);
    auto const& v3 = json_array.at(3);
    if (!v0.is_number_float() ||
        !v1.is_number_float() ||
        !v2.is_number_float() ||
        !v3.is_number_float()) {
#ifdef _DEBUG
        std::cerr << "JsonHelpers::parse_vec4 - Non-float values in vec4 array." << std::endl;
#endif
        return ktm::fvec4(0.0f, 0.0f, 0.0f, 0.0f);
    }
    return ktm::fvec4(v0.get<float>(), v1.get<float>(), v2.get<float>(), v3.get<float>());
}

inline ktm::fmat4x4 parse_mat4x4(const JsonWrapper& json_array) {
    if (!json_array.is_array() ||
        json_array.size() != 4) {
#ifdef _DEBUG
        std::cerr << "JsonHelpers::parse_mat4x4 - Invalid mat4x4 array format." << std::endl;
#endif
        return ktm::fmat4x4{};
    }
    ktm::fvec4 row0 = parse_vec4(json_array.at(0));
    ktm::fvec4 row1 = parse_vec4(json_array.at(1));
    ktm::fvec4 row2 = parse_vec4(json_array.at(2));
    ktm::fvec4 row3 = parse_vec4(json_array.at(3));
    return ktm::fmat4x4(row0, row1, row2, row3);
}

}  // namespace JsonHelpers

}  // namespace Corona::Resource::Scene