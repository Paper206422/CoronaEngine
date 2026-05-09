#include "corona/scene/desc/transform_desc.h"

#include "ktm/function/matrix/matrix_transform3d.h"
#include "ktm/type/affine3d.h"
#include "ktm/type_mat.h"

namespace Corona::Resource::Scene {
namespace {
bool process_look_at(const JsonWrapper& param, ktm::fmat4x4& mat) {
    auto const& position_item = param.find("position");
    auto const& up_item = param.find("up");
    auto const& target_pos_item = param.find("target_pos");

    if (position_item == param.end() || up_item == param.end() || target_pos_item == param.end()) {
        return false;
    }

    ktm::fvec3 position = JsonHelpers::parse_vec3(*position_item);
    ktm::fvec3 up = JsonHelpers::parse_vec3(*up_item);
    ktm::fvec3 target_pos = JsonHelpers::parse_vec3(*target_pos_item);
    mat = ktm::look_at_lh(position, target_pos, up);
    return true;
}

bool process_euler(const JsonWrapper& param, ktm::fmat4x4& mat) {
    auto const& yaw_item = param.find("yaw");
    auto const& pitch_item = param.find("pitch");
    auto const& roll_item = param.find("roll");
    auto const& position_item = param.find("position");

    if (yaw_item == param.end() || pitch_item == param.end() ||
        roll_item == param.end() || position_item == param.end()) {
        return false;
    }

    float yaw = yaw_item->get<float>();
    float pitch = pitch_item->get<float>();
    float roll = roll_item->get<float>();
    ktm::fvec3 position = JsonHelpers::parse_vec3(*position_item);

    // TODO: 确认变换正确性❓❓❓❓❓❓❓
    // 使用 affine3d 链式调用,更符合 ktm 设计理念
    ktm::faffine3d transform;
    transform.translate(position).rotate_y(yaw).rotate_x(pitch).rotate_z(roll);
    transform >> mat;
    return true;
}

bool process_trs(const JsonWrapper& param, ktm::fmat4x4& mat) {
    auto const& t_item = param.find("t");
    auto const& r_item = param.find("r");
    auto const& s_item = param.find("s");

    if (t_item == param.end() || r_item == param.end() || s_item == param.end()) {
        return false;
    }

    ktm::fvec3 t = JsonHelpers::parse_vec3(*t_item);
    ktm::fvec4 r = JsonHelpers::parse_vec4(*r_item);
    ktm::fvec3 s = JsonHelpers::parse_vec3(*s_item);

    ktm::faffine3d transform;
    transform.translate(t).rotate(r).scale(s);
    transform >> mat;
    return true;
}

bool process_matrix4x4(const JsonWrapper& param, ktm::fmat4x4& mat) {
    auto const& matrix_item = param.find("matrix4x4");

    if (matrix_item == param.end()) {
        return false;
    }

    if (!matrix_item->is_array() || matrix_item->size() != 4) {
        return false;
    }

    mat = JsonHelpers::parse_mat4x4(*matrix_item);
    return true;
}
}  // namespace

void TransformDesc::init(const JsonWrapper& params) {
    if (params.is_null()) {
        return;
    }

    sub_type = "matrix4x4";  // 默认类型
    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        sub_type = type_item->get<std::string>();
    }

    JsonWrapper param = params.value("param", JsonWrapper::object());

    if (sub_type == "look_at") {
        process_look_at(param, mat);
    } else if (sub_type == "Euler") {
        process_euler(param, mat);
    } else if (sub_type == "trs") {
        process_trs(param, mat);
    } else if (sub_type == "matrix4x4") {
        process_matrix4x4(param, mat);
    }
}

}  // namespace Corona::Resource::Scene