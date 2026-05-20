#pragma once
#include <corona/kernel/utils/storage.h>
#include <ktm/ktm.h>

#include <array>
#include <cstdint>
#include <memory>
#include <vector>

#include "Horizon.h"

// Forward declarations

namespace Corona {

class Model;

struct MeshDevice {
    HardwareBuffer indexBuffer;
    HardwareBuffer vertexBuffer;

    // StorageBuffer mirrors for compute shader (VBuffer resolve) access.
    // Horizon BufferUsage is non-combinable, so we keep separate copies.
    HardwareBuffer indexStorageBuffer;
    HardwareBuffer vertexStorageBuffer;

    uint32_t materialIndex;
    HardwareImage textureBuffer;

    // 材质颜色 (RGBA)
    std::array<float, 4> materialColor{1.0f, 1.0f, 1.0f, 1.0f};
};

struct ModelTransform {
    ktm::fvec3 position;
    ktm::fvec3 euler_rotation;
    ktm::fvec3 scale;

    ModelTransform() {
        position.x = 0.0f;
        position.y = 0.0f;
        position.z = 0.0f;

        euler_rotation.x = 0.0f;
        euler_rotation.y = 0.0f;
        euler_rotation.z = 0.0f;

        scale.x = 1.0f;
        scale.y = 1.0f;
        scale.z = 1.0f;
    }

    [[nodiscard]] ktm::fmat4x4 compute_matrix() const {
        ktm::fquat qx = ktm::fquat::from_angle_x(euler_rotation.x);
        ktm::fquat qy = ktm::fquat::from_angle_y(euler_rotation.y);
        ktm::fquat qz = ktm::fquat::from_angle_z(euler_rotation.z);
        ktm::fquat rot_quat = qz * qy * qx;

        ktm::faffine3d affine;
        affine.translate(position).rotate(rot_quat).scale(scale);

        ktm::fmat4x4 result;
        affine >> result;
        return result;
    }
};

struct ModelResource {
    std::uint64_t model_id;
};

struct GeometryDevice {
    std::uintptr_t transform_handle{};
    std::uintptr_t model_resource_handle{};
    std::vector<MeshDevice> mesh_handles;
};

struct KinematicsDevice {
    std::uintptr_t geometry_handle{};
};

struct MechanicsDevice {
    std::uintptr_t geometry_handle{};
    ktm::fvec3 max_xyz;
    ktm::fvec3 min_xyz;

    // 物体级物理参数
    float mass{1.0f};
    float restitution{0.8f};
    float damping{0.99f};

    // 物理开关：false 时物理系统跳过该对象（不参与模拟，但仍保留数据）
    bool physics_enabled{true};

    // 力学碰撞检测开关：false 时完全禁用该物体的碰撞检测（物体不与其他物体或地面碰撞）
    bool bEnableCollision{true};

    // 碰撞回调函数
    std::function<void(std::uintptr_t, bool, const std::array<float, 3>&, const std::array<float, 3>&)> collision_callback;

    // 移动回调函数
    std::function<void()> on_move_callback;
};

struct AcousticsDevice {
    std::uintptr_t geometry_handle{};
    float volume{1.0f};
};

struct OpticsDevice {
    std::uintptr_t geometry_handle{};

    bool visible{true};  // 控制模型是否参与渲染

    // 光照影响开关：false 时物体不受灯光照射影响（仍参与渲染但不接收光照计算）
    bool bEnableLighting{true};

    // Disney Principled BRDF parameters
    float metallic{0.0f};
    float roughness{0.5f};
    float subsurface{0.0f};
    float specular{0.5f};
    float specularTint{0.0f};
    float anisotropic{0.0f};
    float sheen{0.0f};
    float sheenTint{0.5f};
    float clearcoat{0.0f};
    float clearcoatGloss{1.0f};

    // Legacy parameters (kept for backward compatibility)
    ktm::fvec3 ambient{0.2f, 0.2f, 0.2f};
    ktm::fvec3 diffuse{0.8f, 0.8f, 0.8f};
    ktm::fvec3 specular_color{1.0f, 1.0f, 1.0f};
    float shininess{32.0f};
};

struct ProfileDevice {
    std::uintptr_t optics_handle{};
    std::uintptr_t acoustics_handle{};
    std::uintptr_t mechanics_handle{};
    std::uintptr_t kinematics_handle{};
    std::uintptr_t geometry_handle{};
};

struct ActorDevice {
    std::vector<std::uintptr_t> profile_handles;
};

enum class CameraOutputMode : uint8_t {
    FinalColor,
    BaseColor,
    Normal,
    WorldPosition,
    ObjectID,
    VisibilityBuffer,
};

struct CameraDevice {
    void* surface{};

    ktm::fvec3 position;
    ktm::fvec3 forward;
    ktm::fvec3 world_up;
    float fov{60.0f};
    float aspect{16.0f / 9.0f};
    float near_plane{0.1f};
    float far_plane{100.0f};
    CameraOutputMode output_mode{CameraOutputMode::FinalColor};

    CameraDevice() {
        position.x = 0.0f;
        position.y = 0.0f;
        position.z = -5.0f;

        forward.x = 0.0f;
        forward.y = 0.0f;
        forward.z = 1.0f;

        world_up.x = 0.0f;
        world_up.y = 1.0f;
        world_up.z = 0.0f;
    }

    [[nodiscard]] ktm::fmat4x4 compute_view_matrix() const {
        ktm::fvec3 normalized_forward = ktm::normalize(forward);
        return ktm::look_to_lh(position, normalized_forward, world_up);
    }

    [[nodiscard]] ktm::fmat4x4 compute_projection_matrix() const {
        ktm::fmat4x4 proj = ktm::perspective_lh(ktm::radians(fov), aspect, near_plane, far_plane);
        // Vulkan NDC Y轴向下（与OpenGL相反），需要翻转Y分量
        proj[1][1] *= -1.0f;
        return proj;
    }

    [[nodiscard]] ktm::fmat4x4 compute_view_proj_matrix() const {
        return compute_projection_matrix() * compute_view_matrix();
    }
};

struct EnvironmentDevice {
    ktm::fvec3 sun_position;
    std::uint32_t floor_grid_enabled{1};

    // 统一光照参数（供 OpticsSystem lighting/sky/tonemap 共用）
    ktm::fvec3 sun_color{1.0f, 0.949f, 0.853f};  // ~5500K 日光色温
    float sun_intensity{10.0f};                  // 太阳直射辐照度
    float sky_intensity{20.0f};                  // 大气散射功率
    float exposure{1.0f};                        // 全局曝光

    // 物理场景参数
    ktm::fvec3 gravity{0.0f, -9.8f, 0.0f};
    float floor_y{0.0f};
    float floor_restitution{0.6f};
    float fixed_dt{1.0f / 60.0f};
};

struct SceneDevice {
    bool enabled{true};
    bool simulation_enabled{false};
    std::uintptr_t environment{};
    std::vector<std::uintptr_t> actor_handles;
    std::vector<std::uintptr_t> camera_handles;
    ktm::fvec3 min_world;
    ktm::fvec3 max_world;
    ktm::fvec3 center_world;
};

struct ImageDevice {
    HardwareImage image;
    HardwareExecutor executor;

    /// Written by DisplaySystem after compositing finishes reading the image.
    /// Producers wait on this before overwriting with new content to prevent GPU read/write races.
    HardwareExecutor consumed_executor;
};

class SharedDataHub {
   public:
    static SharedDataHub& instance();

    ~SharedDataHub() = default;

    SharedDataHub(const SharedDataHub&) = delete;
    SharedDataHub& operator=(const SharedDataHub&) = delete;
    SharedDataHub(SharedDataHub&&) = delete;
    SharedDataHub& operator=(SharedDataHub&&) = delete;

   private:
    SharedDataHub() = default;

   public:
    // 新的 Storage 类型定义，包含默认的容量和内存池参数
    using ModelResourceStorage = Kernel::Utils::Storage<ModelResource, 128, 2>;
    using ModelTransformStorage = Kernel::Utils::Storage<ModelTransform, 128, 2>;
    using GeometryStorage = Kernel::Utils::Storage<GeometryDevice, 128, 2>;
    using KinematicsStorage = Kernel::Utils::Storage<KinematicsDevice, 128, 2>;
    using MechanicsStorage = Kernel::Utils::Storage<MechanicsDevice, 128, 2>;
    using AcousticsStorage = Kernel::Utils::Storage<AcousticsDevice, 128, 2>;
    using OpticsStorage = Kernel::Utils::Storage<OpticsDevice, 128, 2>;
    using ProfileStorage = Kernel::Utils::Storage<ProfileDevice, 128, 2>;
    using ActorStorage = Kernel::Utils::Storage<ActorDevice, 128, 2>;
    using CameraStorage = Kernel::Utils::Storage<CameraDevice, 128, 2>;
    using EnvironmentStorage = Kernel::Utils::Storage<EnvironmentDevice, 128, 2>;
    using SceneStorage = Kernel::Utils::Storage<SceneDevice, 128, 2>;
    using ImageStorage = Kernel::Utils::Storage<ImageDevice, 128, 2>;

    ModelResourceStorage& model_resource_storage();
    const ModelResourceStorage& model_resource_storage() const;

    ModelTransformStorage& model_transform_storage();
    const ModelTransformStorage& model_transform_storage() const;

    GeometryStorage& geometry_storage();
    const GeometryStorage& geometry_storage() const;

    KinematicsStorage& kinematics_storage();
    const KinematicsStorage& kinematics_storage() const;

    MechanicsStorage& mechanics_storage();
    const MechanicsStorage& mechanics_storage() const;

    AcousticsStorage& acoustics_storage();
    const AcousticsStorage& acoustics_storage() const;

    OpticsStorage& optics_storage();
    const OpticsStorage& optics_storage() const;

    ProfileStorage& profile_storage();
    const ProfileStorage& profile_storage() const;

    ActorStorage& actor_storage();
    const ActorStorage& actor_storage() const;

    CameraStorage& camera_storage();
    const CameraStorage& camera_storage() const;

    EnvironmentStorage& environment_storage();
    const EnvironmentStorage& environment_storage() const;

    SceneStorage& scene_storage();
    const SceneStorage& scene_storage() const;

    ImageStorage& image_storage();
    const ImageStorage& image_storage() const;

   private:
    ModelResourceStorage model_resource_storage_;
    GeometryStorage geometry_storage_;
    ModelTransformStorage model_transform_storage_;
    KinematicsStorage kinematics_storage_;
    MechanicsStorage mechanics_storage_;
    OpticsStorage optics_storage_;
    AcousticsStorage acoustics_storage_;
    ProfileStorage profile_storage_;
    ActorStorage actor_storage_;
    EnvironmentStorage environment_storage_;
    CameraStorage camera_storage_;
    SceneStorage scene_storage_;
    ImageStorage image_storage_;
};

}  // namespace Corona
