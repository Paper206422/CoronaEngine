# -*- coding: utf-8 -*-
"""
CoronaEngine Python Fallback（OOP 版）
- 与 C++ 绑定导出的 API 形态对齐（顶层类：Geometry/Mechanics/Optics/Acoustics/Kinematics/ActorProfile/Actor/Camera/ImageEffects/Environment/Scene）
"""
from __future__ import annotations
from typing import List, Optional
import warnings

# 一次性警告：仅在原生模块不可用时才会导入本模块
warnings.warn("[CoronaEngine][Fallback] 使用 Python fallback（未找到原生 CoronaEngine 模块），功能受限，仅用于开发/占位。",
              RuntimeWarning, stacklevel=2)


# ================================
# Geometry
# ================================
class Geometry:
    def __init__(self, model_path: str):
        print(f"[Fallback][Geometry.__init__] model_path={model_path}")
        self._model_path = model_path
        self._pos = [0.0, 0.0, 0.0]
        self._rot = [0.0, 0.0, 0.0]  # Euler ZYX
        self._scl = [1.0, 1.0, 1.0]

    def set_position(self, pos: List[float]):
        print(f"[Fallback][Geometry.set_position] pos={pos}")
        self._pos = list(pos)

    def set_rotation(self, euler: List[float]):
        print(f"[Fallback][Geometry.set_rotation] euler={euler}")
        self._rot = list(euler)

    def set_scale(self, scl: List[float]):
        print(f"[Fallback][Geometry.set_scale] scl={scl}")
        self._scl = list(scl)

    def get_position(self) -> List[float]:
        print("[Fallback][Geometry.get_position]")
        return list(self._pos)

    def get_rotation(self) -> List[float]:
        print("[Fallback][Geometry.get_rotation]")
        return list(self._rot)

    def get_scale(self) -> List[float]:
        print("[Fallback][Geometry.get_scale]")
        return list(self._scl)

    def get_aabb(self) -> List[float]:
        print("[Fallback][Geometry.get_aabb]")
        return [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


# ================================
# Components
# ================================
class Mechanics:
    def __init__(self, geo: Geometry):
        print(f"[Fallback][Mechanics.__init__] geo={geo}")
        self._geo = geo
        self._mass = 1.0
        self._restitution = 0.8
        self._damping = 0.99
        self._physics_enabled = True

    def set_mass(self, v): self._mass = v
    def get_mass(self): return self._mass
    def set_restitution(self, v): self._restitution = v
    def get_restitution(self): return self._restitution
    def set_damping(self, v): self._damping = v
    def get_damping(self): return self._damping
    def set_physics_enabled(self, v): self._physics_enabled = v
    def get_physics_enabled(self): return self._physics_enabled
    def set_collision_enabled(self, v): self._collision_enabled = v
    def get_collision_enabled(self): return getattr(self, '_collision_enabled', True)
    def set_collision_callback(self, cb): pass
    def set_on_move_callback(self, cb): pass


class Optics:
    def __init__(self, geo: Geometry):
        print(f"[Fallback][Optics.__init__] geo={geo}")
        self._geo = geo
        self._metallic = 0.0
        self._roughness = 0.5
        self._subsurface = 0.0
        self._specular = 0.5
        self._specular_tint = 0.0
        self._anisotropic = 0.0
        self._sheen = 0.0
        self._sheen_tint = 0.5
        self._clearcoat = 0.0
        self._clearcoat_gloss = 1.0
        self._ambient = [0.2, 0.2, 0.2]
        self._diffuse = [0.8, 0.8, 0.8]
        self._specular_color = [1.0, 1.0, 1.0]
        self._shininess = 32.0

    def set_metallic(self, v): self._metallic = v
    def get_metallic(self): return self._metallic
    def set_roughness(self, v): self._roughness = v
    def get_roughness(self): return self._roughness
    def set_subsurface(self, v): self._subsurface = v
    def get_subsurface(self): return self._subsurface
    def set_specular(self, v): self._specular = v
    def get_specular(self): return self._specular
    def set_specular_tint(self, v): self._specular_tint = v
    def get_specular_tint(self): return self._specular_tint
    def set_anisotropic(self, v): self._anisotropic = v
    def get_anisotropic(self): return self._anisotropic
    def set_sheen(self, v): self._sheen = v
    def get_sheen(self): return self._sheen
    def set_sheen_tint(self, v): self._sheen_tint = v
    def get_sheen_tint(self): return self._sheen_tint
    def set_clearcoat(self, v): self._clearcoat = v
    def get_clearcoat(self): return self._clearcoat
    def set_clearcoat_gloss(self, v): self._clearcoat_gloss = v
    def get_clearcoat_gloss(self): return self._clearcoat_gloss
    def set_ambient(self, v): self._ambient = list(v)
    def get_ambient(self): return self._ambient
    def set_diffuse(self, v): self._diffuse = list(v)
    def get_diffuse(self): return self._diffuse
    def set_specular_color(self, v): self._specular_color = list(v)
    def get_specular_color(self): return self._specular_color
    def set_shininess(self, v): self._shininess = v
    def get_shininess(self): return self._shininess


class Acoustics:
    def __init__(self, geo: Geometry):
        print(f"[Fallback][Acoustics.__init__] geo={geo}")
        self._geo = geo
        self._volume = 1.0

    def set_volume(self, volume: float):
        print(f"[Fallback][Acoustics.set_volume] volume={volume}")
        self._volume = float(volume)

    def get_volume(self) -> float:
        print("[Fallback][Acoustics.get_volume]")
        return float(self._volume)


class Kinematics:
    def __init__(self, geo: Geometry):
        print(f"[Fallback][Kinematics.__init__] geo={geo}")
        self._geo = geo
        self._anim_index = 0
        self._time = 0.0
        self._playing = False
        self._speed = 1.0

    def set_animation(self, index: int):
        print(f"[Fallback][Kinematics.set_animation] index={index}")
        self._anim_index = int(index)
        self._time = 0.0

    def play_animation(self, speed: float = 1.0):
        print(f"[Fallback][Kinematics.play_animation] speed={speed}")
        self._playing = True
        self._speed = float(speed)

    def stop_animation(self):
        print("[Fallback][Kinematics.stop_animation]")
        self._playing = False

    def get_animation_index(self) -> int:
        print("[Fallback][Kinematics.get_animation_index]")
        return int(self._anim_index)

    def get_current_time(self) -> float:
        print("[Fallback][Kinematics.get_current_time]")
        return float(self._time)


# ================================
# Actor / Profile
# ================================
class ActorProfile:
    def __init__(self):
        print("[Fallback][ActorProfile.__init__]")
        self.optics: Optional[Optics] = None
        self.acoustics: Optional[Acoustics] = None
        self.mechanics: Optional[Mechanics] = None
        self.kinematics: Optional[Kinematics] = None
        self.geometry: Optional[Geometry] = None


class Actor:
    def __init__(self, path: str = ""):
        print(f"[Fallback][Actor.__init__] path={path}")
        # 兼容旧构造签名（path），但不再使用
        self._profiles: List[ActorProfile] = []
        self._active: Optional[ActorProfile] = None

    def add_profile(self, profile: ActorProfile) -> Optional[ActorProfile]:
        print(f"[Fallback][Actor.add_profile] profile={profile}")
        # 一致性校验：组件如存在必须共享同一几何体
        geo = profile.geometry
        if geo is None:
            print("[Fallback][Actor.add_profile] profile.geometry 不能为空")
            return None
        for comp in (profile.optics, profile.mechanics, profile.acoustics, profile.kinematics):
            if comp is not None and getattr(comp, "_geo", None) is not geo:
                print("[Fallback][Actor.add_profile] 组件与 profile.geometry 不一致，拒绝添加")
                return None
        self._profiles.append(profile)
        if self._active is None:
            self._active = profile
        return profile

    def remove_profile(self, profile: ActorProfile):
        print(f"[Fallback][Actor.remove_profile] profile={profile}")
        if profile in self._profiles:
            if self._active is profile:
                self._active = self._profiles[0] if len(self._profiles) > 1 else None
            self._profiles.remove(profile)

    def set_active_profile(self, profile: ActorProfile):
        print(f"[Fallback][Actor.set_active_profile] profile={profile}")
        if profile in self._profiles:
            self._active = profile
        else:
            print("[Fallback][Actor.set_active_profile] 指定的 profile 不属于该 Actor")

    def get_active_profile(self) -> Optional[ActorProfile]:
        print("[Fallback][Actor.get_active_profile]")
        return self._active

    def profile_count(self) -> int:
        print("[Fallback][Actor.profile_count]")
        return len(self._profiles)


# ================================
# Camera / ImageEffects
# ================================
class Camera:
    def __init__(self, position=None, forward=None, world_up=None, fov=None):
        print(f"[Fallback][Camera.__init__] position={position}, forward={forward}, world_up={world_up}, fov={fov}")
        self._position = list(position or [0.0, 0.0, -5.0])
        self._forward = list(forward or [0.0, 0.0, 1.0])
        self._world_up = list(world_up or [0.0, 1.0, 0.0])
        self._fov = float(fov) if fov is not None else 60.0
        self._surface = None
        self._effects = None
        self._w = 1920
        self._h = 1080

    def set(self, position, forward, world_up, fov):
        print(f"[Fallback][Camera.set] position={position}, forward={forward}, world_up={world_up}, fov={fov}")
        self._position = list(position)
        self._forward = list(forward)
        self._world_up = list(world_up)
        self._fov = float(fov)

    def set_surface(self, surface):
        print(f"[Fallback][Camera.set_surface] surface={surface}")
        self._surface = surface

    def get_surface(self):
        print("[Fallback][Camera.get_surface]")
        return self._surface or 0

    def get_position(self):
        print("[Fallback][Camera.get_position]")
        return list(self._position)

    def get_forward(self):
        print("[Fallback][Camera.get_forward]")
        return list(self._forward)

    def get_world_up(self):
        print("[Fallback][Camera.get_world_up]")
        return list(self._world_up)

    def get_fov(self):
        print("[Fallback][Camera.get_fov]")
        return float(self._fov)

    def save_screenshot(self, path: str):
        print(f"[Fallback][Camera.save_screenshot] path={path}")

    def set_output_mode(self, mode: str):
        print(f"[Fallback][Camera.set_output_mode] mode={mode}")
        self._output_mode = mode

    def get_output_mode(self) -> str:
        print("[Fallback][Camera.get_output_mode]")
        return getattr(self, '_output_mode', 'final_color')

    def set_image_effects(self, effects):
        print(f"[Fallback][Camera.set_image_effects] effects={effects}")
        self._effects = effects

    def get_image_effects(self):
        print("[Fallback][Camera.get_image_effects]")
        return self._effects

    def has_image_effects(self) -> bool:
        print("[Fallback][Camera.has_image_effects]")
        return self._effects is not None

    def remove_image_effects(self):
        print("[Fallback][Camera.remove_image_effects]")
        self._effects = None

    def set_size(self, width: int, height: int):
        print(f"[Fallback][Camera.set_size] width={width}, height={height}")
        self._w, self._h = int(width), int(height)

    def set_viewport_rect(self, x: int, y: int, width: int, height: int):
        print(f"[Fallback][Camera.set_viewport_rect] x={x}, y={y}, width={width}, height={height}")

    def pick_actor_at_pixel(self, x: int, y: int):
        print(f"[Fallback][Camera.pick_actor_at_pixel] x={x}, y={y}")
        return (0, 0)


class ImageEffects:
    def __init__(self):
        print("[Fallback][ImageEffects.__init__]")


# ================================
# Environment / Scene
# ================================
class Environment:
    def __init__(self):
        print("[Fallback][Environment.__init__]")
        self._sun_dir = [0.0, -1.0, 0.0]
        self._floor_grid = False
        self._gravity = [0.0, -9.8, 0.0]
        self._floor_y = 0.0
        self._floor_restitution = 0.6
        self._fixed_dt = 1.0 / 60.0

    def set_sun_direction(self, direction: List[float]):
        print(f"[Fallback][Environment.set_sun_direction] direction={direction}")
        self._sun_dir = list(direction)

    def set_floor_grid(self, enabled: bool):
        print(f"[Fallback][Environment.set_floor_grid] enabled={enabled}")
        self._floor_grid = bool(enabled)

    def set_gravity(self, gravity: List[float]):
        print(f"[Fallback][Environment.set_gravity] gravity={gravity}")
        self._gravity = list(gravity)

    def get_gravity(self) -> List[float]:
        return list(self._gravity)

    def set_floor_y(self, y: float):
        print(f"[Fallback][Environment.set_floor_y] y={y}")
        self._floor_y = float(y)

    def get_floor_y(self) -> float:
        return self._floor_y

    def set_floor_restitution(self, restitution: float):
        print(f"[Fallback][Environment.set_floor_restitution] restitution={restitution}")
        self._floor_restitution = float(restitution)

    def get_floor_restitution(self) -> float:
        return self._floor_restitution

    def set_fixed_dt(self, dt: float):
        print(f"[Fallback][Environment.set_fixed_dt] dt={dt}")
        self._fixed_dt = float(dt)

    def get_fixed_dt(self) -> float:
        return self._fixed_dt


class Scene:
    def __init__(self, light_field: bool = False):
        print(f"[Fallback][Scene.__init__] light_field={light_field}")
        self._env: Optional[Environment] = None
        self._actors: List[Actor] = []
        self._cameras: List[Camera] = []
        self._light_field = bool(light_field)

    # Environment
    def set_environment(self, env: Optional[Environment]):
        print(f"[Fallback][Scene.set_environment] env={env}")
        self._env = env

    def get_environment(self) -> Optional[Environment]:
        print("[Fallback][Scene.get_environment]")
        return self._env

    def has_environment(self) -> bool:
        print("[Fallback][Scene.has_environment]")
        return self._env is not None

    def remove_environment(self):
        print("[Fallback][Scene.remove_environment]")
        self._env = None

    # Actor
    def add_actor(self, actor: Actor):
        print(f"[Fallback][Scene.add_actor] actor={actor}")
        if actor not in self._actors:
            self._actors.append(actor)

    def remove_actor(self, actor: Actor):
        print(f"[Fallback][Scene.remove_actor] actor={actor}")
        if actor in self._actors:
            self._actors.remove(actor)

    def clear_actors(self):
        print("[Fallback][Scene.clear_actors]")
        self._actors.clear()

    def actor_count(self) -> int:
        print("[Fallback][Scene.actor_count]")
        return len(self._actors)

    def has_actor(self, actor: Actor) -> bool:
        print(f"[Fallback][Scene.has_actor] actor={actor}")
        return actor in self._actors

    # Camera (scene-level)
    def add_camera(self, cam: Camera):
        print(f"[Fallback][Scene.add_camera] camera={cam}")
        if cam not in self._cameras:
            self._cameras.append(cam)

    def remove_camera(self, cam: Camera):
        print(f"[Fallback][Scene.remove_camera] camera={cam}")
        if cam in self._cameras:
            self._cameras.remove(cam)

    def clear_cameras(self):
        print("[Fallback][Scene.clear_cameras]")
        self._cameras.clear()

    def camera_count(self) -> int:
        print("[Fallback][Scene.camera_count]")
        return len(self._cameras)

    def has_camera(self, cam: Camera) -> bool:
        print(f"[Fallback][Scene.has_camera] camera={cam}")
        return cam in self._cameras

    def get_aabb(self):
        print("[Fallback][Scene.get_aabb]")
        return [0, 0, 0, 0, 0, 0]


# ================================
# Facade（保持与旧加载器兼容）
# ================================
class CoronaEngine:
    Geometry = Geometry
    Mechanics = Mechanics
    Optics = Optics
    Acoustics = Acoustics
    Kinematics = Kinematics
    ActorProfile = ActorProfile
    Actor = Actor
    Camera = Camera
    ImageEffects = ImageEffects
    Environment = Environment
    Scene = Scene
