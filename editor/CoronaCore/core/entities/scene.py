import configparser
import logging
import os
from pathlib import Path
from typing import List, Optional, Dict, Any
from .actor import Actor
from .environment import Environment
from .camera import Camera

from ..corona_editor import CoronaEditor
from ...utils.proejct_utils import auto_save

CoronaEngine = CoronaEditor.CoronaEngine
logger = logging.getLogger(__name__)


class Scene:
    """
    场景包装类：仅管理对象引用，生命周期由外部管理。
    采用 OOP API：引擎 Scene 仅支持 Environment/Actor/Camera 管理。
    """

    def __init__(self, route):

        self.route = route
        self.name = Path(route).stem
        self.file_data = configparser.ConfigParser()

        # 创建引擎场景对象（OOP API）
        if CoronaEngine is None:
            raise RuntimeError("CoronaEngine 未初始化")
        SceneCtor = getattr(CoronaEngine, 'Scene', None)
        if SceneCtor is None:
            raise RuntimeError("CoronaEngine 未提供 Scene 构造器")
        self.engine_scene = SceneCtor()

        # 引用列表（Python 层）
        self._actors: List[Actor] = []
        self._cameras: List[Camera] = []
        self._main_camera: Optional[Camera] = None

        # 环境对象（Python 层）- 自动创建默认环境
        self._environment: Optional[Environment] = None
        try:
            self._environment = Environment(name=f"{self.name}_Environment")
            self.set_environment(self._environment, True)
        except Exception as e:
            # 如果创建失败，继续运行但记录警告
            import logging
            logging.warning(f"Failed to create Environment for Scene '{self.name}': {e}")

        self.terrain_type = ''
        self.terrain_path = ''
        self.script_path = ''

        self.read_data()
        # 场景创建后补齐默认相机（幂等）
        self.ensure_default_camera()
        # 应用保存的相机数据
        self._apply_pending_camera_data()

        # 默认启用物理模拟（否则 MechanicsSystem 会跳过该场景的所有物理计算）
        self.set_simulation_enabled(True)

    @auto_save
    def set_route(self, route):
        self.route = route
        self.name = Path(route).stem
        # save_data 会由装饰器自动调用
        return True

    def read_data(self):
        # 读取文件数据
        if os.path.isabs(self.route):
            data_path = self.route
        else:
            data_path = os.path.join(CoronaEngine.active_project_path, self.route)

        if os.path.exists(data_path):
            self.file_data.read(data_path, encoding='utf-8')

            # 读取太阳设置
            if 'sun' in self.file_data:
                sun_direction_str = self.file_data['sun'].get('sun_direction', '1.0, 1.0, 1.0')
                sun_direction = [float(x.strip()) for x in sun_direction_str.split(',')]
                self.set_sun_direction(sun_direction, True)

                sun_enabled = self.file_data['sun'].getboolean('enabled', True)
                self.set_floor_grid(sun_enabled, True)

            # 读取演员数据 - 构建JSON数据
            if 'actors' in self.file_data:
                actors_section = self.file_data['actors']
                # 收集所有演员的键
                actor_keys = set()
                for key in actors_section:
                    if '.' in key:
                        actor_name = key.split('.')[0]
                        actor_keys.add(actor_name)

                # 为每个演员构建JSON数据
                for actor_name in actor_keys:
                    try:
                        actor_data = self._build_actor_json(actors_section, actor_name)
                        source_index = sum(1 for a in self._actors if a.name == actor_data['name'])
                        # 创建 Actor 对象（传递JSON字符串）
                        actor = Actor(actor_name, actor_data['route'], source_index, actor_data['actor_type'],
                                      parent_scene=self, actor_data=actor_data)
                        if actor:
                            self._actors.append(actor)
                            # 同步注册到 C++ 引擎的 SceneDevice，否则 MechanicsSystem 等无法遍历到
                            if hasattr(self.engine_scene, 'add_actor') and hasattr(actor, 'engine_obj'):
                                self.engine_scene.add_actor(actor.engine_obj)
                    except Exception as e:
                        logger.warning("Scene '%s': 加载 actor '%s' 失败，已跳过：%s", self.name, actor_name, e)

            # 读取脚本数据
            if 'scripts' in self.file_data:
                self.script_path = self.file_data['scripts'].get('path', '')

            # 读取地形数据
            if 'terrain' in self.file_data:
                self.terrain_path = self.file_data['terrain'].get('path', '')
                self.terrain_type = self.file_data['terrain'].get('type', '')

            # 读取相机数据（延迟到 ensure_default_camera 之后应用）
            self._pending_camera_data = {}
            if 'camera' in self.file_data:
                self._pending_camera_data = dict(self.file_data['camera'])

    def _apply_pending_camera_data(self):
        """将从文件读取的相机数据应用到相机上"""
        data = getattr(self, '_pending_camera_data', {})
        if not data:
            return
        for i, cam in enumerate(self._cameras):
            prefix = f'camera{i}'
            pos_str = data.get(f'{prefix}.position')
            fwd_str = data.get(f'{prefix}.forward')
            up_str = data.get(f'{prefix}.world_up')
            fov_str = data.get(f'{prefix}.fov')
            if pos_str and fwd_str and up_str and fov_str:
                try:
                    pos = [float(x.strip()) for x in pos_str.split(',')]
                    fwd = [float(x.strip()) for x in fwd_str.split(',')]
                    up = [float(x.strip()) for x in up_str.split(',')]
                    fov = float(fov_str.strip())
                    if hasattr(cam, 'set'):
                        cam.set(pos, fwd, up, fov)
                except Exception:
                    pass
        self._pending_camera_data = {}

    def save_data(self):
        # 保存文件数据
        if os.path.isabs(self.route):
            data_path = self.route
        else:
            data_path = os.path.join(CoronaEngine.active_project_path, self.route)

        # 确保必要的 section 存在
        for section in ('base', 'sun', 'actors', 'scripts', 'terrain'):
            if section not in self.file_data:
                self.file_data[section] = {}

        # 基础信息
        self.file_data['base']['name'] = self.name

        # 太阳设置
        env = self.get_environment()
        if env and hasattr(env, 'get_sun_direction'):
            sun_direction = env.get_sun_direction()
            self.file_data['sun']['sun_direction'] = f"{sun_direction[0]: .2f}, {sun_direction[1]: .2f}, {sun_direction[2]: .2f}"

        # 演员数据
        self.file_data['actors'] = {}
        used_keys = {}  # 记录已使用的 key，处理同名 actor
        for i, actor in enumerate(self._actors):
            # 使用 actor 的 name 属性或生成一个默认名称
            actor_name = getattr(actor, 'name', f'actor{i + 1}')

            # 确保序列化 key 唯一：同名时追加序号
            if actor_name in used_keys:
                used_keys[actor_name] += 1
                actor_key = f"{actor_name}_{used_keys[actor_name]}"
            else:
                used_keys[actor_name] = 0
                actor_key = actor_name

            self.file_data['actors'][f'{actor_key}.actor_type'] = getattr(actor, 'actor_type', 'actor')
            self.file_data['actors'][f'{actor_key}.route'] = getattr(actor, 'route', '')

            # 获取几何体属性
            if hasattr(actor, '_geometry'):
                position = actor.get_position()
                rotation = actor.get_rotation()
                scale = actor.get_scale()

                self.file_data['actors'][
                    f'{actor_key}.geometry.position'] = f"{position[0]: .2f}, {position[1]: .2f}, {position[2]: .2f}"
                self.file_data['actors'][
                    f'{actor_key}.geometry.rotation'] = f"{rotation[0]: .2f}, {rotation[1]: .2f}, {rotation[2]: .2f}"
                self.file_data['actors'][
                    f'{actor_key}.geometry.scale'] = f"{scale[0]: .2f}, {scale[1]: .2f}, {scale[2]: .2f}"

        # 脚本数据
        self.file_data['scripts']["path"] = self.script_path

        # 地形数据
        self.file_data['terrain']["path"] = self.terrain_path

        # 相机数据
        if 'camera' not in self.file_data:
            self.file_data['camera'] = {}
        for i, cam in enumerate(self._cameras):
            if cam is not None:
                try:
                    pos = cam.get_position()
                    fwd = cam.get_forward()
                    up = cam.get_world_up()
                    fov = cam.get_fov()
                    prefix = f'camera{i}'
                    self.file_data['camera'][f'{prefix}.position'] = f"{pos[0]:.4f}, {pos[1]:.4f}, {pos[2]:.4f}"
                    self.file_data['camera'][f'{prefix}.forward'] = f"{fwd[0]:.4f}, {fwd[1]:.4f}, {fwd[2]:.4f}"
                    self.file_data['camera'][f'{prefix}.world_up'] = f"{up[0]:.4f}, {up[1]:.4f}, {up[2]:.4f}"
                    self.file_data['camera'][f'{prefix}.fov'] = f"{fov:.2f}"
                except Exception:
                    pass

        with open(data_path, 'w', encoding='utf-8') as f:
            self.file_data.write(f)

    @auto_save
    def set_script(self, route):
        self.script_path = route
        return True

    @auto_save
    def set_terrain(self, route):
        self.terrain_path = route
        return True

    # Environment
    @auto_save
    def set_environment(self, environment: Environment, if_init=False) -> bool:
        self._environment = environment
        if hasattr(self.engine_scene, 'set_environment'):
            self.engine_scene.set_environment(
                environment.engine_obj if hasattr(environment, 'engine_obj') else environment)
            if if_init:
                return False
            return True
        return False

    def get_environment(self) -> Optional[Environment]:
        return self._environment

    # Actor 管理
    def _notify_scene_tree_changed(self):
        """通知 SceneBar 前端刷新场景树"""
        try:
            scene_name = getattr(self, 'route', '') or getattr(self, 'name', '')
            CoronaEditor.js_call_func("scene-tree-changed", [scene_name])
        except Exception:
            pass

    @auto_save
    def add_actor(self, actor: Actor, rescene: bool = False) -> bool:
        if actor in self._actors and not rescene:
            return False
        # 自动处理同名冲突：追加后缀 _1, _2, ...
        if not rescene:
            existing_names = {a.name for a in self._actors}
            base_name = actor.name
            suffix = 1
            while actor.name in existing_names:
                actor.name = f"{base_name}_{suffix}"
                suffix += 1
            self._actors.append(actor)
        if hasattr(self.engine_scene, 'add_actor'):
            self.engine_scene.add_actor(actor.engine_obj)
        self._notify_scene_tree_changed()
        return True

    @auto_save
    def remove_actor(self, actor: Actor, rescene: bool = False) -> bool:
        if actor not in self._actors:
            return False
        del actor._optics
        if not rescene:
            self._actors.remove(actor)
        if hasattr(self.engine_scene, 'remove_actor'):
            self.engine_scene.remove_actor(actor.engine_obj)
        self._notify_scene_tree_changed()
        return True  # 返回True触发auto_save

    @auto_save
    def clear_actors(self, rescene: bool = False) -> bool:
        for actor in self._actors.copy():
            self.remove_actor(actor, rescene)
        return True

    # 相机管理
    @auto_save
    def add_camera_to_scene(self, camera: Camera) -> bool:
        if camera in self._cameras:
            return False
        self._cameras.append(camera)
        self.engine_scene.add_camera(getattr(camera, 'engine_obj', camera))
        if self._main_camera is None:
            self._main_camera = camera
            if hasattr(self.engine_scene, 'set_active_camera'):
                self.engine_scene.set_active_camera(getattr(camera, 'engine_obj', camera))
        return True

    @auto_save
    def remove_camera_from_scene(self, camera: Camera) -> bool:
        if camera not in self._cameras:
            return False
        self._cameras.remove(camera)
        self.engine_scene.remove_camera(getattr(camera, 'engine_obj', camera))
        if self._main_camera is camera:
            self._main_camera = self._cameras[0] if self._cameras else None
            if self._main_camera is not None and hasattr(self.engine_scene, 'set_active_camera'):
                self.engine_scene.set_active_camera(getattr(self._main_camera, 'engine_obj', self._main_camera))
        return True

    @auto_save
    def clear_cameras(self) -> bool:
        for cam in self._cameras.copy():
            self.remove_camera_from_scene(cam)
        self._main_camera = None
        return True

    def get_cameras(self) -> List[Camera]:
        return self._cameras.copy()

    # 查询
    def get_actors(self) -> List[Actor]:
        return self._actors.copy()

    def get_actor(self, actor_name: str) -> Optional[Actor]:
        for actor in self._actors:
            if actor.name == actor_name:
                return actor
        return None

    # 太阳方向
    @auto_save
    def set_sun_direction(self, direction: List[float], if_init=False) -> bool:
        """设置太阳方向（主光源方向）- 委托给 Environment"""
        if self._environment:
            self._environment.set_sun_direction(direction)
        else:
            # 降级：如果没有 Environment，尝试直接调用引擎场景
            if hasattr(self.engine_scene, 'set_sun_direction'):
                self.engine_scene.set_sun_direction(direction)
        if if_init:
            return False
        return True

    @auto_save
    def set_floor_grid(self, enabled: bool, if_init: bool = False) -> bool:
        """设置地面网格显示开关 - 委托给 Environment"""
        if self._environment and hasattr(self._environment, 'set_floor_grid'):
            self._environment.set_floor_grid(enabled)
        if if_init:
            return False
        return True

    def set_gravity(self, gravity: List[float]) -> bool:
        """设置重力向量 - 委托给 Environment"""
        if self._environment:
            self._environment.set_gravity(gravity)
        return True

    def get_gravity(self) -> List[float]:
        """获取重力向量"""
        if self._environment:
            return self._environment.get_gravity()
        return [0.0, -9.8, 0.0]

    def set_floor_y(self, y: float) -> bool:
        """设置地面高度 - 委托给 Environment"""
        if self._environment:
            self._environment.set_floor_y(y)
        return True

    def get_floor_y(self) -> float:
        """获取地面高度"""
        if self._environment:
            return self._environment.get_floor_y()
        return 0.0

    def set_floor_restitution(self, restitution: float) -> bool:
        """设置地面弹性系数 - 委托给 Environment"""
        if self._environment:
            self._environment.set_floor_restitution(restitution)
        return True

    def get_floor_restitution(self) -> float:
        """获取地面弹性系数"""
        if self._environment:
            return self._environment.get_floor_restitution()
        return 0.6

    def set_fixed_dt(self, dt: float) -> bool:
        """设置物理固定时间步长 - 委托给 Environment"""
        if self._environment:
            self._environment.set_fixed_dt(dt)
        return True

    def get_fixed_dt(self) -> float:
        """获取物理固定时间步长"""
        if self._environment:
            return self._environment.get_fixed_dt()
        return 1.0 / 60.0

    def get_aabb(self) -> list:
        """获取场景世界 AABB [min_x, min_y, min_z, max_x, max_y, max_z]"""
        return list(self.engine_scene.get_aabb())

    def set_enabled(self, enabled: bool) -> None:
        """启用或禁用场景（禁用后跳过渲染与物理模拟，但不销毁任何 C++ 对象）"""
        if hasattr(self.engine_scene, 'set_enabled'):
            self.engine_scene.set_enabled(enabled)

    def is_enabled(self) -> bool:
        """返回场景当前是否处于启用状态"""
        if hasattr(self.engine_scene, 'is_enabled'):
            return self.engine_scene.is_enabled()
        return True

    def set_simulation_enabled(self, enabled: bool) -> None:
        """启用或禁用该场景的物理模拟（不影响渲染）"""
        if hasattr(self.engine_scene, 'set_simulation_enabled'):
            self.engine_scene.set_simulation_enabled(enabled)

    def is_simulation_enabled(self) -> bool:
        """返回场景物理模拟是否启用"""
        if hasattr(self.engine_scene, 'is_simulation_enabled'):
            return self.engine_scene.is_simulation_enabled()
        return False

    def ensure_default_camera(self) -> bool:
        """确保场景至少有一个 Camera。"""
        created = False

        if not self._cameras:
            camera = Camera(name=f"{self.name}_MainCamera")
            self._cameras.append(camera)
            self.engine_scene.add_camera(getattr(camera, 'engine_obj', camera))
            self._main_camera = camera
            if hasattr(self.engine_scene, 'set_active_camera'):
                self.engine_scene.set_active_camera(getattr(camera, 'engine_obj', camera))
            created = True

        if self._main_camera is None:
            self._main_camera = self._cameras[0]
            if hasattr(self.engine_scene, 'set_active_camera'):
                self.engine_scene.set_active_camera(getattr(self._main_camera, 'engine_obj', self._main_camera))

        return created

    def get_active_camera(self) -> Optional[Camera]:
        self.ensure_default_camera()
        if not self._cameras:
            return None
        if self._main_camera is not None:
            return self._main_camera
        return self._cameras[0]

    def find_camera(self, camera_name: Optional[str]) -> Optional[Camera]:
        if not camera_name:
            return self.get_active_camera()

        for camera in self._cameras:
            if getattr(camera, 'name', None) == camera_name:
                return camera

        logger.warning("Scene.find_camera: camera '%s' not found in scene '%s', fallback to active camera",
                       camera_name, self.name)
        return self.get_active_camera()

    # Camera 设置（兼容旧接口）
    @auto_save
    def set_camera(self, position, forward, up, fov: float,
                   camera_name: Optional[str] = None) -> bool:
        """设置摄像头参数"""
        self.ensure_default_camera()
        camera = self.find_camera(camera_name)

        if camera is not None:
            self._main_camera = camera if isinstance(camera, Camera) else self._main_camera
            if hasattr(self.engine_scene, 'set_active_camera'):
                self.engine_scene.set_active_camera(getattr(camera, 'engine_obj', camera))

            logger.info("Scene.set_camera scene=%s camera=%s camera_type=%s",
                        self.name,
                        getattr(camera, 'name', camera_name),
                        type(camera).__name__)

            if hasattr(camera, 'set'):
                camera.set(position, forward, up, fov)
                return True

            if hasattr(camera, 'engine_obj') and hasattr(camera.engine_obj, 'set'):
                camera.engine_obj.set(position, forward, up, fov)
                return True

            logger.error("Scene.set_camera failed: camera object has no callable set() path")
            return False

        logger.error("Scene.set_camera failed: no camera available")
        return False

    def to_dict(self):
        """生成场景快照"""
        self.ensure_default_camera()

        sun_direction = [0.0, -1.0, 0.0]
        floor_grid_enabled = True
        env = self.get_environment()
        if env and hasattr(env, 'get_sun_direction'):
            sun_direction = env.get_sun_direction()
        if env and hasattr(env, 'get_floor_grid'):
            floor_grid_enabled = env.get_floor_grid()

        active_camera = self.get_active_camera()
        camera_payloads = [cam.to_dict() for cam in self.get_cameras()]

        return {
            "id": self.route,
            "scene_id": self.route,
            "name": self.name,
            "active_camera_id": getattr(active_camera, 'name', None),
            "active_camera_name": getattr(active_camera, 'name', None),
            "camera": active_camera.to_dict() if hasattr(active_camera, 'to_dict') else None,
            "cameras": camera_payloads,
            "sun": {
                "enabled": floor_grid_enabled,
                "direction": sun_direction,
            },
            "grid": {
                "enabled": floor_grid_enabled,
            },
            "terrain": {
                "path": self.terrain_path,
                "type": self.terrain_type
            },
            "script": self.script_path,
            "actors": [actor.to_dict() for actor in self.get_actors()]
        }

    def find_actor(self, actor_name: str | None):
        """查找 Actor（支持模糊匹配）"""
        if not actor_name:
            return None

        actor = self.get_actor(actor_name)
        if actor:
            return actor

        def _normalize_actor_name(name: str) -> str:
            """标准化 Actor 名称（去除引号、扩展名等）"""
            value = name.strip().strip('"').strip("'")
            base = os.path.splitext(value.lower())[0]
            return base

        # 模糊匹配
        normalized = _normalize_actor_name(actor_name)
        for candidate in self.get_actors():
            if _normalize_actor_name(candidate.name) == normalized:
                return candidate
        return None

    def find_actor_by_route(self, route: str):
        """按文件路径查找 Actor"""
        for actor in self._actors:
            if actor.route == route:
                return actor
        return None

    def _build_actor_json(self, actors_section: configparser.SectionProxy, actor_name: str) -> Dict[str, Any]:
        """
        从INI配置构建actor的JSON数据

        Args:
            actors_section: actors节的配置数据
            actor_name: actor的名称

        Returns:
            包含actor完整信息的字典
        """
        actor_data = {
            "name": actor_name,
            "actor_type": actors_section.get(f'{actor_name}.actor_type', 'actor'),
            "route": actors_section.get(f'{actor_name}.route', ''),
            "geometry": {}
        }

        # 解析几何体属性
        pos_str = actors_section.get(f'{actor_name}.geometry.position', '0.0, 0.0, 0.0')
        rot_str = actors_section.get(f'{actor_name}.geometry.rotation', '0.0, 0.0, 0.0')
        scale_str = actors_section.get(f'{actor_name}.geometry.scale', '1.0, 1.0, 1.0')

        actor_data["geometry"]["position"] = [float(x.strip()) for x in pos_str.split(',')]
        actor_data["geometry"]["rotation"] = [float(x.strip()) for x in rot_str.split(',')]
        actor_data["geometry"]["scale"] = [float(x.strip()) for x in scale_str.split(',')]

        return actor_data
