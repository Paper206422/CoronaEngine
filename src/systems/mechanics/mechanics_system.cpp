#include <corona/events/engine_events.h>           // 引擎事件（本文件预留扩展）
#include <corona/events/mechanics_system_events.h>   // mechanics 事件声明
#include <corona/kernel/core/i_logger.h>             // CFW_LOG_* 日志
#include <corona/kernel/event/i_event_bus.h>         // 事件总线（依赖链）
#include <corona/kernel/event/i_event_stream.h>      // 事件流（依赖链）
#include <corona/systems/mechanics/mechanics_system.h> // MechanicsSystem 声明
#include <algorithm>    // min,max,clamp,sort,unique
#include <array>        // std::array（八叉树子节点）
#include <cmath>        // asin,atan2,fabs,abs
#include <cstddef>      // size_t
#include <cstdint>      // 固定宽度整数
#include <limits>       // numeric_limits（SAT）
#include <memory>       // unique_ptr,make_unique
#include <unordered_map> // 各 handle→数据 映射
#include <unordered_set> // alive_handles
#include <utility>      // pair, move
#include <vector>       // mechanics_data, collision_pairs 等

#include "corona/shared_data_hub.h" // 场景/几何/transform 集中存储
#include "ktm/ktm.h"                // 向量矩阵四元数
// 不依赖 nanobind；脚本回调自行处理 GIL。
//
// CORONA_MECHANICS_USE_OBB_SAT：0 默认 AABB 窄相；1 为 OBB+SAT。KTM 矩阵按列：元素 (r,c)=M[c][r]。
//
// === 全文件逐符号导读（对照下方实现） =====================================
// make_fvec3：result 为输出；三赋值后返回。
// mat3_at_rc / mat4_at_rc：数学行列表达到 KTM 存储。
// vec3_*：向量加减、数乘。
// transform_*：M=TRS；local_h 齐次点；world_h=M*local_h。
// world_aabb_*：8 顶点包络世界 AABB；min_y 取最低点给地板。
// quat_from_model_euler / euler_xyz_from_rot_mat / sync_* / integrate_*：姿态表示与积分。
// world_inertia_inv_apply：体对角惯量逆映射到世界。
// MechanicsWorldAABB / build_mechanics_obb / sat_obb_obb：碰撞几何与 SAT。
// Octree* / aabb_overlap：粗测八叉树。
// g_handle_to_*：跨帧速度、角速度、四元数、休眠。
// update_physics：阶段1 收集与属性；2 外力阻尼；3 预测+AABB+惯量；4 写 scene AABB；
//   5 八叉树+窄相+冲量摩擦+位置校正；6 积分+地板；休眠；clean_cache。
// ============================================================================

#ifndef CORONA_MECHANICS_USE_OBB_SAT
#define CORONA_MECHANICS_USE_OBB_SAT 0
#endif

namespace {

// 按分量构造 fvec3（result：输出向量）
constexpr ktm::fvec3 make_fvec3(float x, float y, float z) {
    ktm::fvec3 result; // 返回值缓冲
    result.x = x;      // X
    result.y = y;      // Y
    result.z = z;      // Z
    return result;     // 按值传出
}

// 取 3×3 矩阵第 row 行 col 列（数学下标），等价 M[col][row]
inline float mat3_at_rc(const ktm::fmat3x3& M, std::size_t row, std::size_t col) {
    return M[col][row];
}
inline float mat4_at_rc(const ktm::fmat4x4& M, std::size_t row, std::size_t col) {
    return M[col][row];
}

inline ktm::fvec3 vec3_add(const ktm::fvec3& a, const ktm::fvec3& b) {
    return make_fvec3(a.x+b.x, a.y+b.y, a.z+b.z); // 逐分量加
}
inline ktm::fvec3 vec3_sub(const ktm::fvec3& a, const ktm::fvec3& b) {
    return make_fvec3(a.x-b.x, a.y-b.y, a.z-b.z); // 逐分量减
}
inline ktm::fvec3 vec3_mul(const ktm::fvec3& v, float s) {
    return make_fvec3(v.x*s, v.y*s, v.z*s); // 标量乘向量
}

// local：局部点；返回：同一几何点在世界的坐标
inline ktm::fvec3 transform_local_point_to_world(const Corona::ModelTransform& t, const ktm::fvec3& local) {
    const ktm::fmat4x4 M = t.compute_matrix();   // 4×4 TRS
    const ktm::fvec4 local_h(local, 1.0f);       // w=1 表示点而非方向
    const ktm::fvec4 world_h = M * local_h;      // 齐次乘法
    return make_fvec3(world_h.x, world_h.y, world_h.z); // 透视下 w 应为 1，取 xyz 即可
}

// lmin,lmax：局部轴对齐盒；out_*：世界 AABB 及中心
inline void world_aabb_from_local_bounds(const Corona::ModelTransform& t,
                                         const ktm::fvec3& lmin, const ktm::fvec3& lmax,
                                         ktm::fvec3& out_min, ktm::fvec3& out_max, ktm::fvec3& out_center) {
    ktm::fvec3 c0 = transform_local_point_to_world(t, make_fvec3(lmin.x, lmin.y, lmin.z)); // 角点 (min,min,min)
    out_min = c0;  // 初始化 min
    out_max = c0;  // 初始化 max
    for (int i = 1; i < 8; ++i) { // i 从 1 到 7：其余顶点
        const float x = (i & 1) != 0 ? lmax.x : lmin.x; // 按位选 min 或 max
        const float y = (i & 2) != 0 ? lmax.y : lmin.y;
        const float z = (i & 4) != 0 ? lmax.z : lmin.z;
        const ktm::fvec3 wp = transform_local_point_to_world(t, make_fvec3(x, y, z)); // 世界顶点
        out_min.x = std::min(out_min.x, wp.x); // 扩张 min.x
        out_min.y = std::min(out_min.y, wp.y);
        out_min.z = std::min(out_min.z, wp.z);
        out_max.x = std::max(out_max.x, wp.x); // 扩张 max.x
        out_max.y = std::max(out_max.y, wp.y);
        out_max.z = std::max(out_max.z, wp.z);
    }
    out_center = make_fvec3(
        (out_min.x + out_max.x) * 0.5f, // 形心 X
        (out_min.y + out_max.y) * 0.5f,
        (out_min.z + out_max.z) * 0.5f
    );
}

// 返回世界包络盒在 Y 轴上的最小值（贴地）
inline float world_aabb_min_y(const Corona::ModelTransform& t,
                              const ktm::fvec3& lmin, const ktm::fvec3& lmax) {
    ktm::fvec3 out_min{}, out_max{}, out_center{}; // out_max/center 此处不用
    world_aabb_from_local_bounds(t, lmin, lmax, out_min, out_max, out_center);
    return out_min.y; // 最低点高度
}

// euler：弧度，顺序 XYZ；返回与 TRS 矩阵一致的单位四元数
inline ktm::fquat quat_from_model_euler(const ktm::fvec3& euler) {
    const ktm::fquat qx = ktm::fquat::from_angle_x(euler.x); // 绕 X
    const ktm::fquat qy = ktm::fquat::from_angle_y(euler.y); // 绕 Y
    const ktm::fquat qz = ktm::fquat::from_angle_z(euler.z); // 绕 Z
    return qz * qy * qx; // 组合旋转
}

// R：旋转矩阵；euler：输出的 XYZ 欧拉（弧度）
inline void euler_xyz_from_rot_mat(const ktm::fmat3x3& R, ktm::fvec3& euler) {
    const float sy = mat3_at_rc(R, 0, 2);    // 用于 asin 的元素
    const float pi = 3.1415926535f;          // π

    if (sy > 0.999f) {                      // 俯仰近 +90°，万向节锁
        euler.x = 0;                        // 俯仰锁定下 x 置 0
        euler.y = pi * 0.5f;                // y = +π/2
        euler.z = std::atan2(mat3_at_rc(R, 1, 0), mat3_at_rc(R, 1, 1)); // 用 atan2 定 z
    } else if (sy < -0.999f) {              // 俯仰近 -90°
        euler.x = 0;
        euler.y = -pi * 0.5f;
        euler.z = std::atan2(mat3_at_rc(R, 1, 0), mat3_at_rc(R, 1, 1));
    } else {
        euler.y = std::asin(sy);            // 一般情形：求中间角
        euler.x = std::atan2(-mat3_at_rc(R, 1, 2), mat3_at_rc(R, 2, 2));
        euler.z = std::atan2(-mat3_at_rc(R, 0, 1), mat3_at_rc(R, 0, 0));
    }
}
// q：四元数缓存；euler：写回 Transform 的欧拉角
inline void sync_euler_from_orientation_quat(ktm::fquat& q, ktm::fvec3& euler) {
    if (q.r < 0.0f) {       // 实为同一旋转的另一表示
        q.i = -q.i;         // i 分量取反
        q.j = -q.j;        // j
        q.k = -q.k;        // k
        q.r = -q.r;        // r
    }
    euler_xyz_from_rot_mat(q.matrix3x3(), euler); // 由旋转矩阵反解欧拉
}

// 显式积分四元数导数 dq/dt = 0.5*(0,ω)*q
inline void integrate_orientation_quat(ktm::fquat& q, const ktm::fvec3& omega_world, float dt) {
    const ktm::fquat wq = ktm::fquat::real_imag(0.0f, omega_world); // 纯虚四元数装角速度
    const ktm::fquat dq = wq * q;                                   // 与 q 相乘得导出
    q.i += 0.5f * dt * dq.i;                                        // 累加 i 分量变化
    q.j += 0.5f * dt * dq.j;
    q.k += 0.5f * dt * dq.k;
    q.r += 0.5f * dt * dq.r;
    q = ktm::normalize(q);                                          // 保持单位四元数
}

// AABB 在方向 dir 上的极值点（近似接触用）
inline ktm::fvec3 aabb_support_world(const ktm::fvec3& center, const ktm::fvec3& half,
                                     const ktm::fvec3& dir) {
    return make_fvec3(
        center.x + (dir.x >= 0.0f ? half.x : -half.x), // dir 指向 +X 时取右侧面
        center.y + (dir.y >= 0.0f ? half.y : -half.y),
        center.z + (dir.z >= 0.0f ? half.z : -half.z));
}

// 刚体上一点的世界系线速度 = 质心平动 + 转动项 ω×r
inline ktm::fvec3 velocity_at_point_world(const ktm::fvec3& v_com, const ktm::fvec3& omega_world,
                                          const ktm::fvec3& r_com_to_point) {
    const ktm::fvec3 wxr = ktm::cross(omega_world, r_com_to_point); // 叉乘
    return make_fvec3(v_com.x + wxr.x, v_com.y + wxr.y, v_com.z + wxr.z); // 矢量加
}

// 世界系向量左乘 I^{-1}（对角惯量模型 + 当前姿态 R）
inline ktm::fvec3 world_inertia_inv_apply(const ktm::fmat3x3& R_body_to_world,
                                          const ktm::fvec3& inertia_inv_body,
                                          const ktm::fvec3& w_world) {
    const ktm::fmat3x3 RT = ktm::transpose(R_body_to_world); // 逆旋转（正交阵）
    ktm::fvec3 b = RT * w_world;   // 世界→体
    b.x *= inertia_inv_body.x;     // 体坐标乘以 1/Ix
    b.y *= inertia_inv_body.y;
    b.z *= inertia_inv_body.z;
    return R_body_to_world * b;    // 体→世界
}

// 本帧单个 mechanics 物体的碰撞/渲染用几何缓存
struct MechanicsWorldAABB {
    std::uintptr_t handle;           // mechanics 设备句柄键
    std::uintptr_t transform_handle; // 几何上的 ModelTransform 句柄
    ktm::fvec3 min_world;            // 世界 AABB 最小角
    ktm::fvec3 max_world;            // 世界 AABB 最大角
    ktm::fvec3 center_world;         // AABB 中心（亦作 AABB 窄相参考点）
    ktm::fvec3 half_extents;         // 世界 AABB 半尺寸
    ktm::fvec3 local_min;            // mechanics 局部 min_xyz
    ktm::fvec3 local_max;            // mechanics 局部 max_xyz
    ktm::fvec3 obb_center;           // OBB 中心（世界）
    ktm::fvec3 obb_u, obb_v, obb_w;  // OBB 三个正交轴单位向量（世界）
    float obb_hu{}, obb_hv{}, obb_hw{}; // 对应轴上半轴长
    ktm::fmat3x3 rot_body_to_world{}; // 由预测四元数得到的旋转矩阵
    ktm::fvec3 inertia_inv_body{};    // 体坐标 (1/Ix,1/Iy,1/Iz)
};


// entry：读写 OBB 字段；t：用于把局部点变到世界
inline void build_mechanics_obb(MechanicsWorldAABB& entry, const Corona::ModelTransform& t) {
    const ktm::fvec3 c_l = make_fvec3(
        (entry.local_min.x + entry.local_max.x) * 0.5f, // 局部盒中心 X
        (entry.local_min.y + entry.local_max.y) * 0.5f,
        (entry.local_min.z + entry.local_max.z) * 0.5f
    );
    const ktm::fvec3 e_l = make_fvec3(
        (entry.local_max.x - entry.local_min.x) * 0.5f, // 沿局部 X 的半棱长
        (entry.local_max.y - entry.local_min.y) * 0.5f,
        (entry.local_max.z - entry.local_min.z) * 0.5f
    );
    entry.obb_center = transform_local_point_to_world(t, c_l); // 盒心到世界
    ktm::fvec3 ax = vec3_sub(transform_local_point_to_world(t, vec3_add(c_l, make_fvec3(e_l.x, 0.f, 0.f))),
                             entry.obb_center); // +局部 X 轴端点相对心的向量（世界）
    ktm::fvec3 ay = vec3_sub(transform_local_point_to_world(t, vec3_add(c_l, make_fvec3(0.f, e_l.y, 0.f))),
                             entry.obb_center); // +Y
    ktm::fvec3 az = vec3_sub(transform_local_point_to_world(t, vec3_add(c_l, make_fvec3(0.f, 0.f, e_l.z))),
                             entry.obb_center); // +Z
    const float lu = ktm::length(ax); // 轴方向未归一长度
    const float lv = ktm::length(ay);
    const float lz = ktm::length(az);
    constexpr float obb_eps = 1e-8f; // 退化盒厚度下限
    if (lu > obb_eps) {
        const float inv = 1.0f / lu; // 归一化因子
        entry.obb_u = make_fvec3(ax.x * inv, ax.y * inv, ax.z * inv); // 单位轴 u
        entry.obb_hu = lu; // 半轴长取几何长度
    } else {
        entry.obb_u = make_fvec3(1.0f, 0.0f, 0.0f); // 默认 X
        entry.obb_hu = obb_eps; // 极小半长避免除零
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
    return hu * std::abs(ktm::dot(u, L_unit))   // u 轴贡献
        + hv * std::abs(ktm::dot(v, L_unit))   // v 轴
        + hw * std::abs(ktm::dot(w, L_unit));   // w 轴
}

// 在方向 dir 上取 OBB 支撑点：c 为中心；u,v,w 轴与 hu,hv,hw 半长；沿 dir 取最远顶点
inline ktm::fvec3 obb_support_point(const ktm::fvec3& c,
                                   const ktm::fvec3& u, const ktm::fvec3& v, const ktm::fvec3& w,
                                   float hu, float hv, float hw,
                                   const ktm::fvec3& dir) {
    ktm::fvec3 p = c; // 从中心出发
    const float su = (ktm::dot(u, dir) >= 0.f) ? hu : -hu; // u 轴上取与 dir 同向或反向端点
    const float sv = (ktm::dot(v, dir) >= 0.f) ? hv : -hv;
    const float sw = (ktm::dot(w, dir) >= 0.f) ? hw : -hw;
    p = vec3_add(p, vec3_mul(u, su)); // 沿 u 平移 su*u
    p = vec3_add(p, vec3_mul(v, sv));
    p = vec3_add(p, vec3_mul(w, sw));
    return p; // 角点之一
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
    constexpr float ax_eps = 1e-8f;              // 轴长过短视为退化，跳过该轴
    const ktm::fvec3 d_cb = vec3_sub(cb, ca);        // B 中心相对 A 中心的位移
    float best_ov = std::numeric_limits<float>::max(); // 当前找到的最小正重叠（最深穿透轴）
    bool have_axis = false;                          // 是否至少成功检测过一条有效轴
    ktm::fvec3 best_L = make_fvec3(1.0f, 0.0f, 0.0f); // 最优分离轴方向（单位向量）

    // 在候选轴 Lraw 上做 1D SAT：两 OBB 在轴上的投影区间若不相交则整体分离
    auto test_axis = [&](const ktm::fvec3& Lraw) -> bool {
        const float len = ktm::length(Lraw);       // 未归一轴长
        if (len < ax_eps) {                        // 叉积近似零向量
            return true;                           // 不计入分离轴，视为通过
        }
        const float inv = 1.0f / len;              // 归一化因子
        const ktm::fvec3 L = make_fvec3(Lraw.x * inv, Lraw.y * inv, Lraw.z * inv); // 单位轴
        const float rA = obb_radius_on_axis(hau, hav, haw, ua, va, wa, L); // A 投影半宽
        const float rB = obb_radius_on_axis(hbu, hbv, hbw, ub, vb, wb, L); // B 投影半宽
        const float cA = ktm::dot(ca, L);        // A 中心在轴上坐标
        const float cB = ktm::dot(cb, L);        // B 中心在轴上坐标
        const float minA = cA - rA;              // A 投影区间左端
        const float maxA = cA + rA;              // A 投影区间右端
        const float minB = cB - rB;              // B 左端
        const float maxB = cB + rB;              // B 右端
        const float overlap = std::min(maxA, maxB) - std::max(minA, minB); // 两区间重叠长度
        if (overlap <= 0.f) {                    // 存在分离轴
            return false;                        // 无事相交
        }
        if (overlap < best_ov) {                 // 记录重叠更小的轴（更接近分离）
            best_ov = overlap;
            best_L = L;
            have_axis = true;
        }
        return true;                             // 本轴未排除相交
    };

    if (!test_axis(ua)) return false;            // A 的三个面法向
    if (!test_axis(va)) return false;
    if (!test_axis(wa)) return false;
    if (!test_axis(ub)) return false;            // B 的三个面法向
    if (!test_axis(vb)) return false;
    if (!test_axis(wb)) return false;

    const ktm::fvec3 crosses[9] = {              // 边与边的叉积方向，共 9 条
        ktm::cross(ua, ub), ktm::cross(ua, vb), ktm::cross(ua, wb),
        ktm::cross(va, ub), ktm::cross(va, vb), ktm::cross(va, wb),
        ktm::cross(wa, ub), ktm::cross(wa, vb), ktm::cross(wa, wb)
    };
    for (const ktm::fvec3& cax : crosses) {       // 逐条测试叉积轴
        if (!test_axis(cax)) {
            return false;
        }
    }

    if (!have_axis) {                             // 理论上不应发生：无有效轴却通过全部测试
        return false;
    }
    if (ktm::dot(best_L, d_cb) < 0.f) {          // 令 best_L 与 A→B 同向，作为 A→B 法线
        best_L = make_fvec3(-best_L.x, -best_L.y, -best_L.z);
    }
    out_normal = best_L;                         // 输出接触法线（单位向量）
    out_penetration = best_ov;                   // 输出沿该轴穿透深度估计
    return true;
}

/*
 八叉树节点中的物体数据结构
 存储物体句柄和AABB包围盒
 */
struct OctreeEntry {
    std::uintptr_t handle;        // 物体唯一标识句柄
    ktm::fvec3 min_bounds;        // AABB包围盒最小边界
    ktm::fvec3 max_bounds;        // AABB包围盒最大边界
};

/*
 八叉树节点结构
 八叉树是节点包含8个子节点
 */
struct OctreeNode {
    ktm::fvec3 min_bounds;                                    // 当前节点的AABB最小边界
    ktm::fvec3 max_bounds;                                    // 当前节点的AABB最大边界
    std::vector<OctreeEntry> entries;                         // 叶子节点存储的物体列表
    std::unique_ptr<std::array<OctreeNode, 8>> children;      // 子节点（8个，非叶子节点才有）
};

// 八叉树常量
constexpr int kOctreeMaxDepth = 6;            // 八叉树最大深度（防止过深）
constexpr int kOctreeMaxObjectsPerLeaf = 4;   // 叶子节点最大物体数（超过分裂）

/*
 检测两个AABB包围盒是否重叠
 a_min A物体AABB最小边界
 a_max A物体AABB最大边界
 b_min B物体AABB最小边界
 b_max B物体AABB最大边界
*/
inline bool aabb_overlap(const ktm::fvec3& a_min, const ktm::fvec3& a_max,
                         const ktm::fvec3& b_min, const ktm::fvec3& b_max) {
    //三个轴都有重叠才视为重叠
    return (a_min.x <= b_max.x && a_max.x >= b_min.x) &&
           (a_min.y <= b_max.y && a_max.y >= b_min.y) &&
           (a_min.z <= b_max.z && a_max.z >= b_min.z);
}

/*
  初始化八叉树节点的8个子节点
 */
void octree_init_children(OctreeNode& node) {
    node.children = std::make_unique<std::array<OctreeNode, 8>>(); // 分配 8 子节点数组
    auto& children = *node.children;               // 解引用便于书写

    const ktm::fvec3 center = make_fvec3(          // 父 AABB 的几何中心，八分划分的交点
        (node.min_bounds.x + node.max_bounds.x) * 0.5f,
        (node.min_bounds.y + node.max_bounds.y) * 0.5f,
        (node.min_bounds.z + node.max_bounds.z) * 0.5f
    );
    const auto& min = node.min_bounds;            // 父 min 角
    const auto& max = node.max_bounds;            // 父 max 角

    children[0].min_bounds = min;                 // 卦限 x∈[min,center] 等（靠近 min 角那一块）
    children[0].max_bounds = center;

    children[1].min_bounds = make_fvec3(center.x, min.y, min.z); // +X 侧下半块
    children[1].max_bounds = make_fvec3(max.x, center.y, center.z);

    children[2].min_bounds = make_fvec3(min.x, center.y, min.z); // +Y 侧
    children[2].max_bounds = make_fvec3(center.x, max.y, center.z);

    children[3].min_bounds = make_fvec3(center.x, center.y, min.z); // +X+Y 底面象限
    children[3].max_bounds = make_fvec3(max.x, max.y, center.z);

    children[4].min_bounds = make_fvec3(min.x, min.y, center.z); // +Z 侧近 min
    children[4].max_bounds = make_fvec3(center.x, center.y, max.z);

    children[5].min_bounds = make_fvec3(center.x, min.y, center.z); // +X+Z
    children[5].max_bounds = make_fvec3(max.x, center.y, max.z);

    children[6].min_bounds = make_fvec3(min.x, center.y, center.z); // +Y+Z
    children[6].max_bounds = make_fvec3(center.x, max.y, max.z);

    children[7].min_bounds = center;              // 靠近 max 角那一块
    children[7].max_bounds = max;
}
// 八叉树插入物体
// handle：物体 id；obj_min/max：物体世界 AABB；depth：当前树深（根为 0）
void octree_insert(OctreeNode& node, std::uintptr_t handle,
                   const ktm::fvec3& obj_min, const ktm::fvec3& obj_max, int depth) {
    if (!aabb_overlap(obj_min, obj_max, node.min_bounds, node.max_bounds)) {
        return;                                    // 与本节点无关
    }

    const bool is_leaf = (node.children == nullptr); // nullptr 表示尚未分裂的叶

    if (is_leaf) {
        const bool should_split =                  // 是否达到分裂条件
            depth < kOctreeMaxDepth &&             // 未超过最大深度
            static_cast<int>(node.entries.size()) >= kOctreeMaxObjectsPerLeaf; // 叶内物体够多

        if (!should_split) {
            node.entries.push_back({handle, obj_min, obj_max}); // 直接堆在叶子里
            return;
        }
        octree_init_children(node);                // 生成立即 8 子

        for (const OctreeEntry& e : node.entries) { // 旧物体重新插入（可能进多个子──跨子节点）
            for (int i = 0; i < 8; ++i) {
                octree_insert((*node.children)[i], e.handle, e.min_bounds, e.max_bounds, depth + 1);
            }
        }
        node.entries.clear();                     // 叶改内节点后清空本层列表

        for (int i = 0; i < 8; ++i) {             // 当前新插入物体同样可能进多子
            octree_insert((*node.children)[i], handle, obj_min, obj_max, depth + 1);
        }
        return;
    }

    const ktm::fvec3 center = make_fvec3(         // 内节点再次计算中心（与 init 时一致）
        (node.min_bounds.x + node.max_bounds.x) * 0.5f,
        (node.min_bounds.y + node.max_bounds.y) * 0.5f,
        (node.min_bounds.z + node.max_bounds.z) * 0.5f
    );

    const ktm::fvec3& min_bounds = node.min_bounds; // 别名，少打字
    const ktm::fvec3& max_bounds = node.max_bounds;

    const bool overlap[8] = {                    // 物体 AABB 与 8 个子盒是否相交
        aabb_overlap(obj_min, obj_max, min_bounds, center),
        aabb_overlap(obj_min, obj_max,
                     make_fvec3(center.x, min_bounds.y, min_bounds.z),
                     make_fvec3(max_bounds.x, center.y, center.z)),
        aabb_overlap(obj_min, obj_max,
                     make_fvec3(min_bounds.x, center.y, min_bounds.z),
                     make_fvec3(center.x, max_bounds.y, center.z)),
        aabb_overlap(obj_min, obj_max,
                     make_fvec3(center.x, center.y, min_bounds.z),
                     make_fvec3(max_bounds.x, max_bounds.y, center.z)),
        aabb_overlap(obj_min, obj_max,
                     make_fvec3(min_bounds.x, min_bounds.y, center.z),
                     make_fvec3(center.x, center.y, max_bounds.z)),
        aabb_overlap(obj_min, obj_max,
                     make_fvec3(center.x, min_bounds.y, center.z),
                     make_fvec3(max_bounds.x, center.y, max_bounds.z)),
        aabb_overlap(obj_min, obj_max,
                     make_fvec3(min_bounds.x, center.y, center.z),
                     make_fvec3(center.x, max_bounds.y, max_bounds.z)),
        aabb_overlap(obj_min, obj_max, center, max_bounds)
    };

    for (int i = 0; i < 8; ++i) {                 // 只递归进与物体有交的子树
        if (overlap[i]) {
            octree_insert((*node.children)[i], handle, obj_min, obj_max, depth + 1);
        }
    }
}
// 收集所有可能碰撞的物体对
void octree_collect_pairs(const OctreeNode& node,
                          std::vector<std::pair<std::uintptr_t, std::uintptr_t>>& out) {
    //非叶子节点：递归遍历子节点
    if (node.children) {
        for (int i = 0; i < 8; ++i) {
            octree_collect_pairs((*node.children)[i], out);
        }
        return;
    }

    //叶子节点：生成所有物体对（i<j，避免重复）
    for (std::size_t i = 0; i < node.entries.size(); ++i) {
        for (std::size_t j = i + 1; j < node.entries.size(); ++j) {
            std::uintptr_t a = node.entries[i].handle;
            std::uintptr_t b = node.entries[j].handle;
            if (a > b) std::swap(a, b); // 保证a<=b，统一碰撞对顺序
            out.emplace_back(a, b);
        }
    }
}

void octree_dedupe_pairs(std::vector<std::pair<std::uintptr_t, std::uintptr_t>>& pairs) {
    if (pairs.empty()) return;                   // 空则无需排序
    std::sort(pairs.begin(), pairs.end());      // pair 字典序，相同对相邻
    pairs.erase(std::unique(pairs.begin(), pairs.end()), pairs.end()); // 删除连续重复
}

static std::unordered_map<std::uintptr_t, ktm::fvec3> g_handle_to_velocity;   // 线速度 m/s
static std::unordered_map<std::uintptr_t, ktm::fvec3> g_handle_to_angular_vel; // 角速度 rad/s 世界系
static std::unordered_map<std::uintptr_t, ktm::fquat> g_handle_orientation_quat; // 与欧拉同步的朝向
static std::unordered_map<std::uintptr_t, bool> g_handle_to_sleeping;      // true 则本帧不积分
static std::unordered_map<std::uintptr_t, float> g_handle_to_sleep_timer;  // 低速累计时长

}

namespace Corona::Systems {

bool MechanicsSystem::initialize(Kernel::ISystemContext* ctx) {
    (void)ctx; // 无初始化所需上下文时显式消除未使用告警
    CFW_LOG_INFO("MechanicsSystem initialized");
    return true; // 恒成功；失败时可改为 false
}

void MechanicsSystem::update() {
    update_physics(); // 单帧物理 tick 入口
}

void MechanicsSystem::shutdown() {
    g_handle_to_velocity.clear();     // 释放所有跨帧动力学状态
    g_handle_to_angular_vel.clear();
    g_handle_orientation_quat.clear();
    g_handle_to_sleeping.clear();
    g_handle_to_sleep_timer.clear();
    CFW_LOG_INFO("MechanicsSystem shutdown, all caches cleared");
}

// 物理主循环（单帧）：搜集物体 → 积分外力(重力/阻尼) → 建世界 AABB → 粗/细碰撞改速度 → 积分位姿 → 地板 → 休眠 → 清理缓存
void MechanicsSystem::update_physics() {
    // 常量：时间步、摩擦、休眠、惯量下限等（可按手感调参）
    const float floor_eps = 0.01f;          // 地板碰撞容差
    const float low_vel_threshold = 0.05f;  // 低速衰减阈值
    const float min_valid_dt = 1.0f / 120.0f; // 最小有效时间步
    const float max_valid_dt = 1.0f / 30.0f;  // 最大有效时间步
    const float zero_vel_threshold = 0.01f;  // 速度归零阈值
    const float friction_coeff = 0.35f;      // 统一摩擦系数
    const float sleep_threshold = 0.05f;       // 休眠速度阈值
    const float sleep_threshold_sq = sleep_threshold * sleep_threshold; // 休眠速度阈值平方
    const float sleep_time_needed = 0.4f;      // 静止多久后休眠
    const float min_inertia = 0.0001f;        // 最小转动惯量，防止除零
    const float rot_damping_factor = 0.97f;   // 基础旋转阻尼系数

    // 本帧临时表：质量/阻尼/恢复系数
    std::unordered_map<std::uintptr_t, float> handle_to_mass;
    std::unordered_map<std::uintptr_t, float> handle_to_damping;
    std::unordered_map<std::uintptr_t, float> handle_to_restitution;

    // --- 从 SharedDataHub 取各存储的引用（几何、变换、场景、环境等）---
    auto& mechanics_storage = SharedDataHub::instance().mechanics_storage();   // mechanics 组件数据
    auto& geometry_storage = SharedDataHub::instance().geometry_storage();     // 网格/包围体句柄
    auto& transform_storage = SharedDataHub::instance().model_transform_storage(); // 位姿写回目标
    auto& scene_storage = SharedDataHub::instance().scene_storage();           // 场景与 actor 列表
    auto& actor_storage = SharedDataHub::instance().actor_storage();
    auto& profile_storage = SharedDataHub::instance().profile_storage();        // actor→mechanics 映射
    auto& environment_storage = SharedDataHub::instance().environment_storage(); // 全局 dt/重力等

    float fixed_dt = 1.0f / 60.0f;                // 积分步长秒；可被 environment 覆盖
    ktm::fvec3 gravity = make_fvec3(0.0f, -9.8f, 0.0f); // m/s²
    float floor_restitution = 0.6f;               // 地板法向弹性系数 0..1
    float floor_y = 0.0f;                         // 无穷大水平面高度

    std::vector<std::uintptr_t> mechanics_handles; // 本帧参与物理的 mechanics 去重列表
    mechanics_handles.reserve(64);
    std::vector<std::uintptr_t> scene_handles;    // 参与遍历的 scene 指针键，用于写 scene AABB
    scene_handles.reserve(4);

    // --- 阶段 1：遍历场景 → 读环境(gravity/floor/dt) → 展开 Actor/Profile → 收集 mechanics_handle ---
    for (const auto& scene : scene_storage) {
        scene_handles.push_back(reinterpret_cast<std::uintptr_t>(&scene));

        // 若绑定了 environment：覆盖重力、地板参数，并钳制 fixed_dt
        if (scene.environment != 0) {
            if (auto env = environment_storage.acquire_read(scene.environment)) {
                gravity = env->gravity;
                floor_y = env->floor_y;
                floor_restitution = env->floor_restitution;
                // 限制时间步范围，防止外部传入异常值导致抖动
                fixed_dt = std::clamp(env->fixed_dt, min_valid_dt, max_valid_dt);
            }
        }

        for (auto actor_handle : scene.actor_handles) {
            if (auto actor = actor_storage.acquire_read(actor_handle)) {
                for (auto profile_handle : actor->profile_handles) {
                    if (auto profile = profile_storage.acquire_read(profile_handle)) {
                        if (auto h = profile->mechanics_handle) {
                            mechanics_handles.push_back(h);

                            // 首次见到该 mechanics：初始化全局缓存中的线速度、角速度、休眠计时
                            if (g_handle_to_velocity.find(h) == g_handle_to_velocity.end()) {
                                g_handle_to_velocity[h] = make_fvec3(0.0f, 0.0f, 0.0f);
                                g_handle_to_angular_vel[h] = make_fvec3(0.0f, 0.0f, 0.0f);
                                g_handle_to_sleeping[h] = false;
                                g_handle_to_sleep_timer[h] = 0.0f;
                            }

                            // 读 MechanicsDevice：质量/阻尼/恢复；读失败则用默认值
                            if (auto m_acc = mechanics_storage.acquire_read(h)) {
                                handle_to_mass[h] = m_acc->mass;
                                handle_to_damping[h] = m_acc->damping;
                                handle_to_restitution[h] = m_acc->restitution;
                            } else {
                                handle_to_mass[h] = 1.0f;
                                handle_to_damping[h] = 0.99f;
                                handle_to_restitution[h] = 0.8f;
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

    std::sort(mechanics_handles.begin(), mechanics_handles.end()); // 排序使 unique 有效
    mechanics_handles.erase(std::unique(mechanics_handles.begin(), mechanics_handles.end()), mechanics_handles.end()); // 去重

    if (mechanics_handles.empty()) {
        return;                                // 无物体则整帧跳过
    }

    // --- 阶段 2：半隐式前推速度（仅非休眠体）：重力加速度 × dt，再乘线性/角速度阻尼 ---
    for (std::uintptr_t h : mechanics_handles) { // 对存活列表逐个施力
        if (g_handle_to_sleeping[h]) continue;   // 休眠体本阶段不改速度

        float damping = handle_to_damping[h];    // 线性阻尼乘子（每帧乘一次近似阻力）
        auto& av = g_handle_to_angular_vel[h];   // 可修改的角速度引用
        // Environment.gravity 为重力加速度 g
        g_handle_to_velocity[h].x += gravity.x * fixed_dt;
        g_handle_to_velocity[h].y += gravity.y * fixed_dt;
        g_handle_to_velocity[h].z += gravity.z * fixed_dt;

        // 线性阻尼（近似空气阻力）
        g_handle_to_velocity[h].x *= damping;
        g_handle_to_velocity[h].y *= damping;
        g_handle_to_velocity[h].z *= damping;
        // 角速度阻尼（略强于线性，避免永转）
        float rot_damping = std::max(damping * rot_damping_factor, 0.9f); // 保证最小阻尼
        av.x *= rot_damping;
        av.y *= rot_damping;
        av.z *= rot_damping;
    }

    // --- 阶段 3：为每个 mechanics 读几何/变换 → 首遇则建四元数朝向 → 预测位姿 → 世界 AABB + 长方体对角惯量（世界系冲量用）---
    std::vector<MechanicsWorldAABB> mechanics_data;
    mechanics_data.reserve(mechanics_handles.size());
    std::unordered_map<std::uintptr_t, std::size_t> handle_to_index;

    for (std::uintptr_t h : mechanics_handles) { // 为每个力学体准备碰撞与惯量数据
        auto m_acc = mechanics_storage.acquire_read(h); // mechanics 组件读锁
        if (!m_acc) continue;             // 无数据则跳过
        const auto& m = *m_acc;            // 其 min/max、geometry_handle

        auto geom_acc = geometry_storage.acquire_read(m.geometry_handle);
        if (!geom_acc) continue;

        auto tx_acc = transform_storage.acquire_read(geom_acc->transform_handle);
        if (!tx_acc) continue;
        const auto& t = *tx_acc;         // 只读当前变换（复制后做预测）

        ktm::fvec3 e_local = make_fvec3(  // mechanics 局部半棱长
            (m.max_xyz.x - m.min_xyz.x) * 0.5f,
            (m.max_xyz.y - m.min_xyz.y) * 0.5f,
            (m.max_xyz.z - m.min_xyz.z) * 0.5f
        );

        MechanicsWorldAABB entry;         // 本物体本帧用的缓存结构
        entry.handle = h;
        entry.transform_handle = geom_acc->transform_handle; // 之后写位置修正用同一 handle
        entry.local_min = m.min_xyz;
        entry.local_max = m.max_xyz;
        // 无记录则从当前欧拉初始化四元数
        if (g_handle_orientation_quat.find(h) == g_handle_orientation_quat.end()) {
            g_handle_orientation_quat[h] = quat_from_model_euler(t.euler_rotation);
        }
        ktm::fquat q_pred = g_handle_orientation_quat[h]; // 复制：预测用，不提前改全局缓存
        Corona::ModelTransform t_collision = t;   // 复制当前变换
        if (!g_handle_to_sleeping[h]) {
            const ktm::fvec3& vc = g_handle_to_velocity[h]; // 引用线速度
            t_collision.position.x += vc.x * fixed_dt;    // 外推平移用于碰撞检测
            t_collision.position.y += vc.y * fixed_dt;
            t_collision.position.z += vc.z * fixed_dt;
            integrate_orientation_quat(q_pred, g_handle_to_angular_vel[h], fixed_dt); // 外推旋转
        }
        sync_euler_from_orientation_quat(q_pred, t_collision.euler_rotation); // 矩阵一致化 euler
        world_aabb_from_local_bounds(t_collision, entry.local_min, entry.local_max,
                                     entry.min_world, entry.max_world, entry.center_world);
        entry.half_extents = make_fvec3(
            (entry.max_world.x - entry.min_world.x) * 0.5f, // 世界 AABB 半宽
            (entry.max_world.y - entry.min_world.y) * 0.5f,
            (entry.max_world.z - entry.min_world.z) * 0.5f
        );
#if CORONA_MECHANICS_USE_OBB_SAT
        build_mechanics_obb(entry, t_collision); // 由同一预测位姿构造 OBB
#endif

        const float mass = handle_to_mass[h];    // kg
        const float w = std::abs(e_local.x * t.scale.x) * 2.0f; // 世界系盒子 X 向全长（缩放后）
        const float hh = std::abs(e_local.y * t.scale.y) * 2.0f;
        const float d = std::abs(e_local.z * t.scale.z) * 2.0f;
        float Ix = mass * (hh * hh + d * d) / 12.0f; // 长方体主轴惯量（近似；均质 box）
        float Iy = mass * (w * w + d * d) / 12.0f;
        float Iz = mass * (w * w + hh * hh) / 12.0f;
        Ix = std::max(Ix, min_inertia);           // 下限防止除零
        Iy = std::max(Iy, min_inertia);
        Iz = std::max(Iz, min_inertia);
        entry.rot_body_to_world = q_pred.matrix3x3();   // 体→世界旋转（预测姿态）
        entry.inertia_inv_body = make_fvec3(1.0f / Ix, 1.0f / Iy, 1.0f / Iz); // 体系逆惯量对角

        handle_to_index[h] = mechanics_data.size();     // 句柄→本轮 mechanics_data 下标
        mechanics_data.push_back(entry);
    }

    // --- 阶段 4：把所有物体的世界 AABB 并起来写入 Scene（供裁剪/调试等），并把 floor_y 纳入场景包围，避免物体落地面却被剔除 ---
    if (!mechanics_data.empty()) {
        ktm::fvec3 scene_min = mechanics_data[0].min_world; // 世界 AABB 最小角
        ktm::fvec3 scene_max = mechanics_data[0].max_world; // 世界 AABB 最大角

        for (const auto& e : mechanics_data) {
            scene_min.x = std::min(scene_min.x, e.min_world.x); // 逐轴扩张包络
            scene_min.y = std::min(scene_min.y, e.min_world.y);
            scene_min.z = std::min(scene_min.z, e.min_world.z);
            scene_max.x = std::max(scene_max.x, e.max_world.x);
            scene_max.y = std::max(scene_max.y, e.max_world.y);
            scene_max.z = std::max(scene_max.z, e.max_world.z);
        }
        scene_min.y = std::min(scene_min.y, floor_y - floor_eps); // 下移 min.y，保证地板带进入 Scene AABB

        ktm::fvec3 scene_center = make_fvec3(
            (scene_min.x + scene_max.x) * 0.5f,
            (scene_min.y + scene_max.y) * 0.5f,
            (scene_min.z + scene_max.z) * 0.5f
        );

        for (auto sh : scene_handles) { // 每个被遍历过的 scene 写同一套包围（多场景时行为一致）
            if (auto s_w = scene_storage.acquire_write(sh)) {
                s_w->min_world = scene_min;
                s_w->max_world = scene_max;
                s_w->center_world = scene_center;
            }
        }
    }

    // --- 阶段 5：八叉树粗测 → 世界 AABB 再筛 → 窄相（AABB 或 OBB+SAT）→ 顺序冲量 + 摩擦 + 末轮位置校正 ---
    if (mechanics_data.size() >= 2) {
        // 5.1 用全体物体世界 AABB 建略大于一切的轴对齐根盒子（pad 防边界物体漏分桶）
        ktm::fvec3 root_min = mechanics_data[0].min_world;
        ktm::fvec3 root_max = mechanics_data[0].max_world;
        for (const auto& e : mechanics_data) {
            root_min.x = std::min(root_min.x, e.min_world.x);
            root_min.y = std::min(root_min.y, e.min_world.y);
            root_min.z = std::min(root_min.z, e.min_world.z);
            root_max.x = std::max(root_max.x, e.max_world.x);
            root_max.y = std::max(root_max.y, e.max_world.y);
            root_max.z = std::max(root_max.z, e.max_world.z);
        }
        const float pad = 0.01f; // 米级小膨胀；过小可能使 AABB 贴边物体跨层不稳
        root_min = make_fvec3(root_min.x - pad, root_min.y - pad, root_min.z - pad);
        root_max = make_fvec3(root_max.x + pad, root_max.y + pad, root_max.z + pad);

        OctreeNode octree_root;         // 栈上根；子节点在 vector 内持有
        octree_root.min_bounds = root_min;
        octree_root.max_bounds = root_max;

        // 5.2 每个 mechanics 插入同一棵树；相交叶子记下「可能与谁碰」的候选对
        for (const auto& e : mechanics_data) {
            octree_insert(octree_root, e.handle, e.min_world, e.max_world, 0);
        }

        // 5.3 深度优先扫叶子，拉出所有候选对；dedupe 避免 (a,b)/(b,a) 重复与同对多叶重复
        std::vector<std::pair<std::uintptr_t, std::uintptr_t>> collision_pairs;
        collision_pairs.reserve(mechanics_data.size() * 4);
        octree_collect_pairs(octree_root, collision_pairs);
        octree_dedupe_pairs(collision_pairs);

        CFW_LOG_DEBUG("Detected {} potential collision pairs", collision_pairs.size());

        // 5.4 对候选对做法向/切向冲量（半隐式 GS：多轮依次解每对约束近似同时满足）
        constexpr float eps = 1e-8f;                    // 分母稳定项，非物理
        constexpr float min_overlap = 0.001f;           // 小于此视为数值噪声/SAT 抖振，跳过
        constexpr float k_positional_slop = 0.004f;     // Baumgarte 式校正：小穿透只靠冲量，不修位姿
        constexpr float k_positional_percent = 0.35f;   // 仅末轮按穿透拆分平移，且只推一部分，防过冲
        constexpr int k_impulse_iterations = 5;         // 轮数↑ 堆叠更稳、成本↑；典型 3~8

        for (int impulse_iter = 0; impulse_iter < k_impulse_iterations; ++impulse_iter) {
        for (const auto& pair : collision_pairs) {        // 内层：单对接触解一次（顺序依赖）
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

            // 检测AABB重叠
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
                const float ov = (i == 0) ? overlap_x : (i == 1) ? overlap_y : overlap_z;
                const float ab = (i == 0) ? adx : (i == 1) ? ady : adz;
                if (ov > mtd_min + mtd_band) {
                    continue;
                }
                const int stack_pri = (i == 1) ? 0 : (i == 0) ? 1 : 2;
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

            const float mass_a = handle_to_mass[ha];
            const float mass_b = handle_to_mass[hb];
            const bool sleep_a = g_handle_to_sleeping[ha];   // 休眠体当「动不了」：不接收冲量速度增量
            const bool sleep_b = g_handle_to_sleeping[hb];
            const float inv_ma = sleep_a ? 0.f : 1.0f / mass_a; // Δv = (j/m)·n 中的 1/m
            const float inv_mb = sleep_b ? 0.f : 1.0f / mass_b;
            const float rest_a = handle_to_restitution[ha];     // 双方恢复系数各取组件；此处简单平均
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
            const ktm::fvec3 p_contact = vec3_mul(vec3_add(p_a, p_b), 0.5f); // 近似接触点：两支撑点中点
            const ktm::fvec3 r_a = vec3_sub(p_contact, a.obb_center);       // 质心/盒心到触点的臂
            const ktm::fvec3 r_b = vec3_sub(p_contact, b.obb_center);
#else
            const ktm::fvec3 p_a = aabb_support_world(a.center_world, a.half_extents, normal);
            const ktm::fvec3 p_b = aabb_support_world(b.center_world, b.half_extents,
                                                      make_fvec3(-normal.x, -normal.y, -normal.z));
            const ktm::fvec3 p_contact = vec3_mul(vec3_add(p_a, p_b), 0.5f); // AABB 模式下同样用中点
            const ktm::fvec3 r_a = vec3_sub(p_contact, a.center_world);      // 此处 center_world≈AABB 心
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

            const ktm::fvec3 raxn = ktm::cross(r_a, normal); // r×n，进入 ω 的有效惯量投影公式
            const ktm::fvec3 rbxn = ktm::cross(r_b, normal);
            // 标量 ang_n：世界系下 (I_w^{-1} (r×n))·(r×n)，即柔度矩阵 K 中法对角项
            const float ang_n_a = sleep_a ? 0.f
                : ktm::dot(raxn, world_inertia_inv_apply(a.rot_body_to_world, a.inertia_inv_body, raxn));
            const float ang_n_b = sleep_b ? 0.f
                : ktm::dot(rbxn, world_inertia_inv_apply(b.rot_body_to_world, b.inertia_inv_body, rbxn));
            const float denom_n = inv_ma + inv_mb + ang_n_a + ang_n_b + eps; // 1 / (有效质量)
            if (denom_n <= 1e-12f) {
                continue; // 近奇异（例如双臂共线且惯量项异常）
            }
            const float j = -(1.0f + rest_use) * v_n / denom_n; // 法向冲量标量；约定 J = j·n 作用于 B 的正向

            va.x += normal.x * j * inv_ma;
            va.y += normal.y * j * inv_ma;
            va.z += normal.z * j * inv_ma;
            vb.x -= normal.x * j * inv_mb;
            vb.y -= normal.y * j * inv_mb;
            vb.z -= normal.z * j * inv_mb;

            const ktm::fvec3 Jn = make_fvec3(normal.x * j, normal.y * j, normal.z * j); // 法向冲量向量
            if (!sleep_a) {
                const ktm::fvec3 dw =
                    world_inertia_inv_apply(a.rot_body_to_world, a.inertia_inv_body, ktm::cross(r_a, Jn)); // Δω = I^{-1}(r×J)
                wa.x += dw.x;
                wa.y += dw.y;
                wa.z += dw.z;
            }
            if (!sleep_b) {
                const ktm::fvec3 dw = world_inertia_inv_apply(
                    b.rot_body_to_world, b.inertia_inv_body, ktm::cross(r_b, make_fvec3(-Jn.x, -Jn.y, -Jn.z))); // B 受力为 -J
                wb.x += dw.x;
                wb.y += dw.y;
                wb.z += dw.z;
            }

            v_pa = velocity_at_point_world(va, wa, r_a);
            v_pb = velocity_at_point_world(vb, wb, r_b);
            v_rel = make_fvec3(v_pa.x - v_pb.x, v_pa.y - v_pb.y, v_pa.z - v_pb.z);
            const float v_n_rel = ktm::dot(v_rel, normal); // 法向冲量后的接近速度（可 <0，表示分离中）
            ktm::fvec3 v_t = make_fvec3(                  // v_rel 去掉法向分量 = 切向滑移速度
                v_rel.x - normal.x * v_n_rel,
                v_rel.y - normal.y * v_n_rel,
                v_rel.z - normal.z * v_n_rel);
            const float vt_len = ktm::length(v_t);
            if (vt_len > eps) {                               // 无切向速度则跳过摩擦
                const ktm::fvec3 tdir = make_fvec3(v_t.x / vt_len, v_t.y / vt_len, v_t.z / vt_len); // 滑移方向单位向量
                const float v_slip = ktm::dot(v_rel, tdir);   // 沿 tdir 的标量滑移速度
                const ktm::fvec3 raxt = ktm::cross(r_a, tdir);
                const ktm::fvec3 rbxt = ktm::cross(r_b, tdir);
                const float ang_t_a = sleep_a ? 0.f
                    : ktm::dot(raxt, world_inertia_inv_apply(a.rot_body_to_world, a.inertia_inv_body, raxt));
                const float ang_t_b = sleep_b ? 0.f
                    : ktm::dot(rbxt, world_inertia_inv_apply(b.rot_body_to_world, b.inertia_inv_body, rbxt));
                const float denom_t = inv_ma + inv_mb + ang_t_a + ang_t_b + eps;
                if (denom_t > 1e-12f) {
                    const float jt_free = -v_slip / denom_t; // 无摩擦上限时的切向冲量（完全粘滞）
                    const float jt_cap = friction_coeff * std::fabs(j);               // 库仑锥 |jt| ≤ μ|j|
                    const float jt = std::max(-jt_cap, std::min(jt_cap, jt_free));     // 钳位到摩擦锥内

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
                // 末轮：按穿透深度做一次软位置投影（非物理 LCP；只为减轻长期穿透）
                const float pen = std::max(0.f, penetration - k_positional_slop);
                if (pen > 0.f) {
                    const float inv_sum = inv_ma + inv_mb; // 按逆质量比例分摊平移
                    if (inv_sum > eps) {
                        const float corr_scale = k_positional_percent * pen / inv_sum; // 总位移幅度再乘 percent
                        const auto apply_corr = [&](std::uintptr_t transform_handle, float inv_eff, float sign) {
                            if (inv_eff <= eps) return; // 静/sleep 物体不移动
                            if (auto tx = transform_storage.acquire_write(transform_handle)) {
                                // A 侧 sign=-1 沿 -n 推，B 侧 +1 沿 +n 推，逐渐分开
                                tx->position.x += sign * normal.x * corr_scale * inv_eff;
                                tx->position.y += sign * normal.y * corr_scale * inv_eff;
                                tx->position.z += sign * normal.z * corr_scale * inv_eff;
                            }
                        };
                        apply_corr(a.transform_handle, inv_ma, -1.f);
                        apply_corr(b.transform_handle, inv_mb, +1.f);
                    }
                }

                g_handle_to_sleeping[ha] = false; // 发生过接触则唤醒（避免「睡着还叠压」）
                g_handle_to_sleeping[hb] = false;
                g_handle_to_sleep_timer[ha] = 0.0f;
                g_handle_to_sleep_timer[hb] = 0.0f;

            }

        }
        } // 内层：collision_pairs；外层：impulse_iter
    }

    // --- 阶段 6：半隐式位姿积分（用冲量后的 v,ω）+ 无穷地板 + 休眠累计 + 缓存淘汰 ---
    for (std::size_t i = 0; i < mechanics_data.size(); ++i) {
        const auto& data = mechanics_data[i];        // 与阶段 3 同一套 per-body 缓存
        std::uintptr_t h = data.handle;
        if (g_handle_to_sleeping[h])
            continue;                             // 休眠体不再推进变换

        auto tx_w = transform_storage.acquire_write(data.transform_handle);
        if (!tx_w) continue;

        // 速度 × dt 平移（显式欧拉；与阶段 3 预测一致）
        tx_w->position.x += g_handle_to_velocity[h].x * fixed_dt;
        tx_w->position.y += g_handle_to_velocity[h].y * fixed_dt;
        tx_w->position.z += g_handle_to_velocity[h].z * fixed_dt;

        { // 朝向：以四元数为真值源，欧拉仅用于与渲染/资产管线对齐
            auto q_it = g_handle_orientation_quat.find(h);
            if (q_it == g_handle_orientation_quat.end()) {
                q_it = g_handle_orientation_quat.emplace(h, quat_from_model_euler(tx_w->euler_rotation)).first;
            }
            integrate_orientation_quat(q_it->second, g_handle_to_angular_vel[h], fixed_dt); // q ← q ⊗ Δq(ω)
            sync_euler_from_orientation_quat(q_it->second, tx_w->euler_rotation);         // 写回 XYZ 欧拉（约定与引擎一致）
        }

        const float object_bottom_y =
            world_aabb_min_y(*tx_w, data.local_min, data.local_max); // 当前姿态下局部 AABB 的世界 min.y

        // 水平 floor_y：穿插时整体上抬，并做法向/切向「处方」（非完整接触流形）
        if (object_bottom_y < floor_y + floor_eps) {
            tx_w->position.y += (floor_y + floor_eps) - object_bottom_y; // 消穿（单轴，近似静接触）

            float y_vel = g_handle_to_velocity[h].y; // 向上为正
            if (y_vel < -low_vel_threshold) {
                g_handle_to_velocity[h].y = -y_vel * floor_restitution; // 下行且够快则反弹
            } else {
                if (std::abs(g_handle_to_velocity[h].y) < zero_vel_threshold) {
                    g_handle_to_velocity[h].y = 0.0f; // 粘地：贴住时竖直速度清零
                } else {
                    g_handle_to_velocity[h].y *= 0.15f; // 弱弹簧感衰减残余弹跳
                }

                g_handle_to_velocity[h].x *= 0.8f; // 水平滑动摩擦（与对体摩擦系数独立，属地板启发式）
                g_handle_to_velocity[h].z *= 0.8f;
                g_handle_to_angular_vel[h].x *= 0.7f; // 滚阻：略拖慢角速度防永转
                g_handle_to_angular_vel[h].y *= 0.7f;
                g_handle_to_angular_vel[h].z *= 0.7f;
            }

            g_handle_to_sleep_timer[h] = 0.0f; // 碰地视为仍在扰动，休眠累计清零
        }
    }

    for (std::uintptr_t h : mechanics_handles) {
        if (g_handle_to_sleeping[h]) continue;

        const auto& v = g_handle_to_velocity[h];
        const auto& av = g_handle_to_angular_vel[h];

        float v_sq = v.x * v.x + v.y * v.y + v.z * v.z;
        float av_sq = av.x * av.x + av.y * av.y + av.z * av.z;

        if (v_sq < sleep_threshold_sq && av_sq < sleep_threshold_sq) {
            g_handle_to_sleep_timer[h] += fixed_dt; // 低速窗口累加
            if (g_handle_to_sleep_timer[h] >= sleep_time_needed) {
                g_handle_to_sleeping[h] = true;
                g_handle_to_velocity[h] = make_fvec3(0.0f, 0.0f, 0.0f);
                g_handle_to_angular_vel[h] = make_fvec3(0.0f, 0.0f, 0.0f); // 冻结动力学状态
            }
        } else {
            g_handle_to_sleep_timer[h] = 0.0f; // 一有运动就打断休眠倒计时
        }
    }

    std::unordered_set<std::uintptr_t> alive_handles(mechanics_handles.begin(), mechanics_handles.end());
    auto clean_cache = [&](auto& cache) {
        for (auto it = cache.begin(); it != cache.end(); ) {
            if (!alive_handles.count(it->first)) {
                it = cache.erase(it); // 本帧未出现的 mechanics 句柄：删掉 stale 条目防 map 膨胀
            } else {
                ++it;
            }
        }
    };

    clean_cache(g_handle_to_velocity);
    clean_cache(g_handle_to_angular_vel);
    clean_cache(g_handle_orientation_quat);
    clean_cache(g_handle_to_sleeping);
    clean_cache(g_handle_to_sleep_timer);
    clean_cache(handle_to_mass);
    clean_cache(handle_to_damping);
    clean_cache(handle_to_restitution);
}

} // namespace Corona::Systems