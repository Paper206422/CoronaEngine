from typing import Any, Dict, List, Optional

from ..corona_editor import CoronaEditor

CoronaEngine = CoronaEditor.CoronaEngine


class Camera:
    """
    OOP 相机包装：统一通过 set(...) 推送到引擎；包装层提供单项 setter 并维护本地缓存。
    包含图像效果、尺寸管理等功能。
    """

    def __init__(self, position: Optional[List[float]] = None, forward: Optional[List[float]] = None,
                 world_up: Optional[List[float]] = None, fov: Optional[float] = None, name: str = "Camera",
                 width: int = 1920, height: int = 1080):
        if CoronaEngine is None:
            raise RuntimeError("CoronaEngine 未初始化")

        CameraCtor = getattr(CoronaEngine, 'Camera', None)
        if CameraCtor is None:
            raise RuntimeError("CoronaEngine 未提供 Camera 构造器")

        if position is not None and forward is not None and world_up is not None and fov is not None:
            self.engine_obj = CameraCtor(position, forward, world_up, fov)
            self._pos = list(position)
            self._fwd = list(forward)
            self._up = list(world_up)
            self._fov = float(fov)
        else:
            self.engine_obj = CameraCtor()
            self._pos = self.engine_obj.get_position()
            self._fwd = self.engine_obj.get_forward()
            self._up = self.engine_obj.get_world_up()
            self._fov = self.engine_obj.get_fov()

        self.name = name
        self.width = width
        self.height = height
        # 持有强引用，避免 ImageEffects 被 GC 后底层句柄被释放
        self._image_effects_ref = None

    # 单项 setter：更新缓存并统一调用 set
    def _flush(self):
        self.engine_obj.set(self._pos, self._fwd, self._up, self._fov)

    def set_position(self, position: List[float]):
        self._pos = list(position)
        self._flush()

    def get_position(self) -> List[float]:
        return self.engine_obj.get_position()

    def set_forward(self, forward: List[float]):
        self._fwd = list(forward)
        self._flush()

    def get_forward(self) -> List[float]:
        return self.engine_obj.get_forward()

    def set_world_up(self, world_up: List[float]):
        self._up = list(world_up)
        self._flush()

    def get_world_up(self) -> List[float]:
        return self.engine_obj.get_world_up()

    def set_fov(self, fov: float):
        self._fov = float(fov)
        self._flush()

    def get_fov(self) -> float:
        return self.engine_obj.get_fov()

    # 新接口直通
    def set(self, position: List[float], forward: List[float], world_up: List[float], fov: float):
        self._pos, self._fwd, self._up, self._fov = list(position), list(forward), list(world_up), float(fov)
        self.engine_obj.set(self._pos, self._fwd, self._up, self._fov)

    def get_handle(self) -> int:
        return int(self.engine_obj.get_handle())

    def set_surface(self, surface: int):
        self.engine_obj.set_surface(surface)

    def get_surface(self) -> int:
        return self.engine_obj.get_surface()

    def save_screenshot(self, path: str):
        self.engine_obj.save_screenshot(path)

    def save_screenshot_sync(self, path: str):
        self.engine_obj.save_screenshot_sync(path)

    def set_output_mode(self, mode: str):
        self.engine_obj.set_output_mode(mode)

    def get_output_mode(self) -> str:
        return self.engine_obj.get_output_mode()

    # ========== 图像效果与尺寸管理 ==========
    def set_image_effects(self, effects: Any):
        """设置图像效果"""
        if hasattr(effects, 'engine_obj'):
            self._image_effects_ref = effects
            fx_obj = effects.engine_obj
        else:
            fx_obj = effects
        self.engine_obj.set_image_effects(fx_obj)

    def get_image_effects(self) -> Optional[Any]:
        """获取图像效果"""
        return self._image_effects_ref

    def has_image_effects(self) -> bool:
        """检查是否有图像效果"""
        return self._image_effects_ref is not None

    def remove_image_effects(self):
        """移除图像效果"""
        self._image_effects_ref = None
        self.engine_obj.remove_image_effects()

    def set_size(self, width: int, height: int):
        """设置渲染尺寸"""
        self.width = width
        self.height = height
        self.engine_obj.set_size(width, height)

    def set_viewport_rect(self, x: int, y: int, width: int, height: int):
        """设置视口矩形区域"""
        self.engine_obj.set_viewport_rect(x, y, width, height)

    def pick_actor_at_pixel(self, x: int, y: int):
        """在像素坐标处拾取 Actor"""
        return self.engine_obj.pick_actor_at_pixel(x, y)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.name,
            'name': self.name,
            'handle': self.get_handle(),
            'position': list(self.get_position()),
            'forward': list(self.get_forward()),
            'world_up': list(self.get_world_up()),
            'fov': float(self.get_fov()),
            'width': self.width,
            'height': self.height,
        }

    def __repr__(self):
        return f"Camera(name={self.name}, width={self.width}, height={self.height})"
