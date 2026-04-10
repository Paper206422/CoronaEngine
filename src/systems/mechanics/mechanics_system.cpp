#include <corona/events/engine_events.h>
#include <corona/events/mechanics_system_events.h>
#include <corona/kernel/core/i_logger.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/systems/mechanics/mechanics_system.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <future>
#include <memory>
#include <set>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

#include "corona/shared_data_hub.h"
#include "ktm/ktm.h"
// Note: do not depend on nanobind in the mechanics system. Callbacks provided
// from the scripting layer are expected to manage GIL acquisition themselves.

namespace {

struct PairHash {
    std::size_t operator()(const std::pair<std::uintptr_t, std::uintptr_t>& p) const noexcept {
        // combine hashes
        std::size_t h1 = std::hash<std::uintptr_t>{}(p.first);
        std::size_t h2 = std::hash<std::uintptr_t>{}(p.second);
        return h1 ^ (h2 << 1);
    }
};

// Persistent set of active collision pairs from previous frame
static std::unordered_set<std::pair<std::uintptr_t, std::uintptr_t>, PairHash> g_prev_active_collisions;
// 速度存储的全局变量
static std::unordered_map<std::uintptr_t, ktm::fvec3> g_handle_to_velocity;

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

// ========== 新增：异步回调执行相关 ==========
// 存储异步任务的future，用于追踪（可选，用于等待所有任务完成）
static std::vector<std::future<void>> g_pending_callbacks;
// 互斥锁保护回调队列
static std::mutex g_callback_mutex;
// 是否在shutdown时等待所有回调完成
static std::atomic<bool> g_shutdown_requested{false};
// ========================================

constexpr ktm::fvec3 make_fvec3(float x, float y, float z) {
    ktm::fvec3 result;
    result.x = x;
    result.y = y;
    result.z = z;
    return result;
}

/*
 八叉树节点中的物体数据结构
 存储物体句柄和AABB包围盒
 */
struct OctreeEntry {
    std::uintptr_t handle;  // 物体唯一标识句柄
    ktm::fvec3 min_bounds;  // AABB包围盒最小边界
    ktm::fvec3 max_bounds;  // AABB包围盒最大边界
};

/*
 八叉树节点结构
 八叉树是节点包含8个子节点
 */
struct OctreeNode {
    ktm::fvec3 min_bounds;                                // 当前节点的AABB最小边界
    ktm::fvec3 max_bounds;                                // 当前节点的AABB最大边界
    std::vector<OctreeEntry> entries;                     // 叶子节点存储的物体列表
    std::unique_ptr<std::array<OctreeNode, 8>> children;  // 子节点（8个，非叶子节点才有）
};

// 八叉树常量
constexpr int kOctreeMaxDepth = 6;           // 八叉树最大深度（防止过深）
constexpr int kOctreeMaxObjectsPerLeaf = 4;  // 叶子节点最大物体数（超过分裂）

/*
 检测两个AABB包围盒是否重叠
 a_min A物体AABB最小边界
 a_max A物体AABB最大边界
 b_min B物体AABB最小边界
 b_max B物体AABB最大边界
*/
inline bool aabb_overlap(const ktm::fvec3& a_min, const ktm::fvec3& a_max,
                         const ktm::fvec3& b_min, const ktm::fvec3& b_max) {
    // 三个轴都有重叠才视为重叠
    return (a_min.x <= b_max.x && a_max.x >= b_min.x) &&
           (a_min.y <= b_max.y && a_max.y >= b_min.y) &&
           (a_min.z <= b_max.z && a_max.z >= b_min.z);
}

/*
  初始化八叉树节点的8个子节点
 */
void octree_init_children(OctreeNode& node) {
    // 创建8个子节点的空间
    node.children = std::make_unique<std::array<OctreeNode, 8>>();
    auto& children = *node.children;

    // 计算父节点的坐标（作为子节点的分割点）
    const ktm::fvec3 center = make_fvec3(
        (node.min_bounds.x + node.max_bounds.x) * 0.5f,
        (node.min_bounds.y + node.max_bounds.y) * 0.5f,
        (node.min_bounds.z + node.max_bounds.z) * 0.5f);
    const auto& min = node.min_bounds;
    const auto& max = node.max_bounds;

    // 初始化8个子节点的AABB边界
    children[0].min_bounds = min;
    children[0].max_bounds = center;

    children[1].min_bounds = make_fvec3(center.x, min.y, min.z);
    children[1].max_bounds = make_fvec3(max.x, center.y, center.z);

    children[2].min_bounds = make_fvec3(min.x, center.y, min.z);
    children[2].max_bounds = make_fvec3(center.x, max.y, center.z);

    children[3].min_bounds = make_fvec3(center.x, center.y, min.z);
    children[3].max_bounds = make_fvec3(max.x, max.y, center.z);

    children[4].min_bounds = make_fvec3(min.x, min.y, center.z);
    children[4].max_bounds = make_fvec3(center.x, center.y, max.z);

    children[5].min_bounds = make_fvec3(center.x, min.y, center.z);
    children[5].max_bounds = make_fvec3(max.x, center.y, max.z);

    children[6].min_bounds = make_fvec3(min.x, center.y, center.z);
    children[6].max_bounds = make_fvec3(center.x, max.y, max.z);

    children[7].min_bounds = center;
    children[7].max_bounds = max;
}

void octree_insert(OctreeNode& node, std::uintptr_t handle,
                   const ktm::fvec3& obj_min, const ktm::fvec3& obj_max, int depth) {
    // 物体不在当前节点范围内，return
    if (!aabb_overlap(obj_min, obj_max, node.min_bounds, node.max_bounds)) {
        return;
    }

    // 判断节点是否为叶子节点
    const bool is_leaf = (node.children == nullptr);

    if (is_leaf) {
        // 检查分裂：深度未到最大值和物体数超过阈值
        const bool should_split =
            depth < kOctreeMaxDepth &&
            static_cast<int>(node.entries.size()) >= kOctreeMaxObjectsPerLeaf;

        // 不分裂直接将物体加入当前叶子节点
        if (!should_split) {
            node.entries.push_back({handle, obj_min, obj_max});
            return;
        }
        octree_init_children(node);

        // 将当前节点的物体重新分配到子节点中
        for (const OctreeEntry& e : node.entries) {
            for (int i = 0; i < 8; ++i) {
                octree_insert((*node.children)[i], e.handle, e.min_bounds, e.max_bounds, depth + 1);
            }
        }
        node.entries.clear();  // 清空转移到子节点

        // 将新物体插入到子节点中
        for (int i = 0; i < 8; ++i) {
            octree_insert((*node.children)[i], handle, obj_min, obj_max, depth + 1);
        }
        return;
    }

    // 非叶子节点计算中心并判断物体属于哪些子节点
    const ktm::fvec3 center = make_fvec3(
        (node.min_bounds.x + node.max_bounds.x) * 0.5f,
        (node.min_bounds.y + node.max_bounds.y) * 0.5f,
        (node.min_bounds.z + node.max_bounds.z) * 0.5f);

    const ktm::fvec3& min_bounds = node.min_bounds;
    const ktm::fvec3& max_bounds = node.max_bounds;

    // 检测物体与8个子节点的重叠情况
    const bool overlap[8] = {
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
        aabb_overlap(obj_min, obj_max, center, max_bounds)};

    // 将物体插入到所有重叠的子节点中
    for (int i = 0; i < 8; ++i) {
        if (overlap[i]) {
            octree_insert((*node.children)[i], handle, obj_min, obj_max, depth + 1);
        }
    }
}

void octree_collect_pairs(const OctreeNode& node,
                          std::vector<std::pair<std::uintptr_t, std::uintptr_t>>& out) {
    // 非叶子节点：递归遍历子节点
    if (node.children) {
        for (int i = 0; i < 8; ++i) {
            octree_collect_pairs((*node.children)[i], out);
        }
        return;
    }

    // 叶子节点：生成所有物体对（i<j，避免重复）
    for (std::size_t i = 0; i < node.entries.size(); ++i) {
        for (std::size_t j = i + 1; j < node.entries.size(); ++j) {
            std::uintptr_t a = node.entries[i].handle;
            std::uintptr_t b = node.entries[j].handle;
            if (a > b) std::swap(a, b);  // 保证a<=b，统一碰撞对顺序
            out.emplace_back(a, b);
        }
    }
}

void octree_dedupe_pairs(std::vector<std::pair<std::uintptr_t, std::uintptr_t>>& pairs) {
    if (pairs.empty()) return;
    // 排序后去重
    std::sort(pairs.begin(), pairs.end());
    pairs.erase(std::unique(pairs.begin(), pairs.end()), pairs.end());
}

// 用于精准地板碰撞
struct MechanicsWorldAABB {
    std::uintptr_t handle;            // 物体句柄
    std::uintptr_t transform_handle;  // 物体变换句柄（用于更新位置）
    ktm::fvec3 min_world;             // 世界AABB最小边界
    ktm::fvec3 max_world;             // 世界AABB最大边界
    ktm::fvec3 center_world;          // 世界AABB中心
    float half_height;                // 物体Y轴半高（用于地板碰撞）
};

}  // namespace

namespace Corona::Systems {

bool MechanicsSystem::initialize(Kernel::ISystemContext* ctx) {
    CFW_LOG_NOTICE("MechanicsSystem: Initializing...");
    g_shutdown_requested = false;
    return true;
}

void MechanicsSystem::update() {
    update_physics();  // 每帧调用物理更新
}

void MechanicsSystem::shutdown() {
    CFW_LOG_NOTICE("MechanicsSystem: Shutting down...");

    // 标记关闭请求，不再接受新的回调任务
    g_shutdown_requested = true;

    // 等待所有正在执行的异步回调完成
    {
        std::lock_guard<std::mutex> lock(g_callback_mutex);
        if (!g_pending_callbacks.empty()) {
            CFW_LOG_NOTICE("MechanicsSystem: Waiting for {} pending callbacks to complete...", g_pending_callbacks.size());
            for (auto& fut : g_pending_callbacks) {
                if (fut.valid()) {
                    // 等待回调完成，最多等待5秒避免死锁
                    auto status = fut.wait_for(std::chrono::seconds(5));
                    if (status == std::future_status::timeout) {
                        CFW_LOG_WARNING("MechanicsSystem: Callback timeout, forcing shutdown...");
                    }
                }
            }
            g_pending_callbacks.clear();
        }
    }

    g_prev_active_collisions.clear();
    g_handle_to_velocity.clear();
    g_handle_to_last_move_callback_time.clear();
    g_global_simulation_time = 0.0f;
    g_handle_to_last_move_callback_pos.clear();

    CFW_LOG_NOTICE("MechanicsSystem: Shutdown complete.");
}

// 物理系统核心每一帧都会执行
void MechanicsSystem::update_physics() {
    // 如果正在关闭，不再处理新的物理更新
    if (g_shutdown_requested) {
        return;
    }

    // 如果还会有点抖 那就调大一些
    const float floor_eps = 0.01f;             // 地板碰撞容差
    const float low_vel_threshold = 0.05f;     // 低速衰减阈值
    const float min_valid_dt = 1.0f / 120.0f;  // 最小有效时间步
    const float max_valid_dt = 1.0f / 30.0f;   // 最大有效时间步
    const float zero_vel_threshold = 0.01f;    // 速度归零阈值

    // 物理属性缓存
    std::unordered_map<std::uintptr_t, float> handle_to_mass;
    std::unordered_map<std::uintptr_t, float> handle_to_damping;
    std::unordered_map<std::uintptr_t, float> handle_to_restitution;
    std::unordered_map<std::uintptr_t, std::uintptr_t> mech_to_actor;

    // 获取全局存储
    auto& mechanics_storage = SharedDataHub::instance().mechanics_storage();
    auto& geometry_storage = SharedDataHub::instance().geometry_storage();
    auto& transform_storage = SharedDataHub::instance().model_transform_storage();
    auto& scene_storage = SharedDataHub::instance().scene_storage();
    auto& actor_storage = SharedDataHub::instance().actor_storage();
    auto& profile_storage = SharedDataHub::instance().profile_storage();
    auto& environment_storage = SharedDataHub::instance().environment_storage();

    // 物理参数初始
    float fixed_dt = 1.0f / 60.0f;                       // 默认固定时间步
    ktm::fvec3 gravity = make_fvec3(0.0f, -9.8f, 0.0f);  // 默认重力加速度
    float floor_restitution = 0.6f;                      // 默认地板弹性
    float floor_y = 0.0f;                                // 默认地板高度

    std::vector<std::uintptr_t> mechanics_handles;
    mechanics_handles.reserve(64);
    std::vector<std::uintptr_t> scene_handles;
    scene_handles.reserve(4);

    for (const auto& scene : scene_storage) {
        if (!scene.enabled)
            continue;

        scene_handles.push_back(reinterpret_cast<std::uintptr_t>(&scene));

        // 读取场景环境参数
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
                        if (profile->mechanics_handle != 0) {
                            std::uintptr_t h = profile->mechanics_handle;
                            mechanics_handles.push_back(h);
                            mech_to_actor[h] = actor_handle;

                            // 初始化速度（首次出现的物体）
                            if (g_handle_to_velocity.find(h) == g_handle_to_velocity.end()) {
                                g_handle_to_velocity[h] = make_fvec3(0.0f, 0.0f, 0.0f);
                            }

                            // 读取物理属性（带默认值）
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

    // 去重物理物体句柄，避免重复计算
    std::sort(mechanics_handles.begin(), mechanics_handles.end());
    mechanics_handles.erase(std::unique(mechanics_handles.begin(), mechanics_handles.end()), mechanics_handles.end());

    // 无物理物体时直接返回
    if (mechanics_handles.empty()) {
        CFW_LOG_TRACE("MechanicsSystem: No physics objects found.");
        return;
    }
    CFW_LOG_TRACE("MechanicsSystem: {} physics objects found.", mechanics_handles.size());

    g_global_simulation_time += fixed_dt;

    // 只计算速度
    for (std::uintptr_t h : mechanics_handles) {
        float damping = handle_to_damping[h];

        // 重力直接作用于速度（去掉 / mass）
        g_handle_to_velocity[h].x += gravity.x * fixed_dt;
        g_handle_to_velocity[h].y += gravity.y * fixed_dt;
        g_handle_to_velocity[h].z += gravity.z * fixed_dt;

        // 阻尼（空气阻力）
        g_handle_to_velocity[h].x *= damping;
        g_handle_to_velocity[h].y *= damping;
        g_handle_to_velocity[h].z *= damping;
    }

    // 计算物体世界AABB（
    std::vector<MechanicsWorldAABB> mechanics_data;
    mechanics_data.reserve(mechanics_handles.size());
    std::unordered_map<std::uintptr_t, std::size_t> handle_to_index;

    for (std::uintptr_t h : mechanics_handles) {
        auto m_acc = mechanics_storage.acquire_read(h);
        if (!m_acc) continue;
        const auto& m = *m_acc;

        auto geom_acc = geometry_storage.acquire_read(m.geometry_handle);
        if (!geom_acc) continue;

        auto tx_acc = transform_storage.acquire_read(geom_acc->transform_handle);
        if (!tx_acc) continue;
        const auto& t = *tx_acc;

        // 计算局部中心点和半尺寸
        ktm::fvec3 c_local = make_fvec3(
            (m.min_xyz.x + m.max_xyz.x) * 0.5f,
            (m.min_xyz.y + m.max_xyz.y) * 0.5f,
            (m.min_xyz.z + m.max_xyz.z) * 0.5f);
        ktm::fvec3 e_local = make_fvec3(
            (m.max_xyz.x - m.min_xyz.x) * 0.5f,
            (m.max_xyz.y - m.min_xyz.y) * 0.5f,
            (m.max_xyz.z - m.min_xyz.z) * 0.5f);

        // 计算世界空间AABB（新增半高计算）
        MechanicsWorldAABB entry;
        entry.handle = h;
        entry.transform_handle = geom_acc->transform_handle;
        entry.center_world = make_fvec3(
            c_local.x + t.position.x,
            c_local.y + t.position.y,
            c_local.z + t.position.z);
        entry.half_height = std::abs(e_local.y * t.scale.y);
        ktm::fvec3 e_world = make_fvec3(
            std::abs(e_local.x * t.scale.x),
            entry.half_height,
            std::abs(e_local.z * t.scale.z));
        entry.min_world = make_fvec3(
            entry.center_world.x - e_world.x,
            entry.center_world.y - e_world.y,
            entry.center_world.z - e_world.z);
        entry.max_world = make_fvec3(
            entry.center_world.x + e_world.x,
            entry.center_world.y + e_world.y,
            entry.center_world.z + e_world.z);

        handle_to_index[h] = mechanics_data.size();
        mechanics_data.push_back(entry);
    }

    // 更新场景包围盒
    if (!mechanics_data.empty()) {
        ktm::fvec3 scene_min = mechanics_data[0].min_world;
        ktm::fvec3 scene_max = mechanics_data[0].max_world;

        for (const auto& e : mechanics_data) {
            scene_min.x = std::min(scene_min.x, e.min_world.x);
            scene_min.y = std::min(scene_min.y, e.min_world.y);
            scene_min.z = std::min(scene_min.z, e.min_world.z);
            scene_max.x = std::max(scene_max.x, e.max_world.x);
            scene_max.y = std::max(scene_max.y, e.max_world.y);
            scene_max.z = std::max(scene_max.z, e.max_world.z);
        }

        ktm::fvec3 scene_center = make_fvec3(
            (scene_min.x + scene_max.x) * 0.5f,
            (scene_min.y + scene_max.y) * 0.5f,
            (scene_min.z + scene_max.z) * 0.5f);

        for (auto sh : scene_handles) {
            if (auto s_w = scene_storage.acquire_write(sh)) {
                s_w->min_world = scene_min;
                s_w->max_world = scene_max;
                s_w->center_world = scene_center;
            }
        }
    }

    // 碰撞检测与速度修正
    if (mechanics_data.size() >= 2) {
        // 构建八叉树
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
        // 扩展根节点边界，包含地板
        root_min.y = std::min(root_min.y, floor_y - floor_eps);
        const float pad = 0.01f;
        root_min = make_fvec3(root_min.x - pad, root_min.y - pad, root_min.z - pad);
        root_max = make_fvec3(root_max.x + pad, root_max.y + pad, root_max.z + pad);

        OctreeNode octree_root;
        octree_root.min_bounds = root_min;
        octree_root.max_bounds = root_max;

        // 插入所有物体到八叉树
        for (const auto& e : mechanics_data) {
            octree_insert(octree_root, e.handle, e.min_world, e.max_world, 0);
        }

        // 收集并去重碰撞对
        std::vector<std::pair<std::uintptr_t, std::uintptr_t>> collision_pairs;
        collision_pairs.reserve(mechanics_data.size() * 4);
        octree_collect_pairs(octree_root, collision_pairs);
        octree_dedupe_pairs(collision_pairs);

        // 处理碰撞对（只修正速度）
        std::unordered_set<std::pair<std::uintptr_t, std::uintptr_t>, PairHash> curr_active_collisions;
        constexpr float eps = 1e-6f;           // 极小值，防止除零
        constexpr float min_overlap = 0.001f;  // 最小重叠深度，忽略微小重叠

        for (const auto& pair : collision_pairs) {
            std::uintptr_t ha = pair.first;
            std::uintptr_t hb = pair.second;

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

            // 计算碰撞法线（从A指向B）
            ktm::fvec3 diff = make_fvec3(
                b.center_world.x - a.center_world.x,
                b.center_world.y - a.center_world.y,
                b.center_world.z - a.center_world.z);
            float diff_len = std::sqrt(diff.x * diff.x + diff.y * diff.y + diff.z * diff.z);
            if (diff_len < eps) {
                continue;  // 避免零长度法线
            }
            ktm::fvec3 normal = make_fvec3(
                diff.x / diff_len,
                diff.y / diff_len,
                diff.z / diff_len);

            // 计算重叠深度（只处理有效重叠）
            float overlap_x = (a.max_world.x - a.min_world.x) / 2 + (b.max_world.x - b.min_world.x) / 2 - std::abs(diff.x);
            float overlap_y = (a.max_world.y - a.min_world.y) / 2 + (b.max_world.y - b.min_world.y) / 2 - std::abs(diff.y);
            float overlap_z = (a.max_world.z - a.min_world.z) / 2 + (b.max_world.z - b.min_world.z) / 2 - std::abs(diff.z);
            float min_ov = std::min({overlap_x, overlap_y, overlap_z});
            if (min_ov < min_overlap) {
                continue;
            }

            // 获取物体质量和弹性
            float mass_a = handle_to_mass[ha];
            float mass_b = handle_to_mass[hb];
            float rest_a = handle_to_restitution[ha];
            float rest_b = handle_to_restitution[hb];
            float rest = (rest_a + rest_b) * 0.5f;  // 平均弹性

            // 计算物体在法线上的速度分量
            float v_a = g_handle_to_velocity[ha].x * normal.x + g_handle_to_velocity[ha].y * normal.y + g_handle_to_velocity[ha].z * normal.z;
            float v_b = g_handle_to_velocity[hb].x * normal.x + g_handle_to_velocity[hb].y * normal.y + g_handle_to_velocity[hb].z * normal.z;

            // 计算碰撞冲量（弹性碰撞公式）
            float denominator = (1.0f / mass_a + 1.0f / mass_b) + 1e-8f;  // 加极小值防除零
            float j = (-(1.0f + rest) * (v_a - v_b)) / denominator;

            // 只更新速度
            g_handle_to_velocity[ha].x += normal.x * j / mass_a;
            g_handle_to_velocity[ha].y += normal.y * j / mass_a;
            g_handle_to_velocity[ha].z += normal.z * j / mass_a;

            g_handle_to_velocity[hb].x -= normal.x * j / mass_b;
            g_handle_to_velocity[hb].y -= normal.y * j / mass_b;
            g_handle_to_velocity[hb].z -= normal.z * j / mass_b;

            // 记录活跃碰撞对（
            auto actor_a = mech_to_actor.count(ha) ? mech_to_actor[ha] : ha;
            auto actor_b = mech_to_actor.count(hb) ? mech_to_actor[hb] : hb;
            auto sorted_pair = (actor_a < actor_b) ? std::make_pair(actor_a, actor_b) : std::make_pair(actor_b, actor_a);
            curr_active_collisions.insert(sorted_pair);

            // ==================== 碰撞回调 ================================
            {
                ktm::fvec3 point;
                point.x = (a.center_world.x + b.center_world.x) * 0.5f;
                point.y = (a.center_world.y + b.center_world.y) * 0.5f;
                point.z = (a.center_world.z + b.center_world.z) * 0.5f;

                std::function<void(std::uintptr_t, bool, const std::array<float, 3>&, const std::array<float, 3>&)> cb_a;
                std::function<void(std::uintptr_t, bool, const std::array<float, 3>&, const std::array<float, 3>&)> cb_b;

                {
                    auto mech_a_acc = mechanics_storage.acquire_read(ha);
                    if (mech_a_acc && mech_a_acc->collision_callback) {
                        cb_a = mech_a_acc->collision_callback;  // copy under read lock
                    }
                }

                {
                    auto mech_b_acc = mechanics_storage.acquire_read(hb);
                    if (mech_b_acc && mech_b_acc->collision_callback) {
                        cb_b = mech_b_acc->collision_callback;  // copy under read lock
                    }
                }

                std::array<float, 3> normal_arr = {normal.x, normal.y, normal.z};
                std::array<float, 3> point_arr = {point.x, point.y, point.z};

                // Determine if this pair was newly started this frame
                bool was_active = (g_prev_active_collisions.find(sorted_pair) != g_prev_active_collisions.end());

                // Only notify on collision start (was not active previously). Sustained collisions are ignored.
                if (!was_active) {
                    if (cb_a) {
                        try {
                            // cb_a is callback for object A; pass other actor handle (B) and began=true
                            cb_a(actor_b, true, normal_arr, point_arr);
                        } catch (...) {
                            CFW_LOG_ERROR("MechanicsSystem: Exception occurred in collision callback for actor {}.", actor_a);
                        }
                    }

                    if (cb_b) {
                        std::array<float, 3> reverse_normal_arr = {-normal.x, -normal.y, -normal.z};
                        try {
                            cb_b(actor_a, true, reverse_normal_arr, point_arr);
                        } catch (...) {
                            CFW_LOG_ERROR("MechanicsSystem: Exception occurred in collision callback for actor {}.", actor_b);
                        }
                    }
                }
            }
            // =====================================================
        }

        // 更新上一帧碰撞对
        g_prev_active_collisions.swap(curr_active_collisions);
    }

    // 统一更新位置
    for (std::size_t i = 0; i < mechanics_data.size(); ++i) {
        const auto& data = mechanics_data[i];
        std::uintptr_t h = data.handle;

        auto tx_w = transform_storage.acquire_write(data.transform_handle);
        if (!tx_w) continue;

        tx_w->position.x += g_handle_to_velocity[h].x * fixed_dt;
        tx_w->position.y += g_handle_to_velocity[h].y * fixed_dt;
        tx_w->position.z += g_handle_to_velocity[h].z * fixed_dt;

        // 精准地板碰撞检测（基于物体底部高度）
        float object_bottom_y = tx_w->position.y - data.half_height;  // 物体实际底部Y坐标
        if (object_bottom_y < floor_y + floor_eps) {
            // 修正位置：避免穿透地板
            tx_w->position.y = floor_y + data.half_height + floor_eps;

            // 处理反弹（仅当向下速度足够大时）
            float y_vel = g_handle_to_velocity[h].y;  // 把速度提取为临时变量
            if (y_vel < -low_vel_threshold) {
                g_handle_to_velocity[h].y = -y_vel * floor_restitution;
            } else {
                // 低速时直接归零，彻底消除抖动
                if (std::abs(g_handle_to_velocity[h].y) < zero_vel_threshold) {
                    g_handle_to_velocity[h].y = 0.0f;
                } else {
                    // 逐步衰减到零
                    g_handle_to_velocity[h].y *= 0.1f;
                }
            }
        }

        // ========== 异步执行移动回调 ==========
        {
            auto mech_acc = mechanics_storage.acquire_read(h);
            if (mech_acc && mech_acc->on_move_callback) {
                std::function<void()> cb_move = mech_acc->on_move_callback;

                if (cb_move) {
                    // 1. 时间检查
                    auto it_time = g_handle_to_last_move_callback_time.find(h);
                    float last_time = (it_time != g_handle_to_last_move_callback_time.end()) ? it_time->second : -kMoveCallbackMinInterval;
                    bool time_elapsed = (g_global_simulation_time - last_time >= kMoveCallbackMinInterval);

                    // 2. 位移检查
                    auto it_pos = g_handle_to_last_move_callback_pos.find(h);
                    ktm::fvec3 last_pos = (it_pos != g_handle_to_last_move_callback_pos.end()) ? it_pos->second : make_fvec3(1e9f, 1e9f, 1e9f);

                    // 计算欧几里得距离的平方
                    float dx = tx_w->position.x - last_pos.x;
                    float dy = tx_w->position.y - last_pos.y;
                    float dz = tx_w->position.z - last_pos.z;
                    float dist_sq = dx * dx + dy * dy + dz * dz;
                    bool moved_enough = (dist_sq >= kMoveCallbackMinDistance * kMoveCallbackMinDistance);

                    // 3. 同时满足时间间隔和位移阈值才触发
                    if (time_elapsed && moved_enough && !g_shutdown_requested) {
                        // 更新时间记录（在主线程中更新，避免并发问题）
                        g_handle_to_last_move_callback_time[h] = g_global_simulation_time;
                        g_handle_to_last_move_callback_pos[h] = tx_w->position;

                        // 捕获回调函数和句柄，异步执行
                        // 使用 std::async 启动异步任务
                        auto future = std::async(std::launch::async, [cb_move, h]() {
                            try {
                                cb_move();
                            } catch (const std::exception& e) {
                                CFW_LOG_ERROR("MechanicsSystem: Exception in async on_move callback for actor {}: {}", h, e.what());
                            } catch (...) {
                                CFW_LOG_ERROR("MechanicsSystem: Unknown exception in async on_move callback for actor {}.", h);
                            }
                        });

                        // 存储future以便shutdown时等待
                        std::lock_guard<std::mutex> lock(g_callback_mutex);
                        g_pending_callbacks.push_back(std::move(future));

                        // 定期清理已完成的future，避免无限增长
                        g_pending_callbacks.erase(
                            std::remove_if(g_pending_callbacks.begin(), g_pending_callbacks.end(),
                                           [](std::future<void>& f) {
                                               return !f.valid() ||
                                                      f.wait_for(std::chrono::seconds(0)) == std::future_status::ready;
                                           }),
                            g_pending_callbacks.end());
                    }
                }
            }
        }
        // =============================================================
    }

    // 清理无效句柄的缓存
    std::unordered_set<std::uintptr_t> alive_handles(mechanics_handles.begin(), mechanics_handles.end());

    auto clean_cache = [&](auto& cache) {
        for (auto it = cache.begin(); it != cache.end();) {
            if (!alive_handles.count(it->first)) {
                it = cache.erase(it);
            } else {
                ++it;
            }
        }
    };

    clean_cache(g_handle_to_velocity);
    clean_cache(handle_to_mass);
    clean_cache(handle_to_damping);
    clean_cache(handle_to_restitution);
    clean_cache(g_handle_to_last_move_callback_time);
    clean_cache(g_handle_to_last_move_callback_pos);
}

}  // namespace Corona::Systems