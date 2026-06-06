#include <corona/kernel/core/callback_sink.h>
#include <corona/kernel/core/i_logger.h>
#include <corona/systems/script/corona_engine_api.h>
#include <corona/systems/script/engine_scripts.h>
#include <nanobind/nanobind.h>
#include <nanobind/stl/array.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <array>
#include <cstdint>
#include <memory>

#include <SDL3/SDL.h>

namespace nb = nanobind;
using namespace Corona::API;

namespace EngineScripts {

void BindAll(nanobind::module_& m) {
    // ============================================================================
    // Geometry: 作为所有组件的锚点，存储位置/旋转/缩放和模型数据
    // ============================================================================
    nb::class_<Geometry>(m, "Geometry")
        .def(nb::init<const std::string&>(), nb::arg("model_path"),
             "Create a Geometry from a model file path")
        .def("set_position", &Geometry::set_position, nb::arg("position"),
             "Set local position [x, y, z]")
        .def("set_rotation", &Geometry::set_rotation, nb::arg("euler"),
             "Set local rotation (Euler angles ZYX order) [pitch, yaw, roll]")
        .def("set_scale", &Geometry::set_scale, nb::arg("scale"),
             "Set local scale [x, y, z]")
        .def("get_position", &Geometry::get_position,
             "Get local position [x, y, z]")
        .def("get_rotation", &Geometry::get_rotation,
             "Get local rotation (Euler angles) [pitch, yaw, roll]")
        .def("get_scale", &Geometry::get_scale,
             "Get local scale [x, y, z]")
        .def("get_aabb", &Geometry::get_aabb,
             "Get model AABB [min_x, min_y, min_z, max_x, max_y, max_z]");

    // ============================================================================
    // Mechanics: 物理/力学组件
    // ============================================================================
    nb::class_<Mechanics>(m, "Mechanics")
        .def(nb::init<Geometry&>(), nb::arg("geometry"),
             "Create a Mechanics component attached to a Geometry")
        .def("set_mass", &Mechanics::set_mass, nb::arg("mass"),
             "Set object mass")
        .def("get_mass", &Mechanics::get_mass,
             "Get object mass")
        .def("set_restitution", &Mechanics::set_restitution, nb::arg("restitution"),
             "Set object restitution (bounciness)")
        .def("get_restitution", &Mechanics::get_restitution,
             "Get object restitution")
        .def("set_damping", &Mechanics::set_damping, nb::arg("damping"),
             "Set velocity damping factor")
        .def("get_damping", &Mechanics::get_damping,
             "Get velocity damping factor")
        .def("set_physics_enabled", &Mechanics::set_physics_enabled, nb::arg("enabled"),
             "Enable or disable physics simulation for this object")
        .def("get_physics_enabled", &Mechanics::get_physics_enabled,
             "Get whether physics simulation is enabled for this object")
        .def("set_collision_enabled", &Mechanics::set_collision_enabled, nb::arg("enabled"),
             "Enable or disable collision detection for this object")
        .def("get_collision_enabled", &Mechanics::get_collision_enabled,
             "Get whether collision detection is enabled for this object")
        .def("set_collision_callback",
             [](Mechanics& self, nb::object callback) {
                 using CallbackType = std::function<void(std::uintptr_t, bool, const std::array<float, 3>&, const std::array<float, 3>&)>;

                 if (callback.is_none()) {
                     self.set_collision_callback(CallbackType{});
                     return;
                 }

                auto func_ptr = std::shared_ptr<nb::object>(new nb::object(callback), [](nb::object* p) {
                    try {
                        nb::gil_scoped_acquire gil;
                        delete p;
                    } catch (...) {
                        delete p;
                    }
                });

                CallbackType cb = [func_ptr](std::uintptr_t other, bool began, const std::array<float, 3>& normal, const std::array<float, 3>& point) mutable {
                    nb::gil_scoped_acquire gil;
                    try {
                        (*func_ptr).attr("__call__")(other, began, normal, point);
                    }  catch (const std::exception &e) {
                        CFW_LOG_ERROR("[Bindings::collision_callback] std::exception when invoking Python callback: {}", e.what());
                    } catch (...) {
                        CFW_LOG_ERROR("[Bindings::collision_callback] Unknown exception when invoking Python callback");
                    }
                };

                 self.set_collision_callback(cb); },

             nb::arg("callback"), "Set collision callback. Callback receives (other_handle, normal, point) where normal and point are (x,y,z) tuples.")
        .def("set_on_move_callback", [](Mechanics& self, nb::object callback) {
                using CallbackType = std::function<void()>;
                 
                if (callback.is_none()) {
                    self.set_on_move_callback(CallbackType{});
                    return;
                }
                 
                auto func_ptr = std::shared_ptr<nb::object>(new nb::object(callback), [](nb::object* p) {
                    try {
                        nb::gil_scoped_acquire gil;
                        delete p;
                    } catch (...) {
                        delete p;
                    }
                });
                 
                CallbackType cb = [func_ptr]() mutable {
                    nb::gil_scoped_acquire gil;
                    try {
                        (*func_ptr).attr("__call__")();
                    } catch (const std::exception& e) {
                        CFW_LOG_ERROR("[Bindings::move_callback] std::exception when invoking Python callback: {}", e.what());
                    } catch (...) {
                        CFW_LOG_ERROR("[Bindings::move_callback] Unknown exception when invoking Python callback");
                    }
                };
                 
                self.set_on_move_callback(cb); }, nb::arg("callback"), "Set move callback for geometry.");

    // ============================================================================
    // Optics: 光学/渲染组件
    // ============================================================================
    nb::class_<Optics>(m, "Optics")
        .def(nb::init<Geometry&>(), nb::arg("geometry"),
             "Create an Optics component attached to a Geometry")
        .def("set_visible", &Optics::set_visible, nb::arg("visible"),
             "Set whether this model is rendered")
        .def("get_visible", &Optics::get_visible,
             "Get whether this model is rendered")
        .def("set_lighting_enabled", &Optics::set_lighting_enabled, nb::arg("enabled"),
             "Enable or disable lighting influence on this object")
        .def("get_lighting_enabled", &Optics::get_lighting_enabled,
             "Get whether lighting influence is enabled for this object")
        .def("set_metallic", &Optics::set_metallic, nb::arg("metallic"))
        .def("get_metallic", &Optics::get_metallic)
        .def("set_roughness", &Optics::set_roughness, nb::arg("roughness"))
        .def("get_roughness", &Optics::get_roughness)
        .def("set_subsurface", &Optics::set_subsurface, nb::arg("subsurface"))
        .def("get_subsurface", &Optics::get_subsurface)
        .def("set_specular", &Optics::set_specular, nb::arg("specular"))
        .def("get_specular", &Optics::get_specular)
        .def("set_specular_tint", &Optics::set_specular_tint, nb::arg("specular_tint"))
        .def("get_specular_tint", &Optics::get_specular_tint)
        .def("set_anisotropic", &Optics::set_anisotropic, nb::arg("anisotropic"))
        .def("get_anisotropic", &Optics::get_anisotropic)
        .def("set_sheen", &Optics::set_sheen, nb::arg("sheen"))
        .def("get_sheen", &Optics::get_sheen)
        .def("set_sheen_tint", &Optics::set_sheen_tint, nb::arg("sheen_tint"))
        .def("get_sheen_tint", &Optics::get_sheen_tint)
        .def("set_clearcoat", &Optics::set_clearcoat, nb::arg("clearcoat"))
        .def("get_clearcoat", &Optics::get_clearcoat)
        .def("set_clearcoat_gloss", &Optics::set_clearcoat_gloss, nb::arg("clearcoat_gloss"))
        .def("get_clearcoat_gloss", &Optics::get_clearcoat_gloss)
        .def("set_ambient", &Optics::set_ambient, nb::arg("ambient"))
        .def("get_ambient", &Optics::get_ambient)
        .def("set_diffuse", &Optics::set_diffuse, nb::arg("diffuse"))
        .def("get_diffuse", &Optics::get_diffuse)
        .def("set_specular_color", &Optics::set_specular_color, nb::arg("specular_color"))
        .def("get_specular_color", &Optics::get_specular_color)
        .def("set_shininess", &Optics::set_shininess, nb::arg("shininess"))
        .def("get_shininess", &Optics::get_shininess);

    // ============================================================================
    // Acoustics: 声学组件
    // ============================================================================
    nb::class_<Acoustics>(m, "Acoustics")
        .def(nb::init<Geometry&>(), nb::arg("geometry"),
             "Create an Acoustics component attached to a Geometry")
        .def("set_volume", &Acoustics::set_volume, nb::arg("volume"),
             "Set audio volume")
        .def("get_volume", &Acoustics::get_volume,
             "Get audio volume")
        .def("set_audio_enabled", &Acoustics::set_audio_enabled, nb::arg("enabled"),
             "Enable or disable audio for this object")
        .def("get_audio_enabled", &Acoustics::get_audio_enabled,
             "Get whether audio is enabled for this object");

    // ============================================================================
    // Actor: OOP 风格的实体类，支持多套组件配置（Profile）
    // ============================================================================
    nb::class_<Actor::Profile>(m, "ActorProfile")
        .def(nb::init<>())
        .def_rw("optics", &Actor::Profile::optics, "Optics component")
        .def_rw("acoustics", &Actor::Profile::acoustics, "Acoustics component")
        .def_rw("mechanics", &Actor::Profile::mechanics, "Mechanics component")
        .def_rw("geometry", &Actor::Profile::geometry, "Geometry anchor");

    nb::class_<Actor>(m, "Actor")
        .def(nb::init<>(), "Create an empty Actor")
        .def("add_profile", &Actor::add_profile, nb::arg("profile"),
             "Add a component profile to this actor. Returns pointer to the stored profile.",
             nb::rv_policy::reference_internal)
        .def("remove_profile", &Actor::remove_profile, nb::arg("profile"),
             "Remove a component profile from this actor")
        .def("set_active_profile", &Actor::set_active_profile, nb::arg("profile"),
             "Set the active profile for this actor")
        .def("get_active_profile", &Actor::get_active_profile,
             "Get the currently active profile",
             nb::rv_policy::reference_internal)
        .def("profile_count", &Actor::profile_count,
             "Get number of profiles in this actor")
        .def("get_handle", &Actor::get_handle, "Get the underlying handle of this actor");

    // ============================================================================
    // Camera: 相机类（合并了原 Viewport 功能）
    // ============================================================================
    nb::class_<Camera>(m, "Camera")
        .def(nb::init<>(), "Create a default Camera")
        .def(nb::init<const std::array<float, 3>&, const std::array<float, 3>&,
                      const std::array<float, 3>&, float>(),
             nb::arg("position"), nb::arg("forward"), nb::arg("world_up"), nb::arg("fov"),
             "Create a Camera with specified parameters")
        .def("set", &Camera::set,
             nb::arg("position"), nb::arg("forward"), nb::arg("world_up"), nb::arg("fov"),
             "Set all camera parameters at once")
        .def("get_handle", &Camera::get_handle, "Get camera handle")
        .def("save_screenshot", &Camera::save_screenshot, nb::arg("path"),
             "Save a screenshot from this camera's perspective to file (async)")
        .def("save_screenshot_sync", &Camera::save_screenshot_sync, nb::arg("path"),
             "Save a screenshot and block until it completes. Returns True on success.")
        .def("set_output_mode", &Camera::set_output_mode, nb::arg("mode"),
             "Set camera output mode. mode: 'final_color', 'base_color', 'normal', 'position', 'object_id'")
        .def("get_output_mode", &Camera::get_output_mode,
             "Get current camera output mode as string")
        .def("set_surface", [](Camera& self, std::uintptr_t surface) { self.set_surface(reinterpret_cast<void*>(surface)); }, nb::arg("surface"), "Set render surface (pass window ID as integer)")
        .def("get_surface", [](const Camera& self) -> std::uintptr_t { return reinterpret_cast<std::uintptr_t>(self.get_surface()); }, "Get render surface handle as integer (0 if none)")
        .def("get_position", &Camera::get_position, "Get camera position [x, y, z]")
        .def("get_forward", &Camera::get_forward, "Get camera forward direction [x, y, z]")
        .def("get_world_up", &Camera::get_world_up, "Get camera world up vector [x, y, z]")
        .def("get_fov", &Camera::get_fov, "Get field of view in degrees")
        .def("set_image_effects", &Camera::set_image_effects, nb::arg("effects"), "Set image effects for this camera")
        .def("get_image_effects", &Camera::get_image_effects, "Get image effects attached to this camera", nb::rv_policy::reference)
        .def("has_image_effects", &Camera::has_image_effects, "Check if camera has image effects")
        .def("remove_image_effects", &Camera::remove_image_effects, "Remove image effects from this camera")
        .def("set_size", &Camera::set_size, nb::arg("width"), nb::arg("height"), "Set camera render dimensions")
        .def("set_viewport_rect", &Camera::set_viewport_rect, nb::arg("x"), nb::arg("y"), nb::arg("width"), nb::arg("height"), "Set viewport rectangle")
        .def("pick_actor_at_pixel", &Camera::pick_actor_at_pixel, nb::arg("x"), nb::arg("y"), "Pick actor at pixel coordinates");

    // ============================================================================
    // ImageEffects: 图像效果类
    // ============================================================================
    nb::class_<ImageEffects>(m, "ImageEffects")
        .def(nb::init<>(), "Create an ImageEffects instance");

    // ============================================================================
    // Environment: 环境类
    // ============================================================================
    nb::class_<Environment>(m, "Environment")
        .def(nb::init<>(), "Create an Environment")
        .def("set_sun_direction", &Environment::set_sun_direction, nb::arg("direction"),
             "Set sun light direction [x, y, z]")
        .def("get_sun_direction", &Environment::get_sun_direction,
             "Get sun light direction [x, y, z]")
        .def("set_floor_grid", &Environment::set_floor_grid, nb::arg("enabled"),
             "Enable or disable floor grid rendering")
        .def("get_floor_grid", &Environment::get_floor_grid,
             "Get floor grid rendering state")
        .def("set_gravity", &Environment::set_gravity, nb::arg("gravity"),
             "Set gravity vector [x, y, z]")
        .def("get_gravity", &Environment::get_gravity,
             "Get gravity vector [x, y, z]")
        .def("set_floor_y", &Environment::set_floor_y, nb::arg("y"),
             "Set floor plane Y height")
        .def("get_floor_y", &Environment::get_floor_y,
             "Get floor plane Y height")
        .def("set_floor_restitution", &Environment::set_floor_restitution, nb::arg("restitution"),
             "Set floor restitution (bounciness)")
        .def("get_floor_restitution", &Environment::get_floor_restitution,
             "Get floor restitution")
        .def("set_fixed_dt", &Environment::set_fixed_dt, nb::arg("dt"),
             "Set physics fixed time step")
        .def("get_fixed_dt", &Environment::get_fixed_dt,
             "Get physics fixed time step");

    // ============================================================================
    // Scene: 场景类
    // ============================================================================
    nb::class_<Scene>(m, "Scene")
        .def(nb::init<>(), "Create an empty Scene")
        // Environment management
        .def("set_environment", &Scene::set_environment, nb::arg("environment"),
             "Set the scene environment")
        .def("get_environment", &Scene::get_environment,
             "Get the scene environment",
             nb::rv_policy::reference)
        .def("has_environment", &Scene::has_environment,
             "Check if scene has an environment")
        .def("remove_environment", &Scene::remove_environment,
             "Remove environment from scene")
        // Actor management
        .def("add_actor", &Scene::add_actor, nb::arg("actor"),
             "Add an actor to the scene")
        .def("remove_actor", &Scene::remove_actor, nb::arg("actor"),
             "Remove an actor from the scene")
        .def("clear_actors", &Scene::clear_actors,
             "Remove all actors from the scene")
        .def("actor_count", &Scene::actor_count,
             "Get number of actors in the scene")
        .def("has_actor", &Scene::has_actor, nb::arg("actor"),
             "Check if actor is in the scene")
        // Camera management
        .def("add_camera", &Scene::add_camera, nb::arg("camera"),
             "Add a camera to the scene")
        .def("remove_camera", &Scene::remove_camera, nb::arg("camera"),
             "Remove a camera from the scene")
        .def("clear_cameras", &Scene::clear_cameras,
             "Remove all cameras from the scene")
        .def("camera_count", &Scene::camera_count,
             "Get number of cameras in the scene")
        .def("has_camera", &Scene::has_camera, nb::arg("camera"),
             "Check if camera is in the scene")
        .def("get_aabb", &Scene::get_aabb,
             "Get scene world AABB as [min_x, min_y, min_z, max_x, max_y, max_z]")
        // Scene enable/disable
        .def("set_enabled", &Scene::set_enabled, nb::arg("enabled"),
             "Enable or disable the scene (disabled scenes skip rendering and physics)")
        .def("is_enabled", &Scene::is_enabled,
             "Return True if the scene is currently enabled")
        // Scene simulation control
        .def("set_simulation_enabled", &Scene::set_simulation_enabled, nb::arg("enabled"),
             "Enable or disable physics simulation for this scene (does not affect rendering)")
        .def("is_simulation_enabled", &Scene::is_simulation_enabled,
             "Return True if physics simulation is enabled for this scene");

    // ============================================================================
    // Scene I/O utilities
    // ============================================================================
    // m.def("read_scene", &read_scene, nb::arg("scene_path"),
    //       "Load a scene from file",
    //       nb::rv_policy::take_ownership);
    // m.def("write_scene", &write_scene, nb::arg("scene"), nb::arg("scene_path"),
    //       "Save a scene to file");

    // ============================================================================
    // Logger: 日志前端转发接口
    // ============================================================================
    nb::class_<Corona::Kernel::LogEntry>(m, "LogEntry")
        .def_ro("level", &Corona::Kernel::LogEntry::level,
                "Log level string: TRACE/DEBUG/INFO/WARNING/ERROR/CRITICAL")
        .def_ro("message", &Corona::Kernel::LogEntry::message,
                "Formatted log message")
        .def_ro("timestamp", &Corona::Kernel::LogEntry::timestamp,
                "Timestamp in nanoseconds since epoch");

    m.def("drain_logs", []() -> std::vector<Corona::Kernel::LogEntry> { return Corona::Kernel::CoronaLogger::drain_logs(); }, "Drain all pending log entries from the engine log queue");

    m.def("send_log", [](const std::string& level, const std::string& message) {
              if (level == "TRACE") {
                  PY_LOG_TRACE("{}", message.c_str());
              } else if (level == "DEBUG") {
                  PY_LOG_DEBUG("{}", message.c_str());
              } else if (level == "INFO") {
                  PY_LOG_INFO("{}", message.c_str());
              } else if (level == "WARNING") {
                  PY_LOG_WARNING("{}", message.c_str());
              } else if (level == "ERROR") {
                  PY_LOG_ERROR("{}", message.c_str());
              } else if (level == "CRITICAL") {
                  PY_LOG_CRITICAL("{}", message.c_str());
              } else {
                  PY_LOG_INFO("{}", message.c_str());  // Default to INFO
              } }, nb::arg("level"), nb::arg("message"), "Send a log message to the engine logger with specified level");

    // ============================================================================
    // Render backend control (Native vs Vision)
    // ============================================================================
    m.def("is_vision_available", &is_vision_available,
          "Return True if the engine was compiled with Vision (CORONA_ENABLE_VISION) support");
    m.def("set_render_backend", &set_render_backend, nb::arg("mode"),
          "Request a render backend switch. mode: 'native' or 'vision'. Only effective when Vision is available.");
    m.def("get_render_backend", &get_render_backend,
          "Get the currently requested render backend as 'native' or 'vision'");

    // ============================================================================
    // Engine lifecycle
    // ============================================================================
    m.def("request_engine_exit", []() {
        SDL_Event quit_event;
        SDL_zero(quit_event);
        quit_event.type = SDL_EVENT_QUIT;
        SDL_PushEvent(&quit_event);
    }, "Request graceful engine shutdown. "
       "Pushes an SDL_QUIT event, same as clicking the window close button.");

}

}  // namespace EngineScripts
