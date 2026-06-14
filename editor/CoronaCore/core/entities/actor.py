import configparser
import logging
import shutil
import time
import uuid
import weakref
from pathlib import Path
from typing import Any, Dict, Optional, List
import os

from ..components.geometry import Geometry
from ..components.mechanics import Mechanics
from ..components.acoustics import Acoustics
from ..components.optics import Optics
from ..corona_editor import CoronaEditor
from ...utils.proejct_utils import auto_save

CoronaEngine = CoronaEditor.CoronaEngine

_handle_to_actor = weakref.WeakValueDictionary()


class Actor:
    """
    OOP API 包装：基于 CoronaEngine.Actor。
    - 构造可选传入模型路径：自动创建 Geometry + 默认组件，组装成 Profile 加入 Actor
    - move/rotate/scale 改为作用于 active profile 的 Geometry（不再调用原生的旧接口）
    """

    def __init__(self, name='', route: Optional[str] = None, source_index: int = 0, actor_type: str = "actor",
                 parent_scene=None, actor_data=None):
        self.route = route
        if name:
            self.name = name
        else:
            self.name = Path(route).stem if route else ""
        self.actor_type = actor_type
        self.parent = parent_scene
        if source_index != 0:
            self.name = f"{self.name}_{source_index}"

        self.model_path = ""
        self.model_dependencies = []
        self.script_path = ""
        self.actor_guid = ""
        self._follow_camera = False
        self._suppress_network_broadcast = bool(
            actor_data and actor_data.get("_suppress_network_broadcast")
        )
        self.network_remote = self._suppress_network_broadcast
        self._collision_callback = None

        self.file_data = configparser.ConfigParser()

        if CoronaEngine is None:
            raise RuntimeError("CoronaEngine 未初始化")

        ActorCtor = getattr(CoronaEngine, 'Actor', None)
        if ActorCtor is None:
            raise RuntimeError("CoronaEngine 未提供 Actor 构造器")

        self.engine_obj = ActorCtor()

        # 解析数据路径和actor数据
        data_path = self._resolve_data_path()

        if actor_data:
            # 从场景中获取数据
            self._load_from_actor_data(actor_data, data_path)
        elif actor_type == "actor":
            # 从文件中读取数据
            self._load_from_config(data_path)
        else:
            self.final_model_path = data_path
            if not self.actor_guid:
                self.actor_guid = f"actor-{uuid.uuid4().hex}"
            self._geometry = Geometry(self.final_model_path)
            self._create_and_add_profile()

        if not self.actor_guid:
            self.actor_guid = f"actor-{uuid.uuid4().hex}"

        self.handle = self.engine_obj.get_handle()
        self._sync_follow_camera_to_engine()
        _handle_to_actor[self.handle] = self

        self._enable_collision_callback = True  # 控制是否启用碰撞回调（Python 层回调开关）
        self._collision_type = 'box'           # 碰撞检测类型：'none'（关闭）/ 'box'（包围盒）/ 'mesh'（网格）
        self._camera_locked_script = None  # CameraLockedObject 脚本引用
        if self.parent:
            if self.network_remote:
                self._disable_local_physics_for_remote_actor()
            self._setup_collision_callback()
            self._setup_on_move_callback()
            if (self.actor_type != "actor" and
                    not self._suppress_network_broadcast and
                    hasattr(self, '_geometry')):
                self._broadcast_actor_created()

    def _resolve_data_path(self) -> Optional[str]:
        """解析数据文件的完整路径"""
        if not self.route:
            return None

        if os.path.isabs(self.route):
            return self.route
        else:
            return os.path.join(CoronaEngine.active_project_path, self.route)

    def _load_from_config(self, data_path: str):
        """从配置文件加载actor数据"""
        self.file_data.read(data_path, encoding='utf-8')

        # 读取模型路径
        self.model_path = self.file_data['base']['path']
        self.actor_guid = self.file_data['base'].get('actor_guid', '')
        self._follow_camera = self.file_data['base'].getboolean('follow_camera', fallback=False)
        if not self.actor_guid:
            self.actor_guid = f"actor-{uuid.uuid4().hex}"
        if self.model_path:
            self.final_model_path = os.path.join(CoronaEngine.active_project_path, self.model_path)
            if self.parent:
                self._create_components_from_config()

        self.script_path = self.file_data['scripts']["path"]

    def _load_from_actor_data(self, actor_data: dict, data_path: str):
        """从actor_data字典加载actor数据"""
        file_follow_camera = False
        if self.actor_type == "actor":
            self.file_data.read(data_path, encoding='utf-8')
            self.model_path = self.file_data['base']['path']
            self.actor_guid = actor_data.get(
                'actor_guid',
                self.file_data['base'].get('actor_guid', '')
            )
            file_follow_camera = self.file_data['base'].getboolean('follow_camera', fallback=False)
            self.script_path = self.file_data['scripts']["path"]
            self.final_model_path = os.path.join(CoronaEngine.active_project_path,
                                                 self.model_path) if self.model_path else ""
        else:
            self.final_model_path = data_path
            self.actor_guid = actor_data.get('actor_guid', '')

        self._follow_camera = self._coerce_bool(
            actor_data.get('follow_camera',
                           actor_data.get('render_space', 'ui' if file_follow_camera else 'scene') == 'ui')
        )

        if not self.actor_guid:
            self.actor_guid = f"actor-{uuid.uuid4().hex}"

        if self.final_model_path:
            self._create_components_from_actor_data(actor_data)

    def _create_components_from_config(self):
        """从配置文件创建几何体和组件"""
        if not os.path.exists(self.final_model_path):
            raise FileNotFoundError(f"模型文件不存在: {self.final_model_path}")

        # 创建几何体
        self._geometry = Geometry(self.final_model_path)

        # 从配置文件读取变换参数
        position_str = self.file_data['geometry'].get('position', '0.0, 0.0, 0.0')
        position = [float(x.strip()) for x in position_str.split(',')]
        self.set_position(position, True)

        rotation_str = self.file_data['geometry'].get('rotation', '0.0, 0.0, 0.0')
        rotation = [float(x.strip()) for x in rotation_str.split(',')]
        self.set_rotation(rotation, True)

        scale_str = self.file_data['geometry'].get('scale', '1.0, 1.0, 1.0')
        scale = [float(x.strip()) for x in scale_str.split(',')]
        self.set_scale(scale, True)

        self._create_and_add_profile()

    def _create_components_from_actor_data(self, actor_data: dict):
        """从actor_data字典创建几何体和组件"""
        if not os.path.exists(self.final_model_path):
            raise FileNotFoundError(f"模型文件不存在: {self.final_model_path}")

        # 创建几何体
        self._geometry = Geometry(self.final_model_path)

        # 从actor_data读取变换参数
        self.set_position(actor_data["geometry"]["position"], True)
        self.set_rotation(actor_data["geometry"]["rotation"], True)
        self.set_scale(actor_data["geometry"]["scale"], True)

        self._create_and_add_profile()

    def _create_and_add_profile(self):
        """创建组件、配置集合并添加到actor"""
        ActorProfile = getattr(CoronaEngine, 'ActorProfile', None)
        if ActorProfile is None:
            raise RuntimeError("CoronaEngine 未提供 ActorProfile 类型")

        # 创建各个组件
        self._optics = Optics(self._geometry)
        self._mechanics = Mechanics(self._geometry)
        self._acoustics = Acoustics(self._geometry)

        # 创建并配置profile
        prof = ActorProfile()
        prof.geometry = self._geometry.engine_obj
        prof.optics = self._optics.engine_obj
        prof.mechanics = self._mechanics.engine_obj
        prof.acoustics = self._acoustics.engine_obj

        # 添加到actor并激活
        stored = self.engine_obj.add_profile(prof)
        if stored is None:
            raise RuntimeError("无法向 Actor 添加默认 Profile（几何/组件不一致）")
        self.engine_obj.set_active_profile(stored)

    @staticmethod
    def _coerce_bool(value) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "ui")
        return bool(value)

    def _sync_follow_camera_to_engine(self):
        if hasattr(self.engine_obj, 'set_follow_camera'):
            try:
                self.engine_obj.set_follow_camera(self._follow_camera)
            except Exception as exc:
                logging.warning("Failed to sync follow_camera for actor %s: %s",
                                self.name or self.route, exc)

    def _broadcast_actor_created(self):
        """通过 NetworkSystem 广播 Actor 创建事件到已连接的 peer。"""
        try:
            self._ensure_network_model_path_in_project()
            # Use the same format as to_dict() for the actor data
            actor_data = self.to_dict()
            CoronaEditor.js_call_func("actor-sync-broadcast", [actor_data])
        except Exception as exc:
            logging.warning("Actor network create broadcast failed for %s: %s",
                            self.name or self.route, exc)

    def _disable_local_physics_for_remote_actor(self):
        if not hasattr(self, '_mechanics') or self._mechanics is None:
            return
        try:
            self._mechanics.set_physics_enabled(False)
        except Exception as exc:
            logging.warning("Failed to disable local physics for remote actor %s: %s",
                            self.name or self.route, exc)

    def _ensure_network_model_path_in_project(self):
        """Ensure network-created model paths are project-relative and transferable."""
        if self.actor_type == "actor" or not self.route:
            return

        project_root_raw = getattr(CoronaEngine, "active_project_path", None)
        if not project_root_raw:
            return

        project_root = Path(project_root_raw).resolve()
        route_path = Path(self.route)
        source_path = route_path if route_path.is_absolute() else (project_root / route_path)
        source_path = source_path.resolve()

        try:
            source_path.relative_to(project_root)
            rel_path = source_path.relative_to(project_root).as_posix()
            self.route = rel_path
            self.model_path = rel_path
            self.final_model_path = str(source_path)
            return
        except ValueError:
            pass

        if not source_path.is_file():
            logging.warning("Actor network model path is outside project but missing: %s",
                            source_path)
            return

        copied_paths = self._copy_model_asset_bundle_to_project(source_path, project_root)
        if not copied_paths:
            return

        self.route = copied_paths[0]
        self.model_path = copied_paths[0]
        self.final_model_path = str(project_root / copied_paths[0])
        self.model_dependencies = copied_paths[1:]

    def _copy_model_asset_bundle_to_project(self, source_path: Path,
                                            project_root: Path) -> List[str]:
        resource_dir = project_root / "Resource"
        resource_dir.mkdir(parents=True, exist_ok=True)

        copied = []

        def copy_relative(src: Path, relative_to_source_dir: Path = None):
            rel_under_source = (src.name if relative_to_source_dir is None
                                else src.relative_to(relative_to_source_dir).as_posix())
            dst = resource_dir / rel_under_source
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.resolve() != dst.resolve():
                shutil.copy2(src, dst)
            rel_project = dst.relative_to(project_root).as_posix()
            if rel_project not in copied:
                copied.append(rel_project)
            return dst

        copied_model_path = copy_relative(source_path)

        if source_path.suffix.lower() == ".obj":
            source_dir = source_path.parent
            for mtl_path in self._read_obj_material_libraries(source_path):
                mtl_source = (source_dir / mtl_path).resolve()
                if not mtl_source.is_file():
                    logging.warning("OBJ material library missing: %s", mtl_source)
                    continue
                copied_mtl_path = copy_relative(mtl_source)
                for texture_path in self._read_mtl_texture_paths(mtl_source):
                    texture_source = (mtl_source.parent / texture_path).resolve()
                    if not texture_source.is_file():
                        logging.warning("MTL texture missing: %s", texture_source)
                        continue
                    copy_relative(texture_source, source_dir)

        if copied and copied[0] != copied_model_path.relative_to(project_root).as_posix():
            copied.insert(0, copied_model_path.relative_to(project_root).as_posix())
        return copied

    @staticmethod
    def _read_obj_material_libraries(obj_path: Path) -> List[Path]:
        libraries = []
        try:
            with obj_path.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    parts = stripped.split(maxsplit=1)
                    if len(parts) == 2 and parts[0] == "mtllib":
                        libraries.append(Path(parts[1]))
        except Exception as exc:
            logging.warning("Failed to parse OBJ dependencies for %s: %s", obj_path, exc)
        return libraries

    @staticmethod
    def _read_mtl_texture_paths(mtl_path: Path) -> List[Path]:
        texture_keys = {
            "map_Ka", "map_Kd", "map_Ks", "map_Ke", "map_Ns",
            "map_d", "map_bump", "bump", "disp", "decal", "refl",
            "norm", "map_Pr", "map_Pm", "map_Ps", "map_Bump",
        }
        textures = []
        try:
            with mtl_path.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    parts = stripped.split()
                    if len(parts) < 2 or parts[0] not in texture_keys:
                        continue
                    textures.append(Path(parts[-1]))
        except Exception as exc:
            logging.warning("Failed to parse MTL dependencies for %s: %s", mtl_path, exc)
        return textures

    def save_data(self):
        if self.parent:
            self.parent.save_data()
        else:
            self.file_data['base']['name'] = self.name
            self.file_data['base']['path'] = self.model_path
            self.file_data['base']['actor_guid'] = self.actor_guid
            self.file_data['base']['follow_camera'] = 'true' if self._follow_camera else 'false'
            if self.model_path:
                position = self.get_position()
                rotation = self.get_rotation()
                scale = self.get_scale()
                self.file_data['geometry'][
                    f'position'] = f"{position[0]: .2f}, {position[1]: .2f}, {position[2]: .2f}"
                self.file_data['geometry'][
                    f'rotation'] = f"{rotation[0]: .2f}, {rotation[1]: .2f}, {rotation[2]: .2f}"
                self.file_data['geometry'][
                    f'scale'] = f"{scale[0]: .2f}, {scale[1]: .2f}, {scale[2]: .2f}"

            self.file_data['scripts']['path'] = self.script_path

            with open(self._resolve_data_path(), 'w', encoding='utf-8') as f:
                self.file_data.write(f)

    @auto_save
    def set_route(self, route, source_index: int = 0):
        self.route = route
        self.name = Path(route).stem
        if source_index != 0:
            self.name = f"{self.name}_{source_index}"
        return True

    @auto_save
    def set_model(self, route):
        self.model_path = route
        if not hasattr(self, '_geometry'):
            old_collision_type = getattr(self, '_collision_type', 'box')
            self._geometry = Geometry(self.model_path)
            self._create_and_add_profile()
            # 恢复碰撞状态，避免切换模型后开关重置
            self.set_collision_enabled(old_collision_type)
            # 重新设置碰撞回调（新的 mechanics 需要重新注册回调）
            self._setup_collision_callback()
            self._setup_on_move_callback()
        return True

    @auto_save
    def set_script(self, route):
        self.script_path = route
        return True

    # 兼容编辑器的变换操作：直接作用于几何体
    @auto_save
    def scale(self, v: List[float]):
        if not hasattr(self, '_geometry'):
            raise False
        self._geometry.set_scale(v)
        return True

    @auto_save
    def move(self, v: List[float]):
        if not hasattr(self, '_geometry'):
            return False
        pos = self._geometry.get_position()
        new_pos = [pos[0] + v[0], pos[1] + v[1], pos[2] + v[2]]
        self._geometry.set_position(new_pos)
        return True

    @auto_save
    def rotate(self, euler: List[float]):
        if not hasattr(self, '_geometry'):
            return False
        rot = self._geometry.get_rotation()
        self._geometry.set_rotation([rot[0] + euler[0], rot[1] + euler[1], rot[2] + euler[2]])
        return True

    @auto_save
    def set_position(self, position: List[float], if_init=False):
        if not hasattr(self, '_geometry'):
            return False
        self._geometry.set_position(position)
        if if_init:
            return False
        return True

    def get_position(self) -> List[float]:
        if not hasattr(self, '_geometry'):
            raise RuntimeError("当前 Actor 没有 Geometry")
        return self._geometry.get_position()

    @auto_save
    def set_rotation(self, euler: List[float], if_init=False):
        if not hasattr(self, '_geometry'):
            return False
        self._geometry.set_rotation(euler)
        if if_init:
            return False
        return True

    def get_rotation(self) -> List[float]:
        if not hasattr(self, '_geometry'):
            raise RuntimeError("当前 Actor 没有 Geometry")
        return self._geometry.get_rotation()

    @auto_save
    def set_scale(self, scale: List[float], if_init=False):
        if not hasattr(self, '_geometry'):
            return False
        self._geometry.set_scale(scale)
        if if_init:
            return False
        return True

    def get_scale(self) -> List[float]:
        if not hasattr(self, '_geometry'):
            raise RuntimeError("当前 Actor 没有 Geometry")
        return self._geometry.get_scale()

    def set_visible(self, visible: bool):
        if not hasattr(self, '_optics'):
            raise RuntimeError("当前 Actor 没有 Optics")
        self._optics.set_visible(visible)

    def get_visible(self) -> bool:
        if not hasattr(self, '_optics'):
            return True
        return self._optics.get_visible()

    @auto_save
    def set_follow_camera(self, enabled: bool, if_init=False):
        self._follow_camera = self._coerce_bool(enabled)
        self._sync_follow_camera_to_engine()
        if if_init:
            return False
        if self._follow_camera and hasattr(self, '_mechanics') and self._mechanics is not None:
            self._mechanics.set_physics_enabled(False)
        return True

    def get_follow_camera(self) -> bool:
        if hasattr(self.engine_obj, 'get_follow_camera'):
            try:
                self._follow_camera = bool(self.engine_obj.get_follow_camera())
            except Exception as exc:
                logging.warning("Failed to read follow_camera for actor %s: %s",
                                self.name or self.route, exc)
        return self._follow_camera

    def set_mass(self, mass: float):
        if not hasattr(self, '_mechanics'):
            raise RuntimeError("当前 Actor 没有 Mechanics")
        self._mechanics.set_mass(mass)

    def get_mass(self) -> float:
        if not hasattr(self, '_mechanics'):
            raise RuntimeError("当前 Actor 没有 Mechanics")
        return self._mechanics.get_mass()

    def set_restitution(self, restitution: float):
        if not hasattr(self, '_mechanics'):
            raise RuntimeError("当前 Actor 没有 Mechanics")
        self._mechanics.set_restitution(restitution)

    def get_restitution(self) -> float:
        if not hasattr(self, '_mechanics'):
            raise RuntimeError("当前 Actor 没有 Mechanics")
        return self._mechanics.get_restitution()

    def set_damping(self, damping: float):
        if not hasattr(self, '_mechanics'):
            raise RuntimeError("当前 Actor 没有 Mechanics")
        self._mechanics.set_damping(damping)

    def get_damping(self) -> float:
        if not hasattr(self, '_mechanics'):
            raise RuntimeError("当前 Actor 没有 Mechanics")
        return self._mechanics.get_damping()

    def set_physics_enabled(self, enabled: bool):
        """启用或禁用该 Actor 的物理模拟（关闭后物体不参与力学模拟，但仍保留数据）"""
        if not hasattr(self, '_mechanics') or self._mechanics is None:
            raise RuntimeError("当前 Actor 没有 Mechanics")
        self._mechanics.set_physics_enabled(enabled)

    def get_physics_enabled(self) -> bool:
        """获取物理模拟开关状态"""
        if not hasattr(self, '_mechanics') or self._mechanics is None:
            raise RuntimeError("当前 Actor 没有 Mechanics")
        return self._mechanics.get_physics_enabled()

    def set_linear_lock(self, lock_x: bool, lock_y: bool, lock_z: bool):
        """设置线性运动轴锁定（锁定后该轴不参与平移运动）"""
        if not hasattr(self, '_mechanics') or self._mechanics is None:
            raise RuntimeError("当前 Actor 没有 Mechanics")
        self._mechanics.set_linear_lock(lock_x, lock_y, lock_z)

    def get_linear_lock(self):
        """获取线性运动轴锁定状态，返回 [lock_x, lock_y, lock_z]"""
        if not hasattr(self, '_mechanics') or self._mechanics is None:
            return [False, False, False]
        return list(self._mechanics.get_linear_lock())

    def set_angular_lock(self, lock_x: bool, lock_y: bool, lock_z: bool):
        """设置角度运动轴锁定（锁定后该轴不参与旋转运动）"""
        if not hasattr(self, '_mechanics') or self._mechanics is None:
            raise RuntimeError("当前 Actor 没有 Mechanics")
        self._mechanics.set_angular_lock(lock_x, lock_y, lock_z)

    def get_angular_lock(self):
        """获取角度运动轴锁定状态，返回 [lock_x, lock_y, lock_z]"""
        if not hasattr(self, '_mechanics') or self._mechanics is None:
            return [False, False, False]
        return list(self._mechanics.get_angular_lock())

    def set_collision_enabled(self, collision_type: str):
        """
        设置碰撞检测类型。

        Args:
            collision_type: 'none'（关闭碰撞检测）, 'box'（包围盒碰撞）, 'mesh'（网格碰撞）
        """
        self._collision_type = collision_type
        if hasattr(self, '_mechanics') and self._mechanics:
            self._mechanics.set_collision_enabled(collision_type != 'none')

    def get_collision_enabled(self) -> str:
        """获取碰撞检测类型：'none', 'box', 'mesh'"""
        return self._collision_type

    def _setup_collision_callback(self):
        """设置碰撞回调，使用类方法而非外部函数"""

        def collision_handler(other_handle, if_start, normal, point):
            if not self._enable_collision_callback:
                return

            other_actor = _handle_to_actor.get(other_handle)
            # 调用可重写的 on_collision 方法
            self.on_collision(other_actor, if_start, normal, point)

        if hasattr(self, '_mechanics') and self._mechanics:
            self._mechanics.set_collision_callback(collision_handler)

    def on_collision(self, other_actor, if_start, normal, point):
        """
        碰撞回调方法，子类可重写此方法以实现自定义行为。

        Args:
            other_actor: 碰撞的另一方 Actor 对象，可能为 None
            if_start: True 表示碰撞开始，False 表示碰撞结束
            normal: 碰撞法向量
            point: 碰撞点坐标
        """
        # 默认行为：记录碰撞信息
        if other_actor is not None:
            logging.info(f"{self.handle} Collision {'start' if if_start else 'end'} with {other_actor.name} at {point}")
        else:
            logging.info(f"{self.handle} Collision {'start' if if_start else 'end'} with unknown actor at {point}")


    def _setup_on_move_callback(self):
        """设置移动回调，使用类方法而非外部函数"""

        def on_move_handler():
            self.on_move()

        if hasattr(self, '_mechanics') and self._mechanics:
            self._mechanics.set_on_move_callback(on_move_handler)

    def on_move(self):
        """
        移动回调方法，子类可重写此方法以实现自定义行为。
        """
        CoronaEditor.js_call_func("transform-update",
                                  [self.parent.route if self.parent else "", self.name, self.get_position(),
                                   self.get_rotation(), self.get_scale(), self.actor_type])
        if self.actor_guid:
            CoronaEditor.js_call_func("actor-ownership-claim",
                                      [{"actor_guid": self.actor_guid}])
        self.save_data()


    def enable_collision_callback(self, enable: bool):
        """
        启用或禁用碰撞回调。

        Args:
            enable: True 启用回调，False 禁用回调
        """
        self._enable_collision_callback = enable

    # ========== 相机锁定相关 ==========

    def set_camera_locked_script(self, script):
        """设置 CameraLockedObject 脚本引用"""
        self._camera_locked_script = script

    def get_camera_lock_enabled(self) -> bool:
        if self._camera_locked_script is not None:
            return self._camera_locked_script.lock_to_camera
        return False

    def set_camera_lock_enabled(self, enabled: bool):
        if self._camera_locked_script is not None:
            self._camera_locked_script.toggle_lock(enabled)
        else:
            from ..scripts_system.entities.camera_locked_object import CameraLockedObject
            script = CameraLockedObject(f"Actor_{self.name}_CameraLock", self)
            script.initialize()
            self._camera_locked_script = script
            # 注册到 ScriptsManager
            from ..scripts_system.scripts_manager import ScriptsManager
            try:
                for mgr in ScriptsManager._instances:
                    mgr.actor_scripts[self.name] = script
                    break
            except Exception:
                pass
            script.toggle_lock(enabled)

    def get_camera_lock_offset(self) -> list:
        if self._camera_locked_script is not None:
            return self._camera_locked_script.position_offset
        return [0.0, 0.0, 2.0]

    def set_camera_lock_offset(self, offset: list):
        if self._camera_locked_script is not None:
            self._camera_locked_script.position_offset = list(offset)

    def get_camera_lock_rotation_offset(self) -> list:
        if self._camera_locked_script is not None:
            return self._camera_locked_script.rotation_offset
        return [0.0, 0.0, 0.0]

    def set_camera_lock_rotation_offset(self, offset: list):
        if self._camera_locked_script is not None:
            self._camera_locked_script.rotation_offset = list(offset)

    def to_dict(self) -> Dict[str, Any]:
        _, ext = os.path.splitext(self.route)
        follow_camera = self.get_follow_camera()

        result_dict = {
            "name": self.name,
            "actor_guid": self.actor_guid,
            "handle": int(self.handle),
            "path": self.route,
            "scene": self.parent.route if self.parent else "",
            "type": ext.lstrip("."),
            "model": self.model_path,
            "model_dependencies": list(self.model_dependencies),
            "actor_type": self.actor_type,
            "collision": self.get_collision_enabled(),
            "visible": self.get_visible(),
            "script": self.script_path,
            "follow_camera": follow_camera,
            "render_space": "ui" if follow_camera else "scene",
        }

        if hasattr(self, '_geometry'):
            result_dict["geometry"] = {
                "position": self.get_position(),
                "rotation": self.get_rotation(),
                "scale": self.get_scale(),
            }

        if hasattr(self, '_mechanics') and self._mechanics is not None:
            try:
                result_dict["mechanics"] = {
                    "mass": self.get_mass(),
                    "restitution": self.get_restitution(),
                    "damping": self.get_damping(),
                    "physics_enabled": self.get_physics_enabled(),
                    "linear_lock": self.get_linear_lock(),
                    "angular_lock": self.get_angular_lock(),
                }
            except Exception:
                pass

        # 相机锁定信息
        if self._camera_locked_script is not None:
            result_dict["camera_lock"] = self._camera_locked_script.to_dict()
        else:
            result_dict["camera_lock"] = {
                "lock_to_camera": False,
                "position_offset": [0.0, 0.0, 2.0],
                "rotation_offset": [0.0, 0.0, 0.0],
            }

        return result_dict

    def __repr__(self):
        return f"<Actor name={self.name} path={self.route}>"
