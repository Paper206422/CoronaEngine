#include <corona/events/engine_events.h>
#include <corona/events/mechanics_system_events.h>
#include <corona/kernel/core/i_logger.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/systems/mechanics/mechanics_system.h>
#include <corona/systems/geometry/geometry_system.h>

#include <algorithm>      // min,max,clamp,sort,unique
#include <array>          // std::array（八叉树子节点）
#include <atomic>         // g_shutdown_requested
#include <cmath>          // asin,atan2,fabs,abs
#include <cstddef>        // size_t
#include <cstdint>        // 固定宽度整数
#include <functional>     // std::function（回调）
#include <limits>         // numeric_limits（SAT）
#include <memory>         // unique_ptr,make_unique
#include <unordered_map>  // 各 handle→数据 映射
#include <unordered_set>  // alive_handles
#include <utility>        // pair, move
#include <vector>         // mechanics_data, collision_pairs 等

#include "corona/shared_data_hub.h"  // 场景/几何/transform 集中存储
#include "ktm/ktm.h"                 // 向量矩阵四元数

// Resource layer — 用于加载 LOD 碰撞网格
#include <corona/resource/resource_manager.h>
#include <corona/resource/types/scene.h>
// Note: do not depend on nanobind in the mechanics system. Callbacks provided
// from the scripting layer are expected to manage GIL acquisition themselves.

#ifndef CORONA_MECHANICS_USE_OBB_SAT
#define CORONA_MECHANICS_USE_OBB_SAT 1
#endif

#ifndef CORONA_MECHANICS_USE_TRIANGLE_NARROWPHASE
#define CORONA_MECHANICS_USE_TRIANGLE_NARROWPHASE 1
#endif

namespace {

// 按分量构造 fvec3（result：输出向量）
constexpr ktm::fvec3 make_fvec3(float x, float y, float z) {
    ktm::fvec3 result;  // 返回值缓冲
    result.x = x;       // X
    result.y = y;       // Y
    result.z = z;       // Z
    return result;      // 按值传出
}

// 封装构造四元数
constexpr ktm::fvec4 make_fvec4(float x, float y, float z, float w) {
    ktm::fvec4 result2;  // 返回值缓冲
    result2.x = x;       // X
    result2.y = y;       // Y
    result2.z = z;       // Z
    result2.w = w;
    return result2;  // 按值传出
}

inline ktm::fvec3 vec3_add(const ktm::fvec3& a, const ktm::fvec3& b) {
    return make_fvec3(a.x + b.x, a.y + b.y, a.z + b.z);  // 逐分量加
}
inline ktm::fvec3 vec3_sub(const ktm::fvec3& a, const ktm::fvec3& b) {
    return make_fvec3(a.x - b.x, a.y - b.y, a.z - b.z);  // 逐分量减
}
inline ktm::fvec3 vec3_mul(const ktm::fvec3& v, float s) {
    return make_fvec3(v.x * s, v.y * s, v.z * s);  // 标量乘向量
}

// 检测两个 AABB 是否重叠（世界/局部复用）
inline bool aabb_overlap(const ktm::fvec3& a_min, const ktm::fvec3& a_max,
                         const ktm::fvec3& b_min, const ktm::fvec3& b_max) {
    return (a_min.x <= b_max.x && a_max.x >= b_min.x) &&
           (a_min.y <= b_max.y && a_max.y >= b_min.y) &&
           (a_min.z <= b_max.z && a_max.z >= b_min.z);
}

// local：局部点；返回：同一几何点在世界的坐标
inline ktm::fvec3 transform_local_point_to_world(const Corona::ModelTransform& t, const ktm::fvec3& local) {
    ktm::fmat4x4 M = t.compute_matrix();  // 4×4 TRS
    ktm::fvec4 local_h = make_fvec4(local.x, local.y, local.z, 1.0f);
    // w=1 表示点而非方向
    ktm::fvec4 world_h = M * local_h;                    // 齐次乘法
    return make_fvec3(world_h.x, world_h.y, world_h.z);  // 透视下 w 应为 1，取 xyz 即可
}

// lmin,lmax：局部轴对齐盒；out_*：世界 AABB 及中心
inline void world_aabb_from_local_bounds(const Corona::ModelTransform& t,
                                         const ktm::fvec3& lmin, const ktm::fvec3& lmax,
                                         ktm::fvec3& out_min, ktm::fvec3& out_max, ktm::fvec3& out_center) {
    // 局部 AABB 的 8 个角点：min/max 各分量组合 → 世界空间 → 取包络
    const ktm::fvec3 corners[8] = {
        {lmin.x, lmin.y, lmin.z}, {lmax.x, lmin.y, lmin.z},
        {lmin.x, lmax.y, lmin.z}, {lmax.x, lmax.y, lmin.z},
        {lmin.x, lmin.y, lmax.z}, {lmax.x, lmin.y, lmax.z},
        {lmin.x, lmax.y, lmax.z}, {lmax.x, lmax.y, lmax.z},
    };
    ktm::fvec3 wp0 = transform_local_point_to_world(t, corners[0]);
    out_min = wp0;
    out_max = wp0;
    for (int i = 1; i < 8; ++i) {
        const ktm::fvec3 wp = transform_local_point_to_world(t, corners[i]);
        out_min.x = std::min(out_min.x, wp.x);
        out_min.y = std::min(out_min.y, wp.y);
        out_min.z = std::min(out_min.z, wp.z);
        out_max.x = std::max(out_max.x, wp.x);
        out_max.y = std::max(out_max.y, wp.y);
        out_max.z = std::max(out_max.z, wp.z);
    }
    out_center = make_fvec3(
        (out_min.x + out_max.x) * 0.5f,  // 形心 X
        (out_min.y + out_max.y) * 0.5f,
        (out_min.z + out_max.z) * 0.5f);
}

// 返回世界包络盒在 Y 轴上的最小值（贴地）
inline float world_aabb_min_y(const Corona::ModelTransform& t,
                              const ktm::fvec3& lmin, const ktm::fvec3& lmax) {
    ktm::fvec3 out_min{}, out_max{}, out_center{};  // out_max/center 此处不用
    world_aabb_from_local_bounds(t, lmin, lmax, out_min, out_max, out_center);
    return out_min.y;  // 最低点高度
}

// euler：弧度，顺序 XYZ；返回与 TRS 矩阵一致的单位四元数
inline ktm::fquat quat_from_model_euler(const ktm::fvec3& euler) {
    const ktm::fquat qx = ktm::fquat::from_angle_x(euler.x);  // 绕 X
    const ktm::fquat qy = ktm::fquat::from_angle_y(euler.y);  // 绕 Y
    const ktm::fquat qz = ktm::fquat::from_angle_z(euler.z);  // 绕 Z
    return qz * qy * qx;                                      // 组合旋转
}

// R：旋转矩阵；euler：输出的 XYZ 欧拉（弧度）
// KTM 使用列主序存储 R[col][row]，对 Rz·Ry·Rx 有 R[0][2] = -sin(y)
inline void euler_xyz_from_rot_mat(const ktm::fmat3x3& R, ktm::fvec3& euler) {
    const float sy = std::clamp(-R[0][2], -1.0f, 1.0f);  // sin(y)，clamp 防 NaN

    const float pi = 3.1415926535f;  // π

    if (sy > 0.9999f) {                          // 俯仰近 +90°，万向节锁
        euler.x = 0;                             // 俯仰锁定下 x 置 0
        euler.y = pi * 0.5f;                     // y = +π/2
        euler.z = std::atan2(R[1][0], R[1][1]);  // 用 atan2 定 z
    } else if (sy < -0.9999f) {                  // 俯仰近 -90°
        euler.x = 0;
        euler.y = -pi * 0.5f;
        euler.z = std::atan2(R[1][0], R[1][1]);
    } else {
        euler.y = std::asin(sy);  // 一般情形：求中间角
        euler.x = std::atan2(R[1][2], R[2][2]);
        euler.z = std::atan2(R[0][1], R[0][0]);
    }
}
// q：四元数缓存；euler：写回 Transform 的欧拉角
inline void sync_euler_from_orientation_quat(ktm::fquat& q, ktm::fvec3& euler) {
    if (q.r < 0.0f) {  // 实为同一旋转的另一表示
        q.i = -q.i;    // i 分量取反
        q.j = -q.j;    // j
        q.k = -q.k;    // k
        q.r = -q.r;    // r
    }
    euler_xyz_from_rot_mat(q.matrix3x3(), euler);  // 由旋转矩阵反解欧拉
}

// 显式积分四元数导数 dq/dt = 0.5*(0,ω)*q
inline void integrate_orientation_quat(ktm::fquat& q, const ktm::fvec3& omega_world, float dt) {
    const ktm::fquat wq = ktm::fquat::real_imag(0.0f, omega_world);  // 纯虚四元数装角速度
    const ktm::fquat dq = wq * q;                                    // 与 q 相乘得导出
    q.i += 0.5f * dt * dq.i;                                         // 累加 i 分量变化
    q.j += 0.5f * dt * dq.j;
    q.k += 0.5f * dt * dq.k;
    q.r += 0.5f * dt * dq.r;
    q = ktm::normalize(q);  // 保持单位四元数
}

// AABB 在方向 dir 上的极值点（近似接触用）
inline ktm::fvec3 aabb_support_world(const ktm::fvec3& center, const ktm::fvec3& half,
                                     const ktm::fvec3& dir) {
    return make_fvec3(
        center.x + (dir.x >= 0.0f ? half.x : -half.x),  // dir 指向 +X 时取右侧面
        center.y + (dir.y >= 0.0f ? half.y : -half.y),
        center.z + (dir.z >= 0.0f ? half.z : -half.z));
}

// 刚体上一点的世界系线速度 = 质心平动 + 转动项 ω×r
inline ktm::fvec3 velocity_at_point_world(const ktm::fvec3& v_com, const ktm::fvec3& omega_world,
                                          const ktm::fvec3& r_com_to_point) {
    const ktm::fvec3 wxr = ktm::cross(omega_world, r_com_to_point);        // 叉乘
    return make_fvec3(v_com.x + wxr.x, v_com.y + wxr.y, v_com.z + wxr.z);  // 矢量加
}

// 世界系向量左乘 I^{-1}（对角惯量模型 + 当前姿态 R）
inline ktm::fvec3 world_inertia_inv_apply(const ktm::fmat3x3& R_body_to_world,
                                          const ktm::fvec3& inertia_inv_body,
                                          const ktm::fvec3& w_world) {
    const ktm::fmat3x3 RT = ktm::transpose(R_body_to_world);  // 逆旋转（正交阵）
    ktm::fvec3 b = RT * w_world;                              // 世界→体
    b.x *= inertia_inv_body.x;                                // 体坐标乘以 1/Ix
    b.y *= inertia_inv_body.y;
    b.z *= inertia_inv_body.z;
    return R_body_to_world * b;  // 体→世界
}

// 本帧单个 mechanics 物体的碰撞/渲染用几何缓存
struct MechanicsWorldAABB {
    std::uintptr_t handle;               // mechanics 设备句柄键
    std::uintptr_t transform_handle;     // 几何上的 ModelTransform 句柄
    ktm::fvec3 min_world;                // 世界 AABB 最小角
    ktm::fvec3 max_world;                // 世界 AABB 最大角
    ktm::fvec3 center_world;             // AABB 中心（亦作 AABB 窄相参考点）
    ktm::fvec3 half_extents;             // 世界 AABB 半尺寸
    ktm::fvec3 local_min;                // mechanics 局部 min_xyz
    ktm::fvec3 local_max;                // mechanics 局部 max_xyz
    ktm::fvec3 obb_center;               // OBB 中心（世界）
    ktm::fvec3 obb_u, obb_v, obb_w;      // OBB 三个正交轴单位向量（世界）
    float obb_hu{}, obb_hv{}, obb_hw{};  // 对应轴上半轴长
    ktm::fmat3x3 rot_body_to_world{};    // 由预测四元数得到的旋转矩阵
    ktm::fvec3 inertia_inv_body{};       // 体坐标 (1/Ix,1/Iy,1/Iz)
    std::uint64_t model_id = 0;          // 对应的模型资源ID（用于碰撞网格查找）
};

// entry：读写 OBB 字段；t：用于把局部点变到世界
inline void build_mechanics_obb(MechanicsWorldAABB& entry, const Corona::ModelTransform& t) {
    const ktm::fvec3 c_l = make_fvec3(
        (entry.local_min.x + entry.local_max.x) * 0.5f,  // 局部盒中心 X
        (entry.local_min.y + entry.local_max.y) * 0.5f,
        (entry.local_min.z + entry.local_max.z) * 0.5f);
    const ktm::fvec3 e_l = make_fvec3(
        (entry.local_max.x - entry.local_min.x) * 0.5f,  // 沿局部 X 的半棱长
        (entry.local_max.y - entry.local_min.y) * 0.5f,
        (entry.local_max.z - entry.local_min.z) * 0.5f);
    entry.obb_center = transform_local_point_to_world(t, c_l);  // 盒心到世界
    ktm::fvec3 ax = vec3_sub(transform_local_point_to_world(t, vec3_add(c_l, make_fvec3(e_l.x, 0.f, 0.f))),
                             entry.obb_center);  // +局部 X 轴端点相对心的向量（世界）
    ktm::fvec3 ay = vec3_sub(transform_local_point_to_world(t, vec3_add(c_l, make_fvec3(0.f, e_l.y, 0.f))),
                             entry.obb_center);  // +Y
    ktm::fvec3 az = vec3_sub(transform_local_point_to_world(t, vec3_add(c_l, make_fvec3(0.f, 0.f, e_l.z))),
                             entry.obb_center);  // +Z
    const float lu = ktm::length(ax);            // 轴方向未归一长度
    const float lv = ktm::length(ay);
    const float lz = ktm::length(az);
    constexpr float obb_eps = 1e-8f;  // 退化盒厚度下限
    if (lu > obb_eps) {
        const float inv = 1.0f / lu;                                   // 归一化因子
        entry.obb_u = make_fvec3(ax.x * inv, ax.y * inv, ax.z * inv);  // 单位轴 u
        entry.obb_hu = lu;                                             // 半轴长取几何长度
    } else {
        entry.obb_u = make_fvec3(1.0f, 0.0f, 0.0f);  // 默认 X
        entry.obb_hu = obb_eps;                      // 极小半长避免除零
    }
    if (lv > obb_eps) {
        const float inv = 1.0f / lv;
        entry.obb_v = make_fvec3(ay.x * inv, ay.y * inv, ay.z * inv);
        entry.obb_hv = lv;
    } else {
        entry.obb_v = make_fvec3(0.0f, 1.0f, 0.0f);
        entry.obb_hv = obb_eps;
    }
    if (lz > obb_eps) {
        const float inv = 1.0f / lz;
        entry.obb_w = make_fvec3(az.x * inv, az.y * inv, az.z * inv);
        entry.obb_hw = lz;
    } else {
        entry.obb_w = make_fvec3(0.0f, 0.0f, 1.0f);
        entry.obb_hw = obb_eps;
    }
}

// OBB 投影到单位方向 L_unit 上的半长（分离轴定理里「半径」项）
inline float obb_radius_on_axis(float hu, float hv, float hw,
                                const ktm::fvec3& u, const ktm::fvec3& v, const ktm::fvec3& w,
                                const ktm::fvec3& L_unit) {
    return hu * std::abs(ktm::dot(u, L_unit))     // u 轴贡献
           + hv * std::abs(ktm::dot(v, L_unit))   // v 轴
           + hw * std::abs(ktm::dot(w, L_unit));  // w 轴
}

// 在方向 dir 上取 OBB 支撑点：c 为中心；u,v,w 轴与 hu,hv,hw 半长；沿 dir 取最远顶点
inline ktm::fvec3 obb_support_point(const ktm::fvec3& c,
                                    const ktm::fvec3& u, const ktm::fvec3& v, const ktm::fvec3& w,
                                    float hu, float hv, float hw,
                                    const ktm::fvec3& dir) {
    ktm::fvec3 p = c;                                       // 从中心出发
    const float su = (ktm::dot(u, dir) >= 0.f) ? hu : -hu;  // u 轴上取与 dir 同向或反向端点
    const float sv = (ktm::dot(v, dir) >= 0.f) ? hv : -hv;
    const float sw = (ktm::dot(w, dir) >= 0.f) ? hw : -hw;
    p = vec3_add(p, vec3_mul(u, su));  // 沿 u 平移 su*u
    p = vec3_add(p, vec3_mul(v, sv));
    p = vec3_add(p, vec3_mul(w, sw));
    return p;  // 角点之一
}

/*
 * OBB–OBB 窄相：15 轴 SAT（A 的三面法向、B 的三面法向、9 个边叉积）。
 * 返回最小穿透深度对应轴作为分离方向；法线取向为 A → B（与盒心连线一致）。
 */
inline bool sat_obb_obb(const ktm::fvec3& ca, const ktm::fvec3& ua, const ktm::fvec3& va, const ktm::fvec3& wa,
                        float hau, float hav, float haw,
                        const ktm::fvec3& cb, const ktm::fvec3& ub, const ktm::fvec3& vb, const ktm::fvec3& wb,
                        float hbu, float hbv, float hbw,
                        ktm::fvec3& out_normal, float& out_penetration) {
    constexpr float ax_eps = 1e-8f;                     // 轴长过短视为退化，跳过该轴
    const ktm::fvec3 d_cb = vec3_sub(cb, ca);           // B 中心相对 A 中心的位移
    float best_ov = std::numeric_limits<float>::max();  // 当前找到的最小正重叠（最深穿透轴）
    bool have_axis = false;                             // 是否至少成功检测过一条有效轴
    ktm::fvec3 best_L = make_fvec3(1.0f, 0.0f, 0.0f);   // 最优分离轴方向（单位向量）

    // 在候选轴 Lraw 上做 1D SAT：两 OBB 在轴上的投影区间若不相交则整体分离
    auto test_axis = [&](const ktm::fvec3& Lraw) -> bool {
        const float len = ktm::length(Lraw);  // 未归一轴长
        if (len < ax_eps) {                   // 叉积近似零向量
            return true;                      // 不计入分离轴，视为通过
        }
        const float inv = 1.0f / len;                                               // 归一化因子
        const ktm::fvec3 L = make_fvec3(Lraw.x * inv, Lraw.y * inv, Lraw.z * inv);  // 单位轴
        const float rA = obb_radius_on_axis(hau, hav, haw, ua, va, wa, L);          // A 投影半宽
        const float rB = obb_radius_on_axis(hbu, hbv, hbw, ub, vb, wb, L);          // B 投影半宽
        const float cA = ktm::dot(ca, L);                                           // A 中心在轴上坐标
        const float cB = ktm::dot(cb, L);                                           // B 中心在轴上坐标
        const float minA = cA - rA;                                                 // A 投影区间左端
        const float maxA = cA + rA;                                                 // A 投影区间右端
        const float minB = cB - rB;                                                 // B 左端
        const float maxB = cB + rB;                                                 // B 右端
        const float overlap = std::min(maxA, maxB) - std::max(minA, minB);          // 两区间重叠长度
        if (overlap <= 0.f) {                                                       // 存在分离轴
            return false;                                                           // 无事相交
        }
        if (overlap < best_ov) {  // 记录重叠更小的轴（更接近分离）
            best_ov = overlap;
            best_L = L;
            have_axis = true;
        }
        return true;  // 本轴未排除相交
    };

    if (!test_axis(ua)) return false;  // A 的三个面法向
    if (!test_axis(va)) return false;
    if (!test_axis(wa)) return false;
    if (!test_axis(ub)) return false;  // B 的三个面法向
    if (!test_axis(vb)) return false;
    if (!test_axis(wb)) return false;

    const ktm::fvec3 crosses[9] = {// 边与边的叉积方向，共 9 条
                                   ktm::cross(ua, ub), ktm::cross(ua, vb), ktm::cross(ua, wb),
                                   ktm::cross(va, ub), ktm::cross(va, vb), ktm::cross(va, wb),
                                   ktm::cross(wa, ub), ktm::cross(wa, vb), ktm::cross(wa, wb)};
    for (const ktm::fvec3& cax : crosses) {  // 逐条测试叉积轴
        if (!test_axis(cax)) {
            return false;
        }
    }

    if (!have_axis) {  // 理论上不应发生：无有效轴却通过全部测试
        return false;
    }
    if (ktm::dot(best_L, d_cb) < 0.f) {  // 令 best_L 与 A→B 同向，作为 A→B 法线
        best_L = make_fvec3(-best_L.x, -best_L.y, -best_L.z);
    }
    out_normal = best_L;        // 输出接触法线（单位向量）
    out_penetration = best_ov;  // 输出沿该轴穿透深度估计
    return true;
}

// 碰撞对哈希（用于 unordered_set 去重）
struct PairHash {
    std::size_t operator()(const std::pair<std::uintptr_t, std::uintptr_t>& p) const noexcept {
        // Fibonacci hashing 混合
        std::size_t h1 = std::hash<std::uintptr_t>{}(p.first);
        std::size_t h2 = std::hash<std::uintptr_t>{}(p.second);
        h1 ^= h2 + 0x9e3779b97f4a7c15ULL + (h1 << 6) + (h1 >> 2);
        return h1;
    }
};

// 上一帧活跃碰撞对（用于检测碰撞开始/结束）
static std::unordered_set<std::pair<std::uintptr_t, std::uintptr_t>, PairHash> g_prev_active_collisions;

// 记录每个物体最后一次调用 on_move_callback 的时间（秒）
static std::unordered_map<std::uintptr_t, float> g_handle_to_last_move_callback_time;
// 移动回调最小间隔时间（秒）
constexpr float kMoveCallbackMinInterval = 0.1f;
// 全局模拟时间（秒）
static float g_global_simulation_time = 0.0f;

// 记录每个物体最后一次调用 on_move_callback 时所在的位置
static std::unordered_map<std::uintptr_t, ktm::fvec3> g_handle_to_last_move_callback_pos;
// 移动回调最小位移阈值（单位：米/坐标单位）
constexpr float kMoveCallbackMinDistance = 0.1f;

// 轴锁定位掩码常量
constexpr uint8_t kLockAxisX = 0b001;
constexpr uint8_t kLockAxisY = 0b010;
constexpr uint8_t kLockAxisZ = 0b100;

// ========== 延迟回调队列（同步执行，避免跨线程竞争） ==========
static std::vector<std::function<void()>> g_deferred_move_callbacks;

struct DeferredCollisionCallback {
	std::function<void(std::uintptr_t, bool, const std::array<float, 3>&, const std::array<float, 3>&)> callback;
	std::uintptr_t other_actor;
	bool is_start;
	std::array<float, 3> normal;
	std::array<float, 3> point;
};
static std::vector<DeferredCollisionCallback> g_deferred_collision_callbacks;

static std::atomic<bool> g_shutdown_requested{false};

// 注意：八叉树实现已迁移到 include/corona/spatial/octree.h，由 GeometrySystem 持有并维护。
// MechanicsSystem 仅作为消费者使用（宽相候选对生成仍可复用该通用实现）。

// 以下全局变量仅由 MechanicsSystem::update_physics() 访问（单线程）
// 如需跨系统读取，请通过 EventBus/EventStream 传递
static std::unordered_map<std::uintptr_t, ktm::fvec3> g_handle_to_velocity;       // 线速度 m/s
static std::unordered_map<std::uintptr_t, ktm::fvec3> g_handle_to_angular_vel;    // 角速度 rad/s 世界系
static std::unordered_map<std::uintptr_t, ktm::fquat> g_handle_orientation_quat;  // 与欧拉同步的朝向
static std::unordered_map<std::uintptr_t, bool> g_handle_to_sleeping;             // true 则本帧不积分
static std::unordered_map<std::uintptr_t, float> g_handle_to_sleep_timer;         // 低速累计时长

// 轴锁定缓存（每帧从 MechanicsDevice 刷新）
static std::unordered_map<std::uintptr_t, uint8_t> g_handle_to_linear_lock;   // 线性轴锁定位掩码
static std::unordered_map<std::uintptr_t, uint8_t> g_handle_to_angular_lock;  // 角度轴锁定位掩码

// ============================================================================
// 碰撞网格（基于最低级 LOD 的三角形碰撞检测）
// ============================================================================

/// 碰撞网格：存储局部空间顶点和三角形索引
struct CollisionMesh {
    std::vector<ktm::fvec3> vertices;                     // 局部空间顶点
    std::vector<std::array<std::uint16_t, 3>> triangles;  // 三角形索引三元组
    float min_local_y = 0.0f;                             // 最低点Y（精确地板碰撞）
};

/// 碰撞网格缓存（key = model_id，同模型多实例共享）
static std::unordered_map<std::uint64_t, CollisionMesh> g_collision_mesh_cache;

/// 三角形碰撞检测结果
struct TriangleContactResult {
    bool has_contact = false;
    ktm::fvec3 normal;         // 碰撞法线（从 A 指向 B）
    float penetration = 0.0f;  // 穿透深度
    ktm::fvec3 contact_point;  // 接触点
};

// ============================================================================
// 碰撞网格加载
// ============================================================================

/// 从 Resource 层加载最低级 LOD 碰撞网格
/// 返回 true 表示成功加载（或已在缓存中）
bool ensure_collision_mesh(std::uint64_t model_id) {
    if (model_id == 0) return false;
    if (g_collision_mesh_cache.count(model_id)) return true;

    auto scene = Corona::Resource::ResourceManager::get_instance()
                     .acquire_read<Corona::Resource::Scene>(model_id);
    if (!scene) return false;

    CollisionMesh mesh;
    std::uint16_t vertex_offset = 0;

    for (std::uint32_t mi = 0; mi < static_cast<std::uint32_t>(scene->data.meshes.size()); ++mi) {
        const std::vector<Corona::Resource::Vertex>* src_verts = nullptr;
        const std::vector<std::uint16_t>* src_indices = nullptr;

        std::uint32_t lod_count = scene->get_mesh_lod_count(mi);
        if (lod_count > 0) {
            // 取最后一级 LOD（最简化）
            const auto& lod = scene->get_mesh_lod(mi, lod_count - 1);
            src_verts = &lod.vertices;
            src_indices = &lod.indices;
        } else {
            // 无 LOD，回退原始网格
            src_verts = &scene->get_mesh_vertices(mi);
            src_indices = &scene->get_mesh_indices(mi);
        }

        if (!src_verts || src_verts->empty() || !src_indices || src_indices->empty()) continue;

        // 三角形数过多时跳过此 mesh（降级为 AABB）
        constexpr std::size_t kMaxTrianglesPerMesh = 500;
        if (src_indices->size() / 3 > kMaxTrianglesPerMesh && lod_count == 0) continue;

        // 复制顶点
        for (const auto& v : *src_verts) {
            ktm::fvec3 pos;
            pos.x = v.position[0];
            pos.y = v.position[1];
            pos.z = v.position[2];
            mesh.vertices.push_back(pos);
        }

        // 复制三角形索引（加偏移）
        for (std::size_t i = 0; i + 2 < src_indices->size(); i += 3) {
            mesh.triangles.push_back({
                static_cast<std::uint16_t>((*src_indices)[i] + vertex_offset),
                static_cast<std::uint16_t>((*src_indices)[i + 1] + vertex_offset),
                static_cast<std::uint16_t>((*src_indices)[i + 2] + vertex_offset),
            });
        }

        vertex_offset = static_cast<std::uint16_t>(mesh.vertices.size());
    }

    if (mesh.vertices.empty() || mesh.triangles.empty()) return false;

    // 预计算最低点Y
    mesh.min_local_y = mesh.vertices[0].y;
    for (const auto& v : mesh.vertices) {
        mesh.min_local_y = std::min(mesh.min_local_y, v.y);
    }

    g_collision_mesh_cache[model_id] = std::move(mesh);
    return true;
}

/// 获取 mechanics handle 对应的 model_id
std::uint64_t get_model_id_for_mechanics(std::uintptr_t mech_handle) {
    auto& mechanics_storage = Corona::SharedDataHub::instance().mechanics_storage();
    auto& geometry_storage = Corona::SharedDataHub::instance().geometry_storage();
    auto& model_resource_storage = Corona::SharedDataHub::instance().model_resource_storage();

    auto m_acc = mechanics_storage.try_acquire_read(mech_handle);
    if (!m_acc) return 0;
    auto geom_acc = geometry_storage.try_acquire_read(m_acc->geometry_handle);
    if (!geom_acc) return 0;
    auto res_acc = model_resource_storage.try_acquire_read(geom_acc->model_resource_handle);
    if (!res_acc) return 0;
    return res_acc->model_id;
}

// ============================================================================
// 三角形工具函数
// ============================================================================

inline ktm::fvec3 cross(const ktm::fvec3& a, const ktm::fvec3& b) {
    return make_fvec3(
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x);
}

inline float dot(const ktm::fvec3& a, const ktm::fvec3& b) {
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

inline ktm::fvec3 sub(const ktm::fvec3& a, const ktm::fvec3& b) {
    return make_fvec3(a.x - b.x, a.y - b.y, a.z - b.z);
}

inline float vec_length(const ktm::fvec3& v) {
    return std::sqrt(v.x * v.x + v.y * v.y + v.z * v.z);
}

inline ktm::fvec3 normalize_safe(const ktm::fvec3& v) {
    float len = vec_length(v);
    if (len < 1e-8f) return make_fvec3(0.0f, 1.0f, 0.0f);
    return make_fvec3(v.x / len, v.y / len, v.z / len);
}

/// 将局部空间碰撞网格顶点变换到世界空间
void transform_vertices_to_world(
    const std::vector<ktm::fvec3>& local_verts,
    const Corona::ModelTransform& tx,
    std::vector<ktm::fvec3>& world_verts) {
    world_verts.resize(local_verts.size());

    // 如果有旋转，使用完整矩阵变换
    bool has_rotation = (std::abs(tx.euler_rotation.x) > 1e-6f ||
                         std::abs(tx.euler_rotation.y) > 1e-6f ||
                         std::abs(tx.euler_rotation.z) > 1e-6f);

    if (has_rotation) {
        ktm::fmat4x4 mat = tx.compute_matrix();
        for (std::size_t i = 0; i < local_verts.size(); ++i) {
            const auto& v = local_verts[i];
            // mat * (v, 1)
            world_verts[i] = make_fvec3(
                mat[0][0] * v.x + mat[1][0] * v.y + mat[2][0] * v.z + mat[3][0],
                mat[0][1] * v.x + mat[1][1] * v.y + mat[2][1] * v.z + mat[3][1],
                mat[0][2] * v.x + mat[1][2] * v.y + mat[2][2] * v.z + mat[3][2]);
        }
    } else {
        // 无旋转：简单缩放+平移
        for (std::size_t i = 0; i < local_verts.size(); ++i) {
            const auto& v = local_verts[i];
            world_verts[i] = make_fvec3(
                v.x * tx.scale.x + tx.position.x,
                v.y * tx.scale.y + tx.position.y,
                v.z * tx.scale.z + tx.position.z);
        }
    }
}

// ============================================================================
// Möller 三角形-三角形相交测试
// 基于分离轴定理 (SAT) 的实现
// ============================================================================

/// 将三角形的三个顶点投影到轴上，返回 [min, max]
inline void project_triangle(const ktm::fvec3& axis,
                             const ktm::fvec3& v0, const ktm::fvec3& v1, const ktm::fvec3& v2,
                             float& out_min, float& out_max) {
    float d0 = dot(axis, v0);
    float d1 = dot(axis, v1);
    float d2 = dot(axis, v2);
    out_min = std::min({d0, d1, d2});
    out_max = std::max({d0, d1, d2});
}

/// 测试两个三角形在给定轴上的投影是否分离
/// 若不分离，返回重叠量
inline bool test_axis(const ktm::fvec3& axis,
                      const ktm::fvec3 a[3], const ktm::fvec3 b[3],
                      float& overlap) {
    float axis_len_sq = dot(axis, axis);
    if (axis_len_sq < 1e-12f) {
        // 退化轴（平行边），不作为分离轴
        overlap = std::numeric_limits<float>::max();
        return false;  // 不分离
    }

    float a_min, a_max, b_min, b_max;
    project_triangle(axis, a[0], a[1], a[2], a_min, a_max);
    project_triangle(axis, b[0], b[1], b[2], b_min, b_max);

    constexpr float sep_eps = 1e-5f;  // 浮点容差，避免擦边接触被误判为分离
    if (a_max < b_min - sep_eps || b_max < a_min - sep_eps) {
        return true;  // 分离
    }

    // 计算重叠深度
    float inv_len = 1.0f / std::sqrt(axis_len_sq);
    overlap = (std::min(a_max, b_max) - std::max(a_min, b_min)) * inv_len;
    return false;  // 不分离
}

/// SAT 三角形-三角形相交测试
/// 返回是否相交，并输出穿透法线和深度
bool triangle_triangle_sat(const ktm::fvec3 tri_a[3], const ktm::fvec3 tri_b[3],
                           ktm::fvec3& out_normal, float& out_depth) {
    // 计算三角形边向量
    ktm::fvec3 edge_a[3] = {
        sub(tri_a[1], tri_a[0]),
        sub(tri_a[2], tri_a[1]),
        sub(tri_a[0], tri_a[2])};
    ktm::fvec3 edge_b[3] = {
        sub(tri_b[1], tri_b[0]),
        sub(tri_b[2], tri_b[1]),
        sub(tri_b[0], tri_b[2])};

    // 面法线
    ktm::fvec3 normal_a = cross(edge_a[0], edge_a[1]);
    ktm::fvec3 normal_b = cross(edge_b[0], edge_b[1]);

    float min_overlap = std::numeric_limits<float>::max();
    ktm::fvec3 min_axis = make_fvec3(0.0f, 1.0f, 0.0f);

    // 测试轴：面法线A
    float overlap;
    if (test_axis(normal_a, tri_a, tri_b, overlap)) return false;
    if (overlap < min_overlap) {
        min_overlap = overlap;
        min_axis = normal_a;
    }

    // 测试轴：面法线B
    if (test_axis(normal_b, tri_a, tri_b, overlap)) return false;
    if (overlap < min_overlap) {
        min_overlap = overlap;
        min_axis = normal_b;
    }

    // 测试轴：9 个边叉积
    for (int i = 0; i < 3; ++i) {
        for (int j = 0; j < 3; ++j) {
            ktm::fvec3 axis = cross(edge_a[i], edge_b[j]);
            if (test_axis(axis, tri_a, tri_b, overlap)) return false;
            if (overlap < min_overlap) {
                min_overlap = overlap;
                min_axis = axis;
            }
        }
    }

    // 所有轴均未分离 → 相交
    out_normal = normalize_safe(min_axis);
    out_depth = min_overlap;
    return true;
}

/// 执行两个碰撞网格之间的三角形精确碰撞检测
/// world_verts_a/b: 已变换到世界空间的顶点
/// mesh_a/b: 碰撞网格（提供三角形索引）
/// result: 输出接触信息
void triangle_narrowphase(
    const std::vector<ktm::fvec3>& world_verts_a,
    const CollisionMesh& mesh_a,
    const std::vector<ktm::fvec3>& world_verts_b,
    const CollisionMesh& mesh_b,
    const ktm::fvec3& center_a,
    const ktm::fvec3& center_b,
    TriangleContactResult& result) {
    result.has_contact = false;
    float best_depth = 0.0f;
    ktm::fvec3 best_normal = make_fvec3(0.0f, 1.0f, 0.0f);
    ktm::fvec3 best_point = make_fvec3(0.0f, 0.0f, 0.0f);
    int contact_count = 0;
    ktm::fvec3 contact_sum = make_fvec3(0.0f, 0.0f, 0.0f);

    for (const auto& tri_a_idx : mesh_a.triangles) {
        // 三角形 A 的世界空间顶点
        const ktm::fvec3& a0 = world_verts_a[tri_a_idx[0]];
        const ktm::fvec3& a1 = world_verts_a[tri_a_idx[1]];
        const ktm::fvec3& a2 = world_verts_a[tri_a_idx[2]];

        // 三角形 A 的 mini-AABB
        ktm::fvec3 a_min = make_fvec3(
            std::min({a0.x, a1.x, a2.x}), std::min({a0.y, a1.y, a2.y}), std::min({a0.z, a1.z, a2.z}));
        ktm::fvec3 a_max = make_fvec3(
            std::max({a0.x, a1.x, a2.x}), std::max({a0.y, a1.y, a2.y}), std::max({a0.z, a1.z, a2.z}));

        for (const auto& tri_b_idx : mesh_b.triangles) {
            // 三角形 B 的世界空间顶点
            const ktm::fvec3& b0 = world_verts_b[tri_b_idx[0]];
            const ktm::fvec3& b1 = world_verts_b[tri_b_idx[1]];
            const ktm::fvec3& b2 = world_verts_b[tri_b_idx[2]];

            // Mini-AABB 预筛选
            ktm::fvec3 b_min = make_fvec3(
                std::min({b0.x, b1.x, b2.x}), std::min({b0.y, b1.y, b2.y}), std::min({b0.z, b1.z, b2.z}));
            ktm::fvec3 b_max = make_fvec3(
                std::max({b0.x, b1.x, b2.x}), std::max({b0.y, b1.y, b2.y}), std::max({b0.z, b1.z, b2.z}));

            if (!aabb_overlap(a_min, a_max, b_min, b_max)) continue;

            // SAT 精确测试
            ktm::fvec3 tri_a_verts[3] = {a0, a1, a2};
            ktm::fvec3 tri_b_verts[3] = {b0, b1, b2};

            ktm::fvec3 normal;
            float depth;
            if (!triangle_triangle_sat(tri_a_verts, tri_b_verts, normal, depth)) continue;

            // 累积接触点（两三角形中心的平均）
            ktm::fvec3 tri_center = make_fvec3(
                (a0.x + a1.x + a2.x + b0.x + b1.x + b2.x) / 6.0f,
                (a0.y + a1.y + a2.y + b0.y + b1.y + b2.y) / 6.0f,
                (a0.z + a1.z + a2.z + b0.z + b1.z + b2.z) / 6.0f);
            contact_sum.x += tri_center.x;
            contact_sum.y += tri_center.y;
            contact_sum.z += tri_center.z;
            ++contact_count;

            // 取穿透最深的法线和深度（最深接触代表主碰撞方向）
            if (depth > best_depth) {
                best_depth = depth;
                best_normal = normal;
                best_point = tri_center;
            }
        }
    }

    if (contact_count == 0) return;

    result.has_contact = true;
    result.penetration = best_depth;
    result.contact_point = make_fvec3(
        contact_sum.x / static_cast<float>(contact_count),
        contact_sum.y / static_cast<float>(contact_count),
        contact_sum.z / static_cast<float>(contact_count));

    // 确保法线方向从 A 指向 B
    ktm::fvec3 a_to_b = sub(center_b, center_a);
    if (dot(best_normal, a_to_b) < 0.0f) {
        best_normal = make_fvec3(-best_normal.x, -best_normal.y, -best_normal.z);
    }
    result.normal = best_normal;
}

}  // namespace

namespace Corona::Systems {

bool MechanicsSystem::initialize(Kernel::ISystemContext* ctx) {
    m_ctx = ctx;
    g_shutdown_requested = false;

    // GeometrySystem 指针缓存移到 update_physics() 首次调用时完成，
    // 因为 initialize() 在 SystemManager::initialize_all() 的锁内调用，
    // 此时 get_system() 会尝试重入同一把非递归 mutex，导致未定义行为/崩溃。

    CFW_LOG_INFO("MechanicsSystem initialized");
    return true;
}

void MechanicsSystem::update() {
    if (g_shutdown_requested.load(std::memory_order_acquire)) {
        return;
    }

    // 用高精度计时器测量真实 dt
    auto now = std::chrono::steady_clock::now();
    if (m_first_update) {
        m_last_update_time = now;
        m_first_update = false;
        update_physics();
        return;
    }

    float actual_dt = std::chrono::duration<float>(now - m_last_update_time).count();
    m_last_update_time = now;

    // 钳制防止巨幅跳帧
    const float max_frame_time = 0.1f;
    actual_dt = std::min(actual_dt, max_frame_time);

    m_time_accumulator += actual_dt;

    // 固定步长迭代（与 update_physics 内的 fixed_dt 保持一致，默认 1/60）
    const float fixed_dt = 1.0f / 60.0f;
    while (m_time_accumulator >= fixed_dt &&
           !g_shutdown_requested.load(std::memory_order_acquire)) {
        update_physics();
        m_time_accumulator -= fixed_dt;
    }
}

void MechanicsSystem::stop() {
    g_shutdown_requested.store(true, std::memory_order_release);
    Kernel::SystemBase::stop();
}

void MechanicsSystem::shutdown() {
    // 标记关闭请求，不再接受新的回调任务
    g_shutdown_requested.store(true, std::memory_order_release);

    // 清空延迟回调队列
    g_deferred_move_callbacks.clear();
    g_deferred_collision_callbacks.clear();

    g_prev_active_collisions.clear();
    g_handle_to_velocity.clear();
    g_collision_mesh_cache.clear();
    g_handle_to_angular_vel.clear();
    g_handle_orientation_quat.clear();
    g_handle_to_sleeping.clear();
    g_handle_to_sleep_timer.clear();
    g_handle_to_linear_lock.clear();
    g_handle_to_angular_lock.clear();
    g_handle_to_last_move_callback_time.clear();
    g_handle_to_last_move_callback_pos.clear();
    g_global_simulation_time = 0.0f;
    CFW_LOG_INFO("MechanicsSystem shutdown, all caches cleared");
}

// 物理主循环（单帧）：搜集物体 → 积分外力(重力/阻尼) → 建世界 AABB → 粗/细碰撞改速度 → 积分位姿 → 地板 → 休眠 → 清理缓存
void MechanicsSystem::update_physics() {
    // 如果正在关闭，不再处理新的物理更新
    if (g_shutdown_requested.load(std::memory_order_acquire)) {
        return;
    }

    // 首次调用时懒缓存 GeometrySystem 指针（不在 initialize() 中做，
    // 因为 initialize() 在 SystemManager::initialize_all() 的锁内执行，
    // get_system() 会重入同一把非递归 mutex）。
    if (!m_geometry_sys && m_ctx) {
        m_geometry_sys = dynamic_cast<GeometrySystem*>(m_ctx->get_system("Geometry"));
    }

    // 常量：时间步、摩擦、休眠、惯量下限等（可按手感调参）
    const float floor_eps = 0.01f;                                       // 地板碰撞容差
    const float low_vel_threshold = 0.05f;                               // 低速衰减阈值
    const float min_valid_dt = 1.0f / 120.0f;                            // 最小有效时间步
    const float max_valid_dt = 1.0f / 30.0f;                             // 最大有效时间步
    const float zero_vel_threshold = 0.01f;                              // 速度归零阈值
    const float friction_coeff = 0.35f;                                  // 统一摩擦系数
    const float sleep_threshold = 0.05f;                                 // 休眠速度阈值
    const float sleep_threshold_sq = sleep_threshold * sleep_threshold;  // 休眠速度阈值平方
    const float sleep_time_needed = 0.4f;                                // 静止多久后休眠
    const float min_inertia = 0.0001f;                                   // 最小转动惯量，防止除零
    const float rot_damping_factor = 0.97f;                              // 基础旋转阻尼系数

    // 本帧临时表：质量/阻尼/恢复系数/碰撞开关
    std::unordered_map<std::uintptr_t, float> handle_to_mass;
    std::unordered_map<std::uintptr_t, float> handle_to_damping;
    std::unordered_map<std::uintptr_t, float> handle_to_restitution;
    std::unordered_map<std::uintptr_t, bool> handle_to_collision_enabled;  // 碰撞检测开关缓存
    std::unordered_map<std::uintptr_t, std::uintptr_t> mech_to_actor;

    // --- 从 SharedDataHub 取各存储的引用（几何、变换、场景、环境等）---
    auto& mechanics_storage = SharedDataHub::instance().mechanics_storage();            // mechanics 组件数据
    auto& geometry_storage = SharedDataHub::instance().geometry_storage();              // 网格/包围体句柄
    auto& transform_storage = SharedDataHub::instance().model_transform_storage();      // 位姿写回目标
    auto& model_resource_storage = SharedDataHub::instance().model_resource_storage();  // 模型资源数据
    const auto& scene_storage = SharedDataHub::instance().scene_storage();              // 场景与 actor 列表（const → cbegin/cend 读锁遍历）
    auto& actor_storage = SharedDataHub::instance().actor_storage();
    auto& profile_storage = SharedDataHub::instance().profile_storage();          // actor→mechanics 映射
    auto& environment_storage = SharedDataHub::instance().environment_storage();  // 全局 dt/重力等

    float fixed_dt = 1.0f / 60.0f;                       // 积分步长秒；可被 environment 覆盖
    ktm::fvec3 gravity = make_fvec3(0.0f, -9.8f, 0.0f);  // m/s²
    float floor_restitution = 0.6f;                      // 地板法向弹性系数 0..1
    float floor_y = 0.0f;                                // 无穷大水平面高度

    std::vector<std::uintptr_t> mechanics_handles;  // 本帧参与物理的 mechanics 去重列表
    mechanics_handles.reserve(64);
    std::vector<std::uintptr_t> scene_handles;  // 参与遍历的 scene 指针键，用于写 scene AABB
    scene_handles.reserve(4);

    // --- 阶段 1：遍历场景 → 读环境(gravity/floor/dt) → 展开 Actor/Profile → 收集 mechanics_handle ---
    for (const auto& scene : scene_storage) {
        if (g_shutdown_requested.load(std::memory_order_acquire)) {
            return;
        }
        if (!scene.enabled)
            continue;

        scene_handles.push_back(reinterpret_cast<std::uintptr_t>(&scene));

        if (!scene.simulation_enabled)
            continue;

        // 若绑定了 environment：覆盖重力、地板参数，并钳制 fixed_dt
        if (scene.environment != 0) {
            if (auto env = environment_storage.try_acquire_read(scene.environment)) {
                gravity = env->gravity;
                floor_y = env->floor_y;
                floor_restitution = env->floor_restitution;
                // 限制时间步范围，防止外部传入异常值导致抖动
                fixed_dt = std::clamp(env->fixed_dt, min_valid_dt, max_valid_dt);
            }
        }

        for (auto actor_handle : scene.actor_handles) {
            if (g_shutdown_requested.load(std::memory_order_acquire)) {
                return;
            }
            if (auto actor = actor_storage.try_acquire_read(actor_handle)) {
                for (auto profile_handle : actor->profile_handles) {
                    if (g_shutdown_requested.load(std::memory_order_acquire)) {
                        return;
                    }
                    if (auto profile = profile_storage.try_acquire_read(profile_handle)) {
                        if (auto h = profile->mechanics_handle) {
                            // 读 MechanicsDevice：检查物理开关 + 质量/阻尼/恢复；读失败则用默认值
                            // 轴锁变化检测变量（需在 if/else 外声明，供后续唤醒逻辑使用）
                            uint8_t old_linear = g_handle_to_linear_lock.count(h) ? g_handle_to_linear_lock[h] : 0;
                            uint8_t old_angular = g_handle_to_angular_lock.count(h) ? g_handle_to_angular_lock[h] : 0;
                            uint8_t new_linear = 0;
                            uint8_t new_angular = 0;
                            if (auto m_acc = mechanics_storage.try_acquire_read(h)) {
                                if (!m_acc->physics_enabled) continue;  // 物理已禁用，跳过本 mechanics
                                handle_to_mass[h] = m_acc->mass;
                                handle_to_damping[h] = m_acc->damping;
                                handle_to_restitution[h] = m_acc->restitution;
                                handle_to_collision_enabled[h] = m_acc->bEnableCollision;  // 缓存碰撞开关
                                new_linear = m_acc->linear_lock_mask;
                                new_angular = m_acc->angular_lock_mask;
                                g_handle_to_linear_lock[h] = new_linear;    // 缓存线性轴锁
                                g_handle_to_angular_lock[h] = new_angular;  // 缓存角度轴锁
                            } else {
                                handle_to_mass[h] = 1.0f;
                                handle_to_damping[h] = 0.99f;
                                handle_to_restitution[h] = 0.8f;
                                handle_to_collision_enabled[h] = true;  // 读失败时默认开启碰撞
                                g_handle_to_linear_lock[h] = 0;         // 读失败时默认不锁任何轴
                                g_handle_to_angular_lock[h] = 0;
                            }

                            mechanics_handles.push_back(h);
                            mech_to_actor[h] = actor_handle;

                            // 首次见到该 mechanics：初始化全局缓存中的线速度、角速度、休眠计时
                            if (g_handle_to_velocity.find(h) == g_handle_to_velocity.end()) {
                                g_handle_to_velocity[h] = make_fvec3(0.0f, 0.0f, 0.0f);
                                g_handle_to_angular_vel[h] = make_fvec3(0.0f, 0.0f, 0.0f);
                                g_handle_to_sleeping[h] = false;
                                g_handle_to_sleep_timer[h] = 0.0f;
                            }

                            // 轴锁解除时唤醒休眠体：若锁定位从 1→0（解锁），休眠体需恢复物理响应
                            if (((old_linear & ~new_linear) != 0 || (old_angular & ~new_angular) != 0) && g_handle_to_sleeping[h]) {
                                g_handle_to_sleeping[h] = false;
                                g_handle_to_sleep_timer[h] = 0.0f;
                            }

                            // 质量防护：避免0质量导致碰撞冲量计算异常
                            if (handle_to_mass[h] < 0.0001f) {
                                handle_to_mass[h] = 1.0f;
                            }
                        }
                    }
                }
            }
        }
    }

    std::sort(mechanics_handles.begin(), mechanics_handles.end());                                                      // 排序使 unique 有效
    mechanics_handles.erase(std::unique(mechanics_handles.begin(), mechanics_handles.end()), mechanics_handles.end());  // 去重

    if (mechanics_handles.empty()) {
        return;  // 无物体则整帧跳过
    }

    g_global_simulation_time += fixed_dt;

    // --- 阶段 2：半隐式前推速度（仅非休眠体）：先阻尼旧速度，再叠加重力加速度 ---
    for (std::uintptr_t h : mechanics_handles) {  // 对存活列表逐个施力
        if (g_shutdown_requested.load(std::memory_order_acquire)) {
            return;
        }
        if (g_handle_to_sleeping[h]) continue;    // 休眠体本阶段不改速度

        float damping = handle_to_damping[h];   // 线性阻尼乘子（以 60Hz 为基准的每步保留系数）
        auto& av = g_handle_to_angular_vel[h];  // 可修改的角速度引用

        // 1. 先对上一帧遗留的速度施加阻尼（指数衰减，与 dt 无关）
        const float effective_damping = std::pow(damping, fixed_dt * 60.0f);
        g_handle_to_velocity[h].x *= effective_damping;
        g_handle_to_velocity[h].y *= effective_damping;
        g_handle_to_velocity[h].z *= effective_damping;

        // 2. 再叠加本帧重力加速度（不被阻尼衰减）
        g_handle_to_velocity[h].x += gravity.x * fixed_dt;
        g_handle_to_velocity[h].y += gravity.y * fixed_dt;
        g_handle_to_velocity[h].z += gravity.z * fixed_dt;

        // 3. 角速度阻尼（指数衰减）
        const float effective_rot_damping = std::pow(
            std::max(damping * rot_damping_factor, 0.9f), fixed_dt * 60.0f);
        av.x *= effective_rot_damping;
        av.y *= effective_rot_damping;
        av.z *= effective_rot_damping;
    }

    // --- 阶段 2b：轴锁定强制执行 — 将已锁轴的速度/角速度分量清零 ---
    for (std::uintptr_t h : mechanics_handles) {
        if (g_handle_to_sleeping[h]) continue;
        uint8_t lin_lock = g_handle_to_linear_lock[h];
        if (lin_lock & kLockAxisX) g_handle_to_velocity[h].x = 0.0f;
        if (lin_lock & kLockAxisY) g_handle_to_velocity[h].y = 0.0f;
        if (lin_lock & kLockAxisZ) g_handle_to_velocity[h].z = 0.0f;

        uint8_t ang_lock = g_handle_to_angular_lock[h];
        if (ang_lock & kLockAxisX) g_handle_to_angular_vel[h].x = 0.0f;
        if (ang_lock & kLockAxisY) g_handle_to_angular_vel[h].y = 0.0f;
        if (ang_lock & kLockAxisZ) g_handle_to_angular_vel[h].z = 0.0f;
    }

    // --- 阶段 3：为每个 mechanics 读几何/变换 → 首遇则建四元数朝向 → 预测位姿 → 世界 AABB + 长方体对角惯量（世界系冲量用）---
    std::vector<MechanicsWorldAABB> mechanics_data;
    mechanics_data.reserve(mechanics_handles.size());
    std::unordered_map<std::uintptr_t, std::size_t> handle_to_index;

    for (std::uintptr_t h : mechanics_handles) {         // 为每个力学体准备碰撞与惯量数据
        if (g_shutdown_requested.load(std::memory_order_acquire)) {
            return;
        }
        auto m_acc = mechanics_storage.try_acquire_read(h);  // mechanics 组件读锁
        if (!m_acc) continue;                            // 无数据则跳过
        const auto& m = *m_acc;                          // 其 min/max、geometry_handle

        auto geom_acc = geometry_storage.try_acquire_read(m.geometry_handle);
        if (!geom_acc) continue;

        auto tx_acc = transform_storage.try_acquire_read(geom_acc->transform_handle);
        if (!tx_acc) continue;
        const auto& t = *tx_acc;  // 只读当前变换（复制后做预测）

        ktm::fvec3 e_local = make_fvec3(  // mechanics 局部半棱长
            (m.max_xyz.x - m.min_xyz.x) * 0.5f,
            (m.max_xyz.y - m.min_xyz.y) * 0.5f,
            (m.max_xyz.z - m.min_xyz.z) * 0.5f);

        // 获取 model_id 用于碰撞网格查找
        std::uint64_t entry_model_id = 0;
        if (auto res_acc = model_resource_storage.try_acquire_read(geom_acc->model_resource_handle)) {
            entry_model_id = res_acc->model_id;
        }

        MechanicsWorldAABB entry;  // 本物体本帧用的缓存结构
        entry.handle = h;
        entry.transform_handle = geom_acc->transform_handle;  // 之后写位置修正用同一 handle
        entry.model_id = entry_model_id;
        entry.local_min = m.min_xyz;
        entry.local_max = m.max_xyz;
        // 无记录则从当前欧拉初始化四元数
        if (g_handle_orientation_quat.find(h) == g_handle_orientation_quat.end()) {
            g_handle_orientation_quat[h] = quat_from_model_euler(t.euler_rotation);
        }
        ktm::fquat q_pred = g_handle_orientation_quat[h];  // 复制：预测用，不提前改全局缓存
        Corona::ModelTransform t_collision = t;            // 复制当前变换
        if (!g_handle_to_sleeping[h]) {
            // 为碰撞预测外推位姿时也遵守轴锁定
            ktm::fvec3 vc = g_handle_to_velocity[h];
            ktm::fvec3 ang_pred = g_handle_to_angular_vel[h];
            uint8_t lin_lock = g_handle_to_linear_lock[h];
            uint8_t ang_lock = g_handle_to_angular_lock[h];
            if (lin_lock & kLockAxisX) vc.x = 0.0f;
            if (lin_lock & kLockAxisY) vc.y = 0.0f;
            if (lin_lock & kLockAxisZ) vc.z = 0.0f;
            if (ang_lock & kLockAxisX) ang_pred.x = 0.0f;
            if (ang_lock & kLockAxisY) ang_pred.y = 0.0f;
            if (ang_lock & kLockAxisZ) ang_pred.z = 0.0f;

            t_collision.position.x += vc.x * fixed_dt;       // 外推平移用于碰撞检测
            t_collision.position.y += vc.y * fixed_dt;
            t_collision.position.z += vc.z * fixed_dt;
            integrate_orientation_quat(q_pred, ang_pred, fixed_dt);  // 外推旋转
        }
        sync_euler_from_orientation_quat(q_pred, t_collision.euler_rotation);  // 矩阵一致化 euler
        world_aabb_from_local_bounds(t_collision, entry.local_min, entry.local_max,
                                     entry.min_world, entry.max_world, entry.center_world);
        entry.half_extents = make_fvec3(
            (entry.max_world.x - entry.min_world.x) * 0.5f,  // 世界 AABB 半宽
            (entry.max_world.y - entry.min_world.y) * 0.5f,
            (entry.max_world.z - entry.min_world.z) * 0.5f);
#if CORONA_MECHANICS_USE_OBB_SAT
        build_mechanics_obb(entry, t_collision);  // 由同一预测位姿构造 OBB
#endif

        const float mass = handle_to_mass[h];                    // kg
        const float w = std::abs(e_local.x * t.scale.x) * 2.0f;  // 世界系盒子 X 向全长（缩放后）
        const float hh = std::abs(e_local.y * t.scale.y) * 2.0f;
        const float d = std::abs(e_local.z * t.scale.z) * 2.0f;
        float Ix = mass * (hh * hh + d * d) / 12.0f;  // 长方体主轴惯量（近似；均质 box）
        float Iy = mass * (w * w + d * d) / 12.0f;
        float Iz = mass * (w * w + hh * hh) / 12.0f;
        Ix = std::max(Ix, min_inertia);  // 下限防止除零
        Iy = std::max(Iy, min_inertia);
        Iz = std::max(Iz, min_inertia);
        entry.rot_body_to_world = q_pred.matrix3x3();                          // 体→世界旋转（预测姿态）
        entry.inertia_inv_body = make_fvec3(1.0f / Ix, 1.0f / Iy, 1.0f / Iz);  // 体系逆惯量对角

        handle_to_index[h] = mechanics_data.size();  // 句柄→本轮 mechanics_data 下标
        mechanics_data.push_back(entry);
    }

    // 预加载所有物理物体的碰撞网格（用于三角形碰撞检测和精确地板碰撞）
    for (const auto& entry : mechanics_data) {
        if (g_shutdown_requested.load(std::memory_order_acquire)) {
            return;
        }
        if (entry.model_id != 0) {
            ensure_collision_mesh(entry.model_id);
        }
    }

    // 临时校正表：记录 Phase 5 末轮的位置校正量，在 Phase 6 积分后统一应用
    std::unordered_map<std::uintptr_t, ktm::fvec3> position_correction;

    // 阶段 5：从 GeometrySystem 获取宽相候选对 → 窄相（AABB 或 OBB+SAT）→ 顺序冲量 + 摩擦 + 末轮位置校正 ---
    //GeometrySystem 八叉树 payload 是 actor_handle，query_pairs() 返回 (actor_a, actor_b)
    //一个 actor 可能挂多个含 mechanics 的 profile，故用 vector 存储所有 mechanics_handle
    //转换时展开笛卡尔积；遍历 actor_a 的每个 mechanics vs actor_b 的每个 mechanics

    // 构建 actor_handle → vector<mechanics_handle> 反向映射
    std::unordered_map<std::uintptr_t, std::vector<std::uintptr_t>> actor_to_mech;
    for (const auto& [mh, ah] : mech_to_actor) {
        actor_to_mech[ah].push_back(mh);
    }

    std::vector<std::pair<std::uintptr_t, std::uintptr_t>> collision_pairs;
    collision_pairs.reserve(mechanics_data.size() * 4);

    // 通过 ISystemContext 获取 GeometrySystem 指针，调用其八叉树的 query_pairs()
    // 宽相阶段由 GeometrySystem 维护的八叉树统一服务，MechanicsSystem 不再自建本地 octree。
    // GeometrySystem(85) 优先级高于 MechanicsSystem(75)，八叉树在同帧物理前已重建。
    // 指针在 initialize() 中缓存，避免每帧通过 get_system() 加锁查询。
    if (m_geometry_sys) {
        for (auto sh : scene_handles) {
            if (g_shutdown_requested.load(std::memory_order_acquire)) {
                return;
            }
            auto actor_pairs = m_geometry_sys->query_pairs(sh);
            for (const auto& [ah, bh] : actor_pairs) {
                if (g_shutdown_requested.load(std::memory_order_acquire)) {
                    return;
                }
                auto it_a = actor_to_mech.find(ah);
                auto it_b = actor_to_mech.find(bh);
                if (it_a == actor_to_mech.end() || it_b == actor_to_mech.end()) continue;

                for (auto mh_a : it_a->second) {
                    for (auto mh_b : it_b->second) {
                        collision_pairs.emplace_back(mh_a, mh_b);
                    }
                }
            }
        }
    }

    if (mechanics_data.size() >= 2) {
        // 碰撞对跟踪（用于回调通知 collision start/end）
        std::unordered_set<std::pair<std::uintptr_t, std::uintptr_t>, PairHash> curr_active_collisions;

        // 惰性缓存：仅对候选对涉及的物体计算世界空间碰撞网格
        std::unordered_map<std::uintptr_t, std::vector<ktm::fvec3>> world_verts_cache;

        // 5.4 对候选对做法向/切向冲量（半隐式 GS：多轮依次解每对约束近似同时满足）
        constexpr float eps = 1e-8f;                   // 分母稳定项，非物理
        constexpr float min_overlap = 0.001f;          // 小于此视为数值噪声/SAT 抖振，跳过
        constexpr float k_positional_slop = 0.004f;    // Baumgarte 式校正：小穿透只靠冲量，不修位姿
        constexpr float k_positional_percent = 0.35f;  // 仅末轮按穿透拆分平移，且只推一部分，防过冲
        constexpr int k_impulse_iterations = 5;        // 轮数↑ 堆叠更稳、成本↑；典型 3~8
        for (int impulse_iter = 0; impulse_iter < k_impulse_iterations; ++impulse_iter) {
            if (g_shutdown_requested.load(std::memory_order_acquire)) {
                return;
            }
            for (const auto& pair : collision_pairs) {  // 内层：单对接触解一次（顺序依赖）
                if (g_shutdown_requested.load(std::memory_order_acquire)) {
                    return;
                }
                std::uintptr_t ha = pair.first;
                std::uintptr_t hb = pair.second;
                // 两个都休眠则跳过
                if (g_handle_to_sleeping[ha] && g_handle_to_sleeping[hb])
                    continue;

                // 查找物体A/B的AABB数据
                auto it_a = handle_to_index.find(ha);
                auto it_b = handle_to_index.find(hb);
                if (it_a == handle_to_index.end() || it_b == handle_to_index.end()) {
                    continue;
                }

                const MechanicsWorldAABB& a = mechanics_data[it_a->second];
                const MechanicsWorldAABB& b = mechanics_data[it_b->second];

                // 碰撞检测开关判断：任一物体关闭碰撞则跳过此对
                // 使用 find() 而非 operator[] 避免默认构造 false 导致碰撞被静默跳过
                {
                    bool col_a = true, col_b = true;
                    auto it_col_a = handle_to_collision_enabled.find(ha);
                    if (it_col_a != handle_to_collision_enabled.end()) col_a = it_col_a->second;
                    auto it_col_b = handle_to_collision_enabled.find(hb);
                    if (it_col_b != handle_to_collision_enabled.end()) col_b = it_col_b->second;
                    if (!col_a || !col_b) continue;
                }

                // ===== Phase 1: AABB 碰撞检测（Broadphase 确认）=====
                if (!aabb_overlap(a.min_world, a.max_world, b.min_world, b.max_world)) {
                    continue;
                }

                ktm::fvec3 normal{};
                float penetration = 0.f;
#if CORONA_MECHANICS_USE_OBB_SAT
                if (!sat_obb_obb(a.obb_center, a.obb_u, a.obb_v, a.obb_w, a.obb_hu, a.obb_hv, a.obb_hw,
                                 b.obb_center, b.obb_u, b.obb_v, b.obb_w, b.obb_hu, b.obb_hv, b.obb_hw,
                                 normal, penetration)) {
                    continue;
                }
                if (penetration < min_overlap) {
                    continue;
                }
#else
                // AABB–AABB：MTD 必沿世界轴；旋转体用世界 AABB 包络时斜面接触法线仍错，真斜碰请开 OBB+SAT。
                // 稳定：在「并列最浅穿透」的轴里优先 |Δcenter| 最大者，避免主轴每帧切换；符号用死区避免 0 附近翻转。
                const float diff_x = b.center_world.x - a.center_world.x;
                const float diff_y = b.center_world.y - a.center_world.y;
                const float diff_z = b.center_world.z - a.center_world.z;
                const float overlap_x =
                    (a.max_world.x - a.min_world.x) * 0.5f + (b.max_world.x - b.min_world.x) * 0.5f - std::abs(diff_x);
                const float overlap_y =
                    (a.max_world.y - a.min_world.y) * 0.5f + (b.max_world.y - b.min_world.y) * 0.5f - std::abs(diff_y);
                const float overlap_z =
                    (a.max_world.z - a.min_world.z) * 0.5f + (b.max_world.z - b.min_world.z) * 0.5f - std::abs(diff_z);
                if (overlap_x < min_overlap || overlap_y < min_overlap || overlap_z < min_overlap) {
                    continue;
                }
                const float mtd_min = std::min({overlap_x, overlap_y, overlap_z});
                constexpr float k_mtd_tie_abs = 0.0025f;
                constexpr float k_mtd_tie_rel = 0.04f;
                const float mtd_band = std::max(k_mtd_tie_abs, k_mtd_tie_rel * std::max(mtd_min, min_overlap));
                const float adx = std::abs(diff_x);
                const float ady = std::abs(diff_y);
                const float adz = std::abs(diff_z);
                int axis = 0;
                float best_dabs = -1.f;
                int best_stack_pri = 999;
                for (int i = 0; i < 3; ++i) {
                    const float ov = (i == 0) ? overlap_x : (i == 1) ? overlap_y
                                                                     : overlap_z;
                    const float ab = (i == 0) ? adx : (i == 1) ? ady
                                                               : adz;
                    if (ov > mtd_min + mtd_band) {
                        continue;
                    }
                    const int stack_pri = (i == 1) ? 0 : (i == 0) ? 1
                                                                  : 2;
                    if (ab > best_dabs + 1e-6f) {
                        axis = i;
                        best_dabs = ab;
                        best_stack_pri = stack_pri;
                    } else if (std::abs(ab - best_dabs) <= 1e-6f && stack_pri < best_stack_pri) {
                        axis = i;
                        best_stack_pri = stack_pri;
                    }
                }
                if (best_dabs < 0.f) {
                    if (overlap_y <= overlap_x && overlap_y <= overlap_z) {
                        axis = 1;
                    } else if (overlap_x <= overlap_z) {
                        axis = 0;
                    } else {
                        axis = 2;
                    }
                }
                constexpr float k_mtd_sign_eps = 1e-4f;
                auto mtd_axis_sign = [](float d) -> float {
                    if (d > k_mtd_sign_eps) {
                        return 1.f;
                    }
                    if (d < -k_mtd_sign_eps) {
                        return -1.f;
                    }
                    return 1.f;
                };
                if (axis == 0) {
                    penetration = overlap_x;
                    normal = make_fvec3(mtd_axis_sign(diff_x), 0.f, 0.f);
                } else if (axis == 1) {
                    penetration = overlap_y;
                    normal = make_fvec3(0.f, mtd_axis_sign(diff_y), 0.f);
                } else {
                    penetration = overlap_z;
                    normal = make_fvec3(0.f, 0.f, mtd_axis_sign(diff_z));
                }
#endif

                // ===== 三角形窄相精化（可选）=====
                // 当双方都有碰撞网格且三角形数在限制内时，用三角形级 SAT 替换 AABB/OBB 的法线和穿透
#if CORONA_MECHANICS_USE_TRIANGLE_NARROWPHASE
                if (a.model_id != 0 && b.model_id != 0) {
                    auto it_mesh_a = g_collision_mesh_cache.find(a.model_id);
                    auto it_mesh_b = g_collision_mesh_cache.find(b.model_id);
                    if (it_mesh_a != g_collision_mesh_cache.end() &&
                        it_mesh_b != g_collision_mesh_cache.end()) {
                        // 惰性计算世界空间顶点（每物体每帧最多算一次）
                        if (world_verts_cache.find(ha) == world_verts_cache.end()) {
                            auto tx_a = transform_storage.try_acquire_read(a.transform_handle);
                            if (tx_a) {
                                transform_vertices_to_world(
                                    it_mesh_a->second.vertices, *tx_a, world_verts_cache[ha]);
                            }
                        }
                        if (world_verts_cache.find(hb) == world_verts_cache.end()) {
                            auto tx_b = transform_storage.try_acquire_read(b.transform_handle);
                            if (tx_b) {
                                transform_vertices_to_world(
                                    it_mesh_b->second.vertices, *tx_b, world_verts_cache[hb]);
                            }
                        }

                        auto wit_a = world_verts_cache.find(ha);
                        auto wit_b = world_verts_cache.find(hb);
                        if (wit_a != world_verts_cache.end() && wit_b != world_verts_cache.end() && !wit_a->second.empty() && !wit_b->second.empty()) {
                            auto& wv_a = wit_a->second;
                            auto& wv_b = wit_b->second;
                            TriangleContactResult tri_result;
                            triangle_narrowphase(wv_a, it_mesh_a->second,
                                                 wv_b, it_mesh_b->second,
                                                 a.center_world, b.center_world, tri_result);
                            if (tri_result.has_contact) {
                                normal = tri_result.normal;
                                // 保留 AABB/OBB 级别的穿透深度；三角形 SAT 深度只反映
                                // 单个三角形对的局部重叠，远小于物体级实际穿透，会导致严重穿模。
                                // 三角形窄相的价值在于提供更精确的碰撞法线方向。
                            } else {
                                continue;  // 三角形级无接触，跳过此对
                            }
                        }
                    }
                }
#endif

                const float mass_a = handle_to_mass[ha];
                const float mass_b = handle_to_mass[hb];
                const bool sleep_a = g_handle_to_sleeping[ha];  // 休眠体当「动不了」：不接收冲量速度增量
                const bool sleep_b = g_handle_to_sleeping[hb];
                const float inv_ma = sleep_a ? 0.f : 1.0f / mass_a;  // Δv = (j/m)·n 中的 1/m
                const float inv_mb = sleep_b ? 0.f : 1.0f / mass_b;
                const float rest_a = handle_to_restitution[ha];  // 双方恢复系数各取组件；此处简单平均
                const float rest_b = handle_to_restitution[hb];
                const float rest = (rest_a + rest_b) * 0.5f;
                // 前几轮 e=0：先把接触簇里的相对法向「扎进」速度吃掉；末轮再加 e，减轻来回弹
                const float rest_use = (impulse_iter == k_impulse_iterations - 1) ? rest : 0.f;

#if CORONA_MECHANICS_USE_OBB_SAT
                const ktm::fvec3 p_a = obb_support_point(a.obb_center, a.obb_u, a.obb_v, a.obb_w,
                                                         a.obb_hu, a.obb_hv, a.obb_hw, normal);
                const ktm::fvec3 p_b = obb_support_point(b.obb_center, b.obb_u, b.obb_v, b.obb_w,
                                                         b.obb_hu, b.obb_hv, b.obb_hw,
                                                         make_fvec3(-normal.x, -normal.y, -normal.z));
                const ktm::fvec3 p_contact = vec3_mul(vec3_add(p_a, p_b), 0.5f);  // 近似接触点：两支撑点中点
                const ktm::fvec3 r_a = vec3_sub(p_contact, a.obb_center);         // 质心/盒心到触点的臂
                const ktm::fvec3 r_b = vec3_sub(p_contact, b.obb_center);
#else
                const ktm::fvec3 p_a = aabb_support_world(a.center_world, a.half_extents, normal);
                const ktm::fvec3 p_b = aabb_support_world(b.center_world, b.half_extents,
                                                          make_fvec3(-normal.x, -normal.y, -normal.z));
                const ktm::fvec3 p_contact = vec3_mul(vec3_add(p_a, p_b), 0.5f);  // AABB 模式下同样用中点
                const ktm::fvec3 r_a = vec3_sub(p_contact, a.center_world);       // 此处 center_world≈AABB 心
                const ktm::fvec3 r_b = vec3_sub(p_contact, b.center_world);
#endif

                ktm::fvec3& va = g_handle_to_velocity[ha];
                ktm::fvec3& vb = g_handle_to_velocity[hb];
                ktm::fvec3& wa = g_handle_to_angular_vel[ha];
                ktm::fvec3& wb = g_handle_to_angular_vel[hb];

                ktm::fvec3 v_pa = velocity_at_point_world(va, wa, r_a);
                ktm::fvec3 v_pb = velocity_at_point_world(vb, wb, r_b);
                ktm::fvec3 v_rel = make_fvec3(v_pa.x - v_pb.x, v_pa.y - v_pb.y, v_pa.z - v_pb.z);
                // n 从 A 指向 B：v_rel = v_pa - v_pb，v_n > 0 表示沿 n 相互接近（需法向冲量）
                const float v_n = ktm::dot(v_rel, normal);
                if (v_n < -1e-4f) {
                    continue;
                }

                const ktm::fvec3 raxn = ktm::cross(r_a, normal);  // r×n，进入 ω 的有效惯量投影公式
                const ktm::fvec3 rbxn = ktm::cross(r_b, normal);
                // 标量 ang_n：世界系下 (I_w^{-1} (r×n))·(r×n)，即柔度矩阵 K 中法对角项
                const float ang_n_a = sleep_a ? 0.f
                                              : ktm::dot(raxn, world_inertia_inv_apply(a.rot_body_to_world, a.inertia_inv_body, raxn));
                const float ang_n_b = sleep_b ? 0.f
                                              : ktm::dot(rbxn, world_inertia_inv_apply(b.rot_body_to_world, b.inertia_inv_body, rbxn));
                const float denom_n = inv_ma + inv_mb + ang_n_a + ang_n_b + eps;  // 1 / (有效质量)
                if (denom_n <= 1e-12f) {
                    continue;  // 近奇异（例如双臂共线且惯量项异常）
                }
                const float j = -(1.0f + rest_use) * v_n / denom_n;  // 法向冲量标量；约定 J = j·n 作用于 B 的正向

                va.x += normal.x * j * inv_ma;
                va.y += normal.y * j * inv_ma;
                va.z += normal.z * j * inv_ma;
                vb.x -= normal.x * j * inv_mb;
                vb.y -= normal.y * j * inv_mb;
                vb.z -= normal.z * j * inv_mb;

                const ktm::fvec3 Jn = make_fvec3(normal.x * j, normal.y * j, normal.z * j);  // 法向冲量向量
                if (!sleep_a) {
                    const ktm::fvec3 dw =
                        world_inertia_inv_apply(a.rot_body_to_world, a.inertia_inv_body, ktm::cross(r_a, Jn));  // Δω = I^{-1}(r×J)
                    wa.x += dw.x;
                    wa.y += dw.y;
                    wa.z += dw.z;
                }
                if (!sleep_b) {
                    const ktm::fvec3 dw = world_inertia_inv_apply(
                        b.rot_body_to_world, b.inertia_inv_body, ktm::cross(r_b, make_fvec3(-Jn.x, -Jn.y, -Jn.z)));  // B 受力为 -J
                    wb.x += dw.x;
                    wb.y += dw.y;
                    wb.z += dw.z;
                }

                v_pa = velocity_at_point_world(va, wa, r_a);
                v_pb = velocity_at_point_world(vb, wb, r_b);
                v_rel = make_fvec3(v_pa.x - v_pb.x, v_pa.y - v_pb.y, v_pa.z - v_pb.z);
                const float v_n_rel = ktm::dot(v_rel, normal);  // 法向冲量后的接近速度（可 <0，表示分离中）
                ktm::fvec3 v_t = make_fvec3(                    // v_rel 去掉法向分量 = 切向滑移速度
                    v_rel.x - normal.x * v_n_rel,
                    v_rel.y - normal.y * v_n_rel,
                    v_rel.z - normal.z * v_n_rel);
                const float vt_len = ktm::length(v_t);
                if (vt_len > eps) {                                                                      // 无切向速度则跳过摩擦
                    const ktm::fvec3 tdir = make_fvec3(v_t.x / vt_len, v_t.y / vt_len, v_t.z / vt_len);  // 滑移方向单位向量
                    const float v_slip = ktm::dot(v_rel, tdir);                                          // 沿 tdir 的标量滑移速度
                    const ktm::fvec3 raxt = ktm::cross(r_a, tdir);
                    const ktm::fvec3 rbxt = ktm::cross(r_b, tdir);
                    const float ang_t_a = sleep_a ? 0.f
                                                  : ktm::dot(raxt, world_inertia_inv_apply(a.rot_body_to_world, a.inertia_inv_body, raxt));
                    const float ang_t_b = sleep_b ? 0.f
                                                  : ktm::dot(rbxt, world_inertia_inv_apply(b.rot_body_to_world, b.inertia_inv_body, rbxt));
                    const float denom_t = inv_ma + inv_mb + ang_t_a + ang_t_b + eps;
                    if (denom_t > 1e-12f) {
                        const float jt_free = -v_slip / denom_t;                        // 无摩擦上限时的切向冲量（完全粘滞）
                        const float jt_cap = friction_coeff * std::fabs(j);             // 库仑锥 |jt| ≤ μ|j|
                        const float jt = std::max(-jt_cap, std::min(jt_cap, jt_free));  // 钳位到摩擦锥内

                        va.x += tdir.x * jt * inv_ma;
                        va.y += tdir.y * jt * inv_ma;
                        va.z += tdir.z * jt * inv_ma;
                        vb.x -= tdir.x * jt * inv_mb;
                        vb.y -= tdir.y * jt * inv_mb;
                        vb.z -= tdir.z * jt * inv_mb;

                        const ktm::fvec3 Jt = make_fvec3(tdir.x * jt, tdir.y * jt, tdir.z * jt);
                        if (!sleep_a) {
                            const ktm::fvec3 dw =
                                world_inertia_inv_apply(a.rot_body_to_world, a.inertia_inv_body, ktm::cross(r_a, Jt));
                            wa.x += dw.x;
                            wa.y += dw.y;
                            wa.z += dw.z;
                        }
                        if (!sleep_b) {
                            const ktm::fvec3 dw = world_inertia_inv_apply(
                                b.rot_body_to_world, b.inertia_inv_body,
                                ktm::cross(r_b, make_fvec3(-Jt.x, -Jt.y, -Jt.z)));
                            wb.x += dw.x;
                            wb.y += dw.y;
                            wb.z += dw.z;
                        }
                    }
                }

                if (impulse_iter == k_impulse_iterations - 1) {
                    // 末轮：按穿透深度记录软位置校正（延迟到 Phase 6 积分后统一应用，避免抖动）
                    const float pen = std::max(0.f, penetration - k_positional_slop);
                    if (pen > 0.f) {
                        const float inv_sum = inv_ma + inv_mb;  // 按逆质量比例分摊平移
                        if (inv_sum > eps) {
                            const float corr_scale = k_positional_percent * pen / inv_sum;
                            const auto record_corr = [&](std::uintptr_t handle, float inv_eff, float sign) {
                                if (inv_eff <= eps) return;
                                auto& corr = position_correction[handle];  // 默认初始化为 {0,0,0}
                                corr.x += sign * normal.x * corr_scale * inv_eff;
                                corr.y += sign * normal.y * corr_scale * inv_eff;
                                corr.z += sign * normal.z * corr_scale * inv_eff;
                            };
                            record_corr(ha, inv_ma, -1.f);
                            record_corr(hb, inv_mb, +1.f);
                        }
                    }

                    // 只有当法向冲量导致的速度变化超过休眠阈值时才唤醒
                    {
                        const float wake_impulse_threshold = sleep_threshold * 2.0f;
                        const float delta_v_a = std::abs(j) * inv_ma;
                        const float delta_v_b = std::abs(j) * inv_mb;

                        if (delta_v_a > wake_impulse_threshold) {
                            g_handle_to_sleeping[ha] = false;
                            g_handle_to_sleep_timer[ha] = 0.0f;
                        }
                        if (delta_v_b > wake_impulse_threshold) {
                            g_handle_to_sleeping[hb] = false;
                            g_handle_to_sleep_timer[hb] = 0.0f;
                        }
                    }

                    // 记录活跃碰撞对
                    auto actor_a = mech_to_actor.count(ha) ? mech_to_actor[ha] : ha;
                    auto actor_b = mech_to_actor.count(hb) ? mech_to_actor[hb] : hb;
                    auto sorted_pair = (actor_a < actor_b) ? std::make_pair(actor_a, actor_b) : std::make_pair(actor_b, actor_a);
                    curr_active_collisions.insert(sorted_pair);

                    // ==================== 碰撞回调（延迟到帧末执行，避免在物理循环中持有锁时调用） ========================
                    {
                        ktm::fvec3 point;
                        point.x = (a.center_world.x + b.center_world.x) * 0.5f;
                        point.y = (a.center_world.y + b.center_world.y) * 0.5f;
                        point.z = (a.center_world.z + b.center_world.z) * 0.5f;

                        std::function<void(std::uintptr_t, bool, const std::array<float, 3>&, const std::array<float, 3>&)> cb_a;
                        std::function<void(std::uintptr_t, bool, const std::array<float, 3>&, const std::array<float, 3>&)> cb_b;

                        {
                            auto mech_a_acc = mechanics_storage.try_acquire_read(ha);
                            if (mech_a_acc && mech_a_acc->collision_callback) {
                                cb_a = mech_a_acc->collision_callback;
                            }
                        }

                        {
                            auto mech_b_acc = mechanics_storage.try_acquire_read(hb);
                            if (mech_b_acc && mech_b_acc->collision_callback) {
                                cb_b = mech_b_acc->collision_callback;
                            }
                        }

                        std::array<float, 3> normal_arr = {normal.x, normal.y, normal.z};
                        std::array<float, 3> point_arr = {point.x, point.y, point.z};

                        bool was_active = (g_prev_active_collisions.find(sorted_pair) != g_prev_active_collisions.end());

                        if (!was_active && !g_shutdown_requested.load(std::memory_order_acquire)) {
                            if (cb_a) {
                                g_deferred_collision_callbacks.push_back({std::move(cb_a), actor_b, true, normal_arr, point_arr});
                            }

                            if (cb_b) {
                                std::array<float, 3> reverse_normal_arr = {-normal.x, -normal.y, -normal.z};
                                g_deferred_collision_callbacks.push_back({std::move(cb_b), actor_a, true, reverse_normal_arr, point_arr});
                            }
                        }
                    }
                    // =====================================================
                }
            }
        }  // 内层：collision_pairs；外层：impulse_iter

        // ===== 碰撞结束检测：遍历上帧活跃但本帧消失的碰撞对，延迟触发 end 回调 =====
        for (const auto& old_pair : g_prev_active_collisions) {
            if (g_shutdown_requested.load(std::memory_order_acquire)) {
                return;
            }
            if (curr_active_collisions.find(old_pair) != curr_active_collisions.end()) {
                continue;  // 仍在碰撞，不触发 end
            }

            std::uintptr_t actor_a = old_pair.first;
            std::uintptr_t actor_b = old_pair.second;

            // 反查 actor_handle → mechanics_handle
            std::uintptr_t mech_ha = 0, mech_hb = 0;
            for (const auto& [mh, ah] : mech_to_actor) {
                if (ah == actor_a && mech_ha == 0) mech_ha = mh;
                if (ah == actor_b && mech_hb == 0) mech_hb = mh;
            }

            std::array<float, 3> zero_normal = {0.f, 0.f, 0.f};
            std::array<float, 3> zero_point = {0.f, 0.f, 0.f};

            if (mech_ha != 0) {
                std::function<void(std::uintptr_t, bool, const std::array<float, 3>&, const std::array<float, 3>&)> cb;
                {
                    auto m_acc = mechanics_storage.try_acquire_read(mech_ha);
                    if (m_acc && m_acc->collision_callback && !g_shutdown_requested.load(std::memory_order_acquire)) {
                        cb = m_acc->collision_callback;
                    }
                }
                if (cb) {
                    g_deferred_collision_callbacks.push_back({std::move(cb), actor_b, false, zero_normal, zero_point});
                }
            }

            if (mech_hb != 0) {
                std::function<void(std::uintptr_t, bool, const std::array<float, 3>&, const std::array<float, 3>&)> cb;
                {
                    auto m_acc = mechanics_storage.try_acquire_read(mech_hb);
                    if (m_acc && m_acc->collision_callback && !g_shutdown_requested.load(std::memory_order_acquire)) {
                        cb = m_acc->collision_callback;
                    }
                }
                if (cb) {
                    g_deferred_collision_callbacks.push_back({std::move(cb), actor_a, false, zero_normal, zero_point});
                }
            }
        }

        // 更新上一帧碰撞对
        g_prev_active_collisions.swap(curr_active_collisions);
    } else {
        // 物体数量不足2个时，为残留的碰撞对延迟发送 collision end 回调
        for (const auto& old_pair : g_prev_active_collisions) {
            if (g_shutdown_requested.load(std::memory_order_acquire)) {
                return;
            }
            std::uintptr_t actor_a = old_pair.first;
            std::uintptr_t actor_b = old_pair.second;

            std::uintptr_t mech_ha = 0, mech_hb = 0;
            for (const auto& [mh, ah] : mech_to_actor) {
                if (ah == actor_a && mech_ha == 0) mech_ha = mh;
                if (ah == actor_b && mech_hb == 0) mech_hb = mh;
            }

            std::array<float, 3> zero_normal = {0.f, 0.f, 0.f};
            std::array<float, 3> zero_point = {0.f, 0.f, 0.f};

            if (mech_ha != 0) {
                std::function<void(std::uintptr_t, bool, const std::array<float, 3>&, const std::array<float, 3>&)> cb;
                {
                    auto m_acc = mechanics_storage.try_acquire_read(mech_ha);
                    if (m_acc && m_acc->collision_callback && !g_shutdown_requested.load(std::memory_order_acquire)) {
                        cb = m_acc->collision_callback;
                    }
                }
                if (cb) {
                    g_deferred_collision_callbacks.push_back({std::move(cb), actor_b, false, zero_normal, zero_point});
                }
            }

            if (mech_hb != 0) {
                std::function<void(std::uintptr_t, bool, const std::array<float, 3>&, const std::array<float, 3>&)> cb;
                {
                    auto m_acc = mechanics_storage.try_acquire_read(mech_hb);
                    if (m_acc && m_acc->collision_callback && !g_shutdown_requested.load(std::memory_order_acquire)) {
                        cb = m_acc->collision_callback;
                    }
                }
                if (cb) {
                    g_deferred_collision_callbacks.push_back({std::move(cb), actor_a, false, zero_normal, zero_point});
                }
            }
        }
        g_prev_active_collisions.clear();
    }

    // --- 阶段 5b：轴锁定强制执行 — 碰撞冲量求解后，再次清零锁定轴的速度分量 ---
    for (std::uintptr_t h : mechanics_handles) {
        if (g_handle_to_sleeping[h]) continue;
        uint8_t lin_lock = g_handle_to_linear_lock[h];
        if (lin_lock & kLockAxisX) g_handle_to_velocity[h].x = 0.0f;
        if (lin_lock & kLockAxisY) g_handle_to_velocity[h].y = 0.0f;
        if (lin_lock & kLockAxisZ) g_handle_to_velocity[h].z = 0.0f;

        uint8_t ang_lock = g_handle_to_angular_lock[h];
        if (ang_lock & kLockAxisX) g_handle_to_angular_vel[h].x = 0.0f;
        if (ang_lock & kLockAxisY) g_handle_to_angular_vel[h].y = 0.0f;
        if (ang_lock & kLockAxisZ) g_handle_to_angular_vel[h].z = 0.0f;
    }

    // --- 阶段 6：半隐式位姿积分（用冲量后的 v,ω）+ 无穷地板 + 休眠累计 + 缓存淘汰 ---
    for (std::size_t i = 0; i < mechanics_data.size(); ++i) {
        if (g_shutdown_requested.load(std::memory_order_acquire)) {
            return;
        }
        const auto& data = mechanics_data[i];  // 与阶段 3 同一套 per-body 缓存
        std::uintptr_t h = data.handle;

        // 唤醒因地板降低而悬空的休眠体（物体搁在地板上休眠后，地板调低应自由落体）
        if (g_handle_to_sleeping[h] && data.min_world.y > floor_y + floor_eps) {
            g_handle_to_sleeping[h] = false;
            g_handle_to_sleep_timer[h] = 0.0f;
        }

        if (g_handle_to_sleeping[h])
            continue;  // 休眠体不再推进变换

        // 阻塞写锁：位置积分每帧都要写回，_nowait 拿不到锁会跳过本帧导致物体卡顿/抖动。
        // 用阻塞版等锁（不漏帧），槽位失效时返回无效句柄而非抛异常。
        auto tx_w = transform_storage.try_acquire_write(data.transform_handle);
        if (!tx_w) continue;

        // 为轴锁定准备一份清零后的速度副本（用于积分，不修改全局缓存）
        ktm::fvec3 vel_for_pos = g_handle_to_velocity[h];
        uint8_t lin_lock = g_handle_to_linear_lock[h];
        if (lin_lock & kLockAxisX) vel_for_pos.x = 0.0f;
        if (lin_lock & kLockAxisY) vel_for_pos.y = 0.0f;
        if (lin_lock & kLockAxisZ) vel_for_pos.z = 0.0f;

        // 速度 × dt 平移（显式欧拉；与阶段 3 预测一致）
        tx_w->position.x += vel_for_pos.x * fixed_dt;
        tx_w->position.y += vel_for_pos.y * fixed_dt;
        tx_w->position.z += vel_for_pos.z * fixed_dt;

        // 应用 Phase 5 累积的位置校正（积分后统一应用，避免校正与积分不一致导致抖动）
        auto corr_it = position_correction.find(h);
        if (corr_it != position_correction.end()) {
            ktm::fvec3 corr = corr_it->second;
            if (lin_lock & kLockAxisX) corr.x = 0.0f;
            if (lin_lock & kLockAxisY) corr.y = 0.0f;
            if (lin_lock & kLockAxisZ) corr.z = 0.0f;
            tx_w->position.x += corr.x;
            tx_w->position.y += corr.y;
            tx_w->position.z += corr.z;
        }

        {  // 朝向：以四元数为真值源，欧拉仅用于与渲染/资产管线对齐
            auto q_it = g_handle_orientation_quat.find(h);
            if (q_it == g_handle_orientation_quat.end()) {
                q_it = g_handle_orientation_quat.emplace(h, quat_from_model_euler(tx_w->euler_rotation)).first;
            }
            // 为轴锁定准备一份清零后的角速度副本（用于积分，不修改全局缓存）
            ktm::fvec3 ang_for_rot = g_handle_to_angular_vel[h];
            uint8_t ang_lock = g_handle_to_angular_lock[h];
            if (ang_lock & kLockAxisX) ang_for_rot.x = 0.0f;
            if (ang_lock & kLockAxisY) ang_for_rot.y = 0.0f;
            if (ang_lock & kLockAxisZ) ang_for_rot.z = 0.0f;
            integrate_orientation_quat(q_it->second, ang_for_rot, fixed_dt);  // q ← q ⊗ Δq(ω)
            sync_euler_from_orientation_quat(q_it->second, tx_w->euler_rotation);            // 写回 XYZ 欧拉（约定与引擎一致）
        }

        // 复用 Phase 3 已计算的世界 AABB min.y，避免重新计算完整 world AABB
        // 积分后 position 偏移量与 Phase 3 的预测一致，因此可直接复用
        float object_bottom_y = data.min_world.y;
        // 若有位置校正，补偿底面高度（仅在 Y 轴未锁时考虑校正）
        if (corr_it != position_correction.end() && !(lin_lock & kLockAxisY)) {
            object_bottom_y += corr_it->second.y;
        }

        // 碰撞检测开关判断：若物体关闭碰撞，跳过地板碰撞处理
        bool collision_enabled = true;
        auto col_it = handle_to_collision_enabled.find(h);
        if (col_it != handle_to_collision_enabled.end()) {
            collision_enabled = col_it->second;
        }

        // 水平 floor_y：穿插时整体上抬，并做法向/切向「处方」（非完整接触流形）
        // 轴锁定：地板碰撞的各轴修正仅在对应轴未锁时执行
        if (collision_enabled && object_bottom_y < floor_y + floor_eps) {
            // 消穿修正仅在 Y 轴未锁时执行
            if (!(lin_lock & kLockAxisY)) {
                tx_w->position.y += (floor_y + floor_eps) - object_bottom_y;
            }

            // 法向速度反弹仅在 Y 轴未锁时处理
            if (!(lin_lock & kLockAxisY)) {
                float y_vel = g_handle_to_velocity[h].y;  // 向上为正
                if (y_vel < -low_vel_threshold) {
                    g_handle_to_velocity[h].y = -y_vel * floor_restitution;  // 下行且够快则反弹
                    g_handle_to_sleep_timer[h] = 0.0f;                       // 显著弹跳才打断休眠计时
                } else {
                    if (std::abs(g_handle_to_velocity[h].y) < zero_vel_threshold) {
                        g_handle_to_velocity[h].y = 0.0f;  // 粘地：贴住时竖直速度清零
                    } else {
                        g_handle_to_velocity[h].y *= 0.15f;  // 弱弹簧感衰减残余弹跳
                    }
                }
            }

            // 地板摩擦力仅在对应轴未锁时应用
            if (!(lin_lock & kLockAxisX)) g_handle_to_velocity[h].x *= 0.8f;
            if (!(lin_lock & kLockAxisZ)) g_handle_to_velocity[h].z *= 0.8f;

            // 滚阻仅在对应轴未锁时应用
            uint8_t ang_lock = g_handle_to_angular_lock[h];
            if (!(ang_lock & kLockAxisX)) g_handle_to_angular_vel[h].x *= 0.7f;
            if (!(ang_lock & kLockAxisY)) g_handle_to_angular_vel[h].y *= 0.7f;
            if (!(ang_lock & kLockAxisZ)) g_handle_to_angular_vel[h].z *= 0.7f;
            // 静接触不打断休眠计时，让休眠检测正常累积
        }
    }

    for (std::uintptr_t h : mechanics_handles) {
        if (g_shutdown_requested.load(std::memory_order_acquire)) {
            return;
        }
        if (g_handle_to_sleeping[h]) continue;

        const auto& v = g_handle_to_velocity[h];
        const auto& av = g_handle_to_angular_vel[h];

        float v_sq = v.x * v.x + v.y * v.y + v.z * v.z;
        float av_sq = av.x * av.x + av.y * av.y + av.z * av.z;

        if (v_sq < sleep_threshold_sq && av_sq < sleep_threshold_sq) {
            g_handle_to_sleep_timer[h] += fixed_dt;  // 低速窗口累加
            if (g_handle_to_sleep_timer[h] >= sleep_time_needed) {
                g_handle_to_sleeping[h] = true;
                g_handle_to_velocity[h] = make_fvec3(0.0f, 0.0f, 0.0f);
                g_handle_to_angular_vel[h] = make_fvec3(0.0f, 0.0f, 0.0f);  // 冻结动力学状态
            }
        } else {
            g_handle_to_sleep_timer[h] = 0.0f;  // 一有运动就打断休眠倒计时
        }

        // ========== 异步执行移动回调 ==========
        {
            auto mech_acc = mechanics_storage.try_acquire_read(h);
            if (mech_acc && mech_acc->on_move_callback) {
                std::function<void()> cb_move = mech_acc->on_move_callback;

                if (cb_move) {
                    // 获取当前位置用于位移检查
                    ktm::fvec3 cur_pos = make_fvec3(0.f, 0.f, 0.f);
                    bool has_pos = false;
                    if (auto geom = geometry_storage.try_acquire_read(mech_acc->geometry_handle)) {
                        if (auto tx_r = transform_storage.try_acquire_read(geom->transform_handle)) {
                            cur_pos = tx_r->position;
                            has_pos = true;
                        }
                    }
                    if (!has_pos) continue;

                    // 1. 时间检查
                    auto it_time = g_handle_to_last_move_callback_time.find(h);
                    float last_time = (it_time != g_handle_to_last_move_callback_time.end()) ? it_time->second : -kMoveCallbackMinInterval;
                    bool time_elapsed = (g_global_simulation_time - last_time >= kMoveCallbackMinInterval);

                    // 2. 位移检查
                    auto it_pos = g_handle_to_last_move_callback_pos.find(h);
                    ktm::fvec3 last_pos = (it_pos != g_handle_to_last_move_callback_pos.end()) ? it_pos->second : make_fvec3(1e9f, 1e9f, 1e9f);

                    float dx = cur_pos.x - last_pos.x;
                    float dy = cur_pos.y - last_pos.y;
                    float dz = cur_pos.z - last_pos.z;
                    float dist_sq = dx * dx + dy * dy + dz * dz;
                    bool moved_enough = (dist_sq >= kMoveCallbackMinDistance * kMoveCallbackMinDistance);

                    // 3. 同时满足时间间隔和位移阈值才触发
                    if (time_elapsed && moved_enough && !g_shutdown_requested) {
                        g_handle_to_last_move_callback_time[h] = g_global_simulation_time;
                        g_handle_to_last_move_callback_pos[h] = cur_pos;

                        // 收集到延迟队列，帧末统一同步执行
                        g_deferred_move_callbacks.push_back(std::move(cb_move));
                    }
                }
            }
        }
        // =============================================================
    }

    // 帧末统一同步执行延迟的 on_move 回调
    for (auto& cb : g_deferred_move_callbacks) {
        if (g_shutdown_requested.load(std::memory_order_acquire)) {
            break;
        }
        try {
            cb();
        } catch (const std::exception& e) {
            CFW_LOG_ERROR("MechanicsSystem: on_move callback exception: {}", e.what());
        } catch (...) {
            CFW_LOG_ERROR("MechanicsSystem: on_move callback unknown exception");
        }
    }
    g_deferred_move_callbacks.clear();

    // 帧末统一同步执行延迟的碰撞回调（在 Storage 锁外执行，避免死锁）
    for (auto& cb : g_deferred_collision_callbacks) {
        if (g_shutdown_requested.load(std::memory_order_acquire)) {
            break;
        }
        try {
            cb.callback(cb.other_actor, cb.is_start, cb.normal, cb.point);
        } catch (const std::exception& e) {
            CFW_LOG_ERROR("MechanicsSystem: collision callback exception: {}", e.what());
        } catch (...) {
            CFW_LOG_ERROR("MechanicsSystem: collision callback unknown exception");
        }
    }
    g_deferred_collision_callbacks.clear();

    // 清理无效句柄的缓存
    std::unordered_set<std::uintptr_t> alive_handles(mechanics_handles.begin(), mechanics_handles.end());

    auto clean_cache = [&](auto& cache) {
        for (auto it = cache.begin(); it != cache.end();) {
            if (!alive_handles.count(it->first)) {
                it = cache.erase(it);  // 本帧未出现的 mechanics 句柄：删掉 stale 条目防 map 膨胀
            } else {
                ++it;
            }
        }
    };

    clean_cache(g_handle_to_sleeping);
    clean_cache(g_handle_to_sleep_timer);
    clean_cache(g_handle_to_linear_lock);
    clean_cache(g_handle_to_angular_lock);
    clean_cache(handle_to_mass);
    clean_cache(handle_to_damping);
    clean_cache(handle_to_restitution);
    clean_cache(handle_to_collision_enabled);
    clean_cache(g_handle_to_last_move_callback_time);
    clean_cache(g_handle_to_last_move_callback_pos);

}

}  // namespace Corona::Systems