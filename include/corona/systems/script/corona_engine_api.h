#pragma once

#include <array>
#include <filesystem>
#include <memory>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <functional>

namespace Corona {
class Model;

namespace API {
// ============================================================================
// UI 侧可设置当前默认显示 surface（例如 SDL 原生窗口句柄）。
// ============================================================================
void set_default_surface(void* surface);
[[nodiscard]] void* get_default_surface();

// ============================================================================
// Geometry: 作为所有组件的锚点，存储位置/旋转/缩放和模型数据
// ============================================================================
class Geometry {
   public:
    explicit Geometry(const std::string& model_path);
    ~Geometry();

    Geometry(const Geometry&) = delete;
    Geometry& operator=(const Geometry&) = delete;
    Geometry(Geometry&&) noexcept = default;
    Geometry& operator=(Geometry&&) noexcept = default;

    void set_position(const std::array<float, 3>& pos);
    void set_rotation(const std::array<float, 3>& euler);
    void set_scale(const std::array<float, 3>& size);

    [[nodiscard]] std::array<float, 3> get_position() const;
    [[nodiscard]] std::array<float, 3> get_rotation() const;
    [[nodiscard]] std::array<float, 3> get_scale() const;

    /// 获取模型 AABB，返回 {min_x, min_y, min_z, max_x, max_y, max_z}
    [[nodiscard]] std::array<float, 6> get_aabb() const;

   private:
    friend class Mechanics;
    friend class Optics;
    friend class Acoustics;
    friend class Kinematics;

   protected:
    [[nodiscard]] std::uintptr_t get_handle() const;
    [[nodiscard]] std::uintptr_t get_transform_handle() const;
    [[nodiscard]] std::uintptr_t get_model_resource_handle() const;

   private:
    std::uintptr_t handle_{};
    std::uintptr_t transform_handle_{};
    std::uintptr_t model_resource_handle_{};
};

// ============================================================================
// Mechanics: 物理/力学组件，依赖 Geometry
// ============================================================================
class Mechanics {
   public:
    explicit Mechanics(Geometry& geo);
    ~Mechanics();

    void set_mass(float mass);
    [[nodiscard]] float get_mass() const;
    void set_restitution(float restitution);
    [[nodiscard]] float get_restitution() const;
    void set_damping(float damping);
    [[nodiscard]] float get_damping() const;

    // 设置碰撞回调（参数为对方 actor 句柄、began(true=enter,false=exit)、法线、碰撞点）
    void set_collision_callback(std::function<void(std::uintptr_t, bool, const std::array<float, 3>&, const std::array<float, 3>&)> callback);

    // 设置移动回调
    void set_on_move_callback(std::function<void()> callback);
   private:
    friend class Actor;

    [[nodiscard]] std::uintptr_t get_handle() const;
    [[nodiscard]] Geometry* get_geometry() const;

    Geometry* geometry_;
    std::uintptr_t handle_{};
};

// ============================================================================
// Optics: 光学/渲染组件，依赖 Geometry
// ============================================================================
class Optics {
   public:
    explicit Optics(Geometry& geo);
    ~Optics();

    void set_metallic(float metallic);
    [[nodiscard]] float get_metallic() const;
    void set_roughness(float roughness);
    [[nodiscard]] float get_roughness() const;
    void set_subsurface(float subsurface);
    [[nodiscard]] float get_subsurface() const;
    void set_specular(float specular);
    [[nodiscard]] float get_specular() const;
    void set_specular_tint(float specularTint);
    [[nodiscard]] float get_specular_tint() const;
    void set_anisotropic(float anisotropic);
    [[nodiscard]] float get_anisotropic() const;
    void set_sheen(float sheen);
    [[nodiscard]] float get_sheen() const;
    void set_sheen_tint(float sheenTint);
    [[nodiscard]] float get_sheen_tint() const;
    void set_clearcoat(float clearcoat);
    [[nodiscard]] float get_clearcoat() const;
    void set_clearcoat_gloss(float clearcoatGloss);
    [[nodiscard]] float get_clearcoat_gloss() const;
    void set_visible(bool visible);
    [[nodiscard]] bool get_visible() const;
    void set_ambient(const std::array<float, 3>& ambient);
    [[nodiscard]] std::array<float, 3> get_ambient() const;
    void set_diffuse(const std::array<float, 3>& diffuse);
    [[nodiscard]] std::array<float, 3> get_diffuse() const;
    void set_specular_color(const std::array<float, 3>& specular);
    [[nodiscard]] std::array<float, 3> get_specular_color() const;
    void set_shininess(float shininess);
    [[nodiscard]] float get_shininess() const;

   private:
    friend class Actor;

    [[nodiscard]] std::uintptr_t get_handle() const;
    [[nodiscard]] Geometry* get_geometry() const;

    Geometry* geometry_;
    std::uintptr_t handle_{};
};

// ============================================================================
// Acoustics: 声学组件，依赖 Geometry
// ============================================================================
class Acoustics {
   public:
    explicit Acoustics(Geometry& geo);
    ~Acoustics();

    void set_volume(float volume);
    [[nodiscard]] float get_volume() const;

   private:
    friend class Actor;

    [[nodiscard]] std::uintptr_t get_handle() const;
    [[nodiscard]] Geometry* get_geometry() const;

    Geometry* geometry_;
    std::uintptr_t handle_{};
};

// ============================================================================
// Kinematics: 运动学组件，依赖 Geometry
// ============================================================================
class Kinematics {
   public:
    explicit Kinematics(Geometry& geo);
    ~Kinematics();

    void set_animation(std::uint32_t animation_index);
    void play_animation(float speed = 1.0f);
    void stop_animation();

    [[nodiscard]] std::uint32_t get_animation_index() const;
    [[nodiscard]] float get_current_time() const;

   private:
    friend class Actor;

    [[nodiscard]] std::uintptr_t get_handle() const;
    [[nodiscard]] Geometry* get_geometry() const;

    Geometry* geometry_;
    std::uintptr_t handle_{0};
};

// ============================================================================
// Actor: OOP 风格的实体类，支持多套组件和多个 Geometry
// ============================================================================
class Actor {
   public:
    Actor();
    ~Actor();

    struct Profile {
        Optics* optics{nullptr};
        Acoustics* acoustics{nullptr};
        Mechanics* mechanics{nullptr};
        Kinematics* kinematics{nullptr};
        Geometry* geometry{nullptr};
    };

    Profile* add_profile(const Profile& profile);
    void remove_profile(const Profile* profile);
    void set_active_profile(const Profile* profile);
    [[nodiscard]] Profile* get_active_profile();
    [[nodiscard]] std::size_t profile_count() const;
    
    [[nodiscard]] std::uintptr_t get_handle() const;

   private:
    friend class Scene;


    std::uintptr_t handle_{};
    std::unordered_map<std::uintptr_t, Profile> profiles_;
    std::uintptr_t active_profile_handle_{0};
    std::uintptr_t next_profile_handle_{1};
};

// ============================================================================
// ImageEffects: 图像效果类
// ============================================================================
class ImageEffects {
   public:
    ImageEffects();
    ~ImageEffects();

   private:
    std::uintptr_t handle_{};
};

// ============================================================================
// Camera: 相机类（合并了原 Viewport 的功能）
// ============================================================================
class Camera {
   public:
    Camera();
    Camera(const std::array<float, 3>& position, const std::array<float, 3>& forward,
           const std::array<float, 3>& world_up, float fov);
    ~Camera();

    void set(const std::array<float, 3>& position, const std::array<float, 3>& forward,
             const std::array<float, 3>& world_up, float fov);
    void set_surface(void* surface);
    void save_screenshot(const std::string& path) const;
    bool save_screenshot_sync(const std::string& path) const;

    void set_output_mode(const std::string& mode);
    [[nodiscard]] std::string get_output_mode() const;

    [[nodiscard]] std::array<float, 3> get_position() const;
    [[nodiscard]] std::array<float, 3> get_forward() const;
    [[nodiscard]] std::array<float, 3> get_world_up() const;
    [[nodiscard]] float get_fov() const;

    // ========== 原 Viewport 功能 ==========
    void set_image_effects(ImageEffects* effects);
    [[nodiscard]] ImageEffects* get_image_effects();
    [[nodiscard]] bool has_image_effects() const;
    void remove_image_effects();

    void set_size(int width, int height);
    void set_viewport_rect(int x, int y, int width, int height);
    void pick_actor_at_pixel(int x, int y) const;

   private:
    friend class Scene;

    [[nodiscard]] std::uintptr_t get_handle() const;

    std::uintptr_t handle_{};
    ImageEffects* image_effects_{nullptr};
    int width_{1920};
    int height_{1080};
};

// ============================================================================
// Environment: 环境类
// ============================================================================
class Environment {
   public:
    Environment();
    ~Environment();

    void set_sun_direction(const std::array<float, 3>& direction);
    void set_floor_grid(bool enabled) const;

    void set_gravity(const std::array<float, 3>& gravity);
    [[nodiscard]] std::array<float, 3> get_gravity() const;
    void set_floor_y(float y);
    [[nodiscard]] float get_floor_y() const;
    void set_floor_restitution(float restitution);
    [[nodiscard]] float get_floor_restitution() const;
    void set_fixed_dt(float dt);
    [[nodiscard]] float get_fixed_dt() const;

   private:
    friend class Scene;

    [[nodiscard]] std::uintptr_t get_handle() const;

    std::uintptr_t handle_{};
};

// ============================================================================
// Scene: 场景类（OOP 设计）
// ============================================================================
class Scene {
   public:
    Scene();
    ~Scene();

    // ========== Environment 管理 ==========
    void set_environment(Environment* env);
    [[nodiscard]] Environment* get_environment();
    [[nodiscard]] bool has_environment() const;
    void remove_environment();

    // ========== Actor 管理 ==========
    void add_actor(Actor* actor);
    void remove_actor(Actor* actor);
    void clear_actors();

    [[nodiscard]] std::size_t actor_count() const;
    [[nodiscard]] bool has_actor(const Actor* actor) const;

    // ========== Camera 管理 ==========
    void add_camera(Camera* camera);
    void remove_camera(Camera* camera);
    void clear_cameras();

    [[nodiscard]] std::size_t camera_count() const;
    [[nodiscard]] bool has_camera(const Camera* camera) const;

    /// 获取场景世界 AABB，返回 {min_x, min_y, min_z, max_x, max_y, max_z}
    [[nodiscard]] std::array<float, 6> get_aabb() const;

    // ========== 场景启用/禁用 ==========
    /// 启用或禁用场景（禁用后跳过渲染与物理模拟）
    void set_enabled(bool enabled);
    [[nodiscard]] bool is_enabled() const;

   private:
    std::uintptr_t handle_{};

    Environment* environment_{nullptr};
    std::vector<Actor*> actors_;
    std::vector<Camera*> cameras_;
    std::unordered_set<const Actor*> actors_index_;
    std::unordered_set<const Camera*> cameras_index_;
};

// ============================================================================
// Scene I/O utilities
// ============================================================================
Scene* read_scene(const std::filesystem::path& scene_path);
void write_scene(Scene* scene, const std::filesystem::path& scene_path);
}  // namespace API
}  // namespace Corona