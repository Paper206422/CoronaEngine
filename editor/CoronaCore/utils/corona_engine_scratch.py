# -*- coding: utf-8 -*-
"""
CoronaEngine Scratch 兼容层
提供 Scratch 风格的函数式 API，桥接 Blockly 生成的代码与底层 OOP 引擎。

此模块作为模块级函数使用，生成的 Python 代码以：
    from CoronaCore.utils import corona_engine_scratch as CoronaEngine
方式导入，然后调用 CoronaEngine.move(10) 等。

支持两种模式：
1. 独立模式（无参数 set_target）：自建内部 Actor（向后兼容）
2. 绑定模式（调用 set_target）：操作场景管理器中指定的真实 Actor
"""

import random as _random
import time as _time
import logging
import threading as _threading

_logger = logging.getLogger(__name__)

# 线程安全锁：保护对 C++ 引擎对象的访问
_engine_lock = _threading.Lock()

# ============================================================
# 内部状态（模块级单例）
# ============================================================

_x = 0.0
_y = 0.0
_z = 0.0
_rot_x = 0.0
_rot_y = 0.0
_rot_z = 0.0
_size_val = 100.0
_cartoon_index = 0
_visible = True
_variables = {}  # var_name -> float

# 目标 Actor / Scene 引用
_target_scene_name = None
_target_actor_name = None
_target_scene = None
_target_actor = None

# 底层引擎对象
_geometry = None
_optics = None
_kinematics = None
_mechanics = None
_actor = None
_scene = None
_initialized = False

# 标记是否已设置外部目标
_external_target = False

# 脚本执行停止标志（线程安全）
_stop_requested = False

# 运行计数器（用于诊断"只能运行一次"的问题）
_run_count = 0

# 键盘/鼠标事件处理器注册表（由生成的积木代码 register）
_key_handler = None
_mouse_handler = None


def register_key_handler(handler):
    """注册键盘事件处理器"""
    global _key_handler
    _key_handler = handler
    _logger.info(f"[ScratchWrapper] 键盘处理器已注册: {handler.__name__ if handler else 'None'}")


def unregister_key_handler():
    """取消注册键盘事件处理器"""
    global _key_handler
    _key_handler = None
    _logger.info("[ScratchWrapper] 键盘处理器已取消注册")


def register_mouse_handler(handler):
    """注册鼠标事件处理器"""
    global _mouse_handler
    _mouse_handler = handler


def handle_key_event(key, mods=None, display_key=None):
    """分发键盘事件到注册的处理器，同时更新 _key_state"""
    if display_key is None:
        display_key = key
    # 存储所有可能的形式供 detect 积木匹配
    keys_to_set = {key, display_key}
    if len(display_key) == 1:
        keys_to_set.add(display_key.lower())
        keys_to_set.add(display_key.upper())
    for k in keys_to_set:
        _key_state[k] = True

    # 打印当前按键信息，帮助用户确认积木配置
    print(f"[KeyDebug] code={key} key={display_key} stored={sorted(keys_to_set)}", flush=True)

    # 调用注册的 handler
    if _key_handler is None:
        _logger.warning(f"[ScratchWrapper] 收到按键 {key} 但无注册的 handler！")
        return
    try:
        _logger.info(f"[ScratchWrapper] 转发按键 code={key} display={display_key} 到 handler")
        _key_handler(key, mods or [])
    except SystemExit:
        raise
    except Exception as e:
        _logger.warning(f"[ScratchWrapper] 键盘事件处理异常: {e}")


def handle_key_release(key, display_key=None):
    """键盘释放事件：同时清除 code 和 key 形式的状态"""
    _key_state[key] = False
    if display_key:
        _key_state[display_key] = False
        if len(display_key) == 1:
            _key_state[display_key.lower()] = False
            _key_state[display_key.upper()] = False


def handle_mouse_event(event_type, button, x, y):
    """分发鼠标事件到注册的处理器，同时更新鼠标状态"""
    global _mouse_pressed, _mouse_x, _mouse_y
    if event_type in ('click', 'mousedown'):
        _mouse_pressed = True
    elif event_type in ('mouseup',):
        _mouse_pressed = False
    _mouse_x = float(x)
    _mouse_y = float(y)
    # 调用注册的 handler
    if _mouse_handler is not None:
        try:
            _mouse_handler(event_type, button, x, y)
        except SystemExit:
            raise
        except Exception as e:
            _logger.warning(f"[ScratchWrapper] 鼠标事件处理异常: {e}")


def set_target(scene_name: str, actor_name: str):
    """设置该模块操作的目标 Actor（绑定到场景中的真实物体）
    
    调用此函数后，所有操作将作用于场景管理器中的实际 Actor，
    而非自建的内部对象。
    
    Args:
        scene_name: 场景路径/名称，如 "Scene/main.scene"
        actor_name: Actor 名称
    """
    global _target_scene_name, _target_actor_name, _external_target, _initialized
    _target_scene_name = scene_name
    _target_actor_name = actor_name
    _external_target = True
    _initialized = False  # 强制重新初始化
    print(f"[ScratchWrapper] set_target: scene={scene_name}, actor={actor_name}", flush=True)


def _init_engine():
    """延迟初始化底层 CoronaEngine 对象
    
    如果已通过 set_target() 绑定了外部 Actor，则从 scene_manager 查找真实对象；
    否则自建内部 Actor（向后兼容）。
    """
    global _geometry, _optics, _kinematics, _actor, _scene, _initialized
    global _target_scene, _target_actor

    if _initialized:
        return
    _initialized = True

    if _external_target:
        _init_external_target()
    else:
        _init_internal_actor()


def _init_external_target():
    """绑定到场景管理器中的真实 Actor"""
    global _geometry, _optics, _kinematics, _actor, _scene
    global _target_scene, _target_actor

    print(f"[ScratchWrapper] _init_external_target: scene={_target_scene_name} actor={_target_actor_name}", flush=True)

    try:
        from CoronaCore.core.managers import scene_manager

        _target_scene = scene_manager.get(_target_scene_name)
        if _target_scene is None:
            print(f"[ScratchWrapper] 场景未找到，回退独立模式", flush=True)
            _init_internal_actor()
            return

        _target_actor = _target_scene.find_actor(_target_actor_name)
        if _target_actor is None:
            print(f"[ScratchWrapper] Actor未找到，回退独立模式", flush=True)
            _init_internal_actor()
            return

        print(f"[ScratchWrapper] Actor找到: type={type(_target_actor).__name__} id={id(_target_actor)}", flush=True)

        # 获取真实 Actor 的组件
        _actor = _target_actor
        _scene = _target_scene

        if hasattr(_target_actor, '_geometry') and _target_actor._geometry is not None:
            _geometry = _target_actor._geometry
            print(f"[ScratchWrapper] _geometry绑定: type={type(_geometry).__name__}", flush=True)
        else:
            print(f"[ScratchWrapper] _geometry未找到 (hasattr={hasattr(_target_actor, '_geometry')})", flush=True)

        if hasattr(_target_actor, '_optics') and _target_actor._optics is not None:
            _optics = _target_actor._optics
        if hasattr(_target_actor, '_kinematics') and _target_actor._kinematics is not None:
            _kinematics = _target_actor._kinematics

        if hasattr(_target_actor, '_mechanics') and _target_actor._mechanics is not None:
            _mechanics = _target_actor._mechanics

        # 同步内部状态到实际 Actor 的当前值
        try:
            pos = _target_actor.get_position()
            global _x, _y, _z
            _x, _y, _z = float(pos[0]), float(pos[1]), float(pos[2])
        except Exception:
            pass

        try:
            scl = _target_actor.get_scale()
            global _size_val
            _size_val = float(scl[0]) * 100.0
        except Exception:
            pass

        # 旋转状态：读取 C++ 当前值并同步到内部状态
        # 不做 reset-to-zero，因为和后续 rotateX 在同一帧会导致视觉不变
        try:
            if hasattr(_target_actor, 'get_rotation'):
                cpp_rot = _target_actor.get_rotation()
                global _rot_x, _rot_y, _rot_z
                _rot_x, _rot_y, _rot_z = float(cpp_rot[0]), float(cpp_rot[1]), float(cpp_rot[2])
                print(f"[ScratchWrapper] 同步C++ rotation=({_rot_x:.1f},{_rot_y:.1f},{_rot_z:.1f})", flush=True)
        except Exception:
            pass

        print(
            f"[ScratchWrapper] 已绑定: scene={_target_scene_name} "
            f"actor={_target_actor_name} pos=({_x:.2f},{_y:.2f},{_z:.2f}) size={_size_val:.1f}",
            flush=True,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[ScratchWrapper] 绑定外部Actor异常: {e}", flush=True)
        _init_internal_actor()


def _init_internal_actor():
    """独立模式（无场景上下文）

    不创建引擎对象（避免加载不存在的模型文件报错），
    仅使用内部变量 _x/_y/_z/_size_val 追踪状态。
    所有 getter/setter 函数已对 None 做了安全保护。
    """
    global _geometry, _optics, _kinematics, _mechanics, _actor, _scene

    _geometry = None
    _optics = None
    _kinematics = None
    _mechanics = None
    _actor = None
    _scene = None

    _logger.debug("[ScratchWrapper] 独立模式（无渲染）")


# ============================================================
# 运动 (Engine) — 16 个函数
# ============================================================

def move(steps):
    """向前移动 steps 步"""
    _init_engine()
    global _x
    old_x = _x
    _x += float(steps)
    print(f"[ScratchWrapper] move({steps}): X {old_x:.1f} -> {_x:.1f}", flush=True)
    _sync_position()


def _apply_rotation():
    """将内部旋转状态同步到引擎。重力开启时临时暂停物理防止覆盖。"""
    check_stop()
    rot = [_rot_x, _rot_y, _rot_z]
    kine_ok = geo_ok = actor_ok = mech_was_enabled = False
    with _engine_lock:
        # 如果物理系统启用，临时暂停防止覆盖手动旋转
        if _mechanics is not None and hasattr(_mechanics, 'set_physics_enabled'):
            try:
                mech_was_enabled = _mechanics.get_physics_enabled()
                if mech_was_enabled:
                    _mechanics.set_physics_enabled(False)
            except Exception:
                pass

        if _kinematics is not None and hasattr(_kinematics, 'set_rotation'):
            try:
                _kinematics.set_rotation(rot)
                kine_ok = True
            except Exception as e:
                print(f"[ROT-DIAG] _apply_rotation: kine.set FAILED: {e}", flush=True)
        if _geometry is not None:
            try:
                _geometry.set_rotation(rot)
                geo_ok = True
            except Exception as e:
                print(f"[ROT-DIAG] _apply_rotation: geo.set FAILED: {e}", flush=True)
        if _actor is not None and hasattr(_actor, 'set_rotation'):
            try:
                _actor.set_rotation(rot)
                actor_ok = True
            except Exception as e:
                print(f"[ROT-DIAG] _apply_rotation: actor.set FAILED: {e}", flush=True)

        # 恢复物理
        if mech_was_enabled and _mechanics is not None:
            try:
                _mechanics.set_physics_enabled(True)
            except Exception:
                pass

    print(f"[ROT-DIAG] _apply_rotation #{_run_count}: rot={rot} kine_ok={kine_ok} geo_ok={geo_ok} actor_ok={actor_ok} mech_suspended={mech_was_enabled}", flush=True)


def rotateX(angle):
    """绕X轴旋转"""
    _init_engine()
    global _rot_x
    _rot_x += float(angle)
    # 优先 kinematics 增量旋转（物理系统兼容），再同步 geometry（视觉更新）
    if _kinematics is not None and hasattr(_kinematics, 'rotate_x'):
        try:
            _kinematics.rotate_x(float(angle))
        except Exception:
            pass
    # 始终同步 geometry（渲染器读 geometry，不同步则视觉不变）
    _apply_rotation()
    _logger.debug(f"[ScratchWrapper] rotateX({angle}) -> rot_x={_rot_x:.1f}")


def rotateY(angle):
    """绕Y轴旋转"""
    _init_engine()
    global _rot_y
    _rot_y += float(angle)
    if _kinematics is not None and hasattr(_kinematics, 'rotate_y'):
        try:
            _kinematics.rotate_y(float(angle))
        except Exception:
            pass
    _apply_rotation()
    _logger.debug(f"[ScratchWrapper] rotateY({angle}) -> rot_y={_rot_y:.1f}")


def rotateZ(angle):
    """绕Z轴旋转（2D平面旋转）"""
    _init_engine()
    global _rot_z
    old = _rot_z
    _rot_z += float(angle)
    has_kine = _kinematics is not None and hasattr(_kinematics, 'rotate_z')
    has_geo = _geometry is not None
    print(f"[ROT-DIAG] rotateZ({angle}) #{_run_count}: _rot_z {old:.1f}->{_rot_z:.1f} has_kine={has_kine} has_geo={has_geo}", flush=True)
    if has_kine:
        try:
            _kinematics.rotate_z(float(angle))
            print(f"[ROT-DIAG] rotateZ: kinematics.rotate_z OK", flush=True)
        except Exception as e:
            print(f"[ROT-DIAG] rotateZ: kinematics.rotate_z FAILED: {e}", flush=True)
    _apply_rotation()


def face(direction):
    """面向某个方向（0=右, 90=前, 180=左, 270=后，设置绝对朝向）"""
    _init_engine()
    global _rot_y
    _rot_y = float(direction)
    _apply_rotation()


def rotationX():
    """获取当前X轴旋转角度"""
    _init_engine()
    return _rot_x


def rotationY():
    """获取当前Y轴旋转角度"""
    _init_engine()
    return _rot_y


def rotationZ():
    """获取当前Z轴旋转角度"""
    _init_engine()
    return _rot_z


def moveto(position):
    """移动到预设位置"""
    _init_engine()
    global _x, _y, _z

    import random

    if position == 'random_position':
        _x = random.uniform(-10, 10)
        _y = random.uniform(-5, 5)
        _z = random.uniform(-10, 10)
    elif position == 'sight_position':
        _x, _y, _z = 0.0, 0.0, 0.0
    else:
        print(f"[ScratchWrapper] moveto 未知位置: {position}", flush=True)
        return

    _sync_position()
    print(f"[ScratchWrapper] moveto({position}) -> ({_x:.2f}, {_y:.2f}, {_z:.2f})", flush=True)


def movetoXYZ(position):
    """移动到 XYZ 位置"""
    _init_engine()
    _logger.debug(f"[ScratchWrapper] movetoXYZ({position})")


def movetoXYZtime(t, x1, x2, x3):
    """在 t 时间内移动到 (x1,x2,x3)"""
    _init_engine()
    global _x, _y, _z
    _x, _y, _z = float(x1), float(x2), float(x3)
    _sync_position()
    _logger.debug(f"[ScratchWrapper] movetoXYZtime(t={t}, x={x1},{x2},{x3})")


def Xset(x):
    """设置 X 坐标"""
    _init_engine()
    global _x
    _x = float(x)
    _sync_position()


def Yset(y):
    """设置 Y 坐标"""
    _init_engine()
    global _y
    _y = float(y)
    _sync_position()


def Zset(z):
    """设置 Z 坐标"""
    _init_engine()
    global _z
    _z = float(z)
    _sync_position()


def Xadd(dx):
    """X 坐标增加"""
    _init_engine()
    global _x
    _x += float(dx)
    _sync_position()


def Yadd(dy):
    """Y 坐标增加"""
    _init_engine()
    global _y
    _y += float(dy)
    _sync_position()


def Zadd(dz):
    """Z 坐标增加"""
    _init_engine()
    global _z
    _z += float(dz)
    _sync_position()


def X():
    """获取 X 坐标"""
    _init_engine()
    return _x


def Y():
    """获取 Y 坐标"""
    _init_engine()
    return _y


def Z():
    """获取 Z 坐标"""
    _init_engine()
    return _z


def _sync_position():
    """将内部坐标同步到引擎 Geometry"""
    check_stop()  # 旧代码无 check_stop 时，这里兜底检查
    with _engine_lock:
        if _geometry is not None:
            try:
                _geometry.set_position([_x, _y, _z])
                return
            except Exception as e:
                _logger.debug(f"_sync_position FAILED: {e}")
        if _actor is not None and hasattr(_actor, 'set_position'):
            try:
                _actor.set_position([_x, _y, _z])
                return
            except Exception as e:
                _logger.debug(f"_sync_position(actor) FAILED: {e}")


# ============================================================
# 外观 (Appearance) — 11 个函数
# ============================================================

def cartoonSet(index):
    """切换到指定动画"""
    _init_engine()
    global _cartoon_index
    _cartoon_index = int(index)
    if _kinematics is not None:
        try:
            _kinematics.set_animation(int(index))
        except Exception:
            pass


def nextCartoon():
    """切换到下一个动画"""
    _init_engine()
    global _cartoon_index
    _cartoon_index += 1
    if _kinematics is not None:
        try:
            _kinematics.set_animation(_cartoon_index)
        except Exception:
            pass


def playCartoon():
    """播放动画"""
    _init_engine()
    if _kinematics is not None:
        try:
            _kinematics.play_animation()
        except Exception:
            pass


def stopCartoon():
    """停止动画"""
    _init_engine()
    if _kinematics is not None:
        try:
            _kinematics.stop_animation()
        except Exception:
            pass


def resetCartoon():
    """重置动画"""
    _init_engine()
    global _cartoon_index
    _cartoon_index = 0
    if _kinematics is not None:
        try:
            _kinematics.set_animation(0)
        except Exception:
            pass


def sizeAdd(ds):
    """大小增加"""
    _init_engine()
    global _size_val
    _size_val += float(ds)
    _sync_scale()


def sizeSet(sz):
    """设置大小"""
    _init_engine()
    global _size_val
    _size_val = float(sz)
    _sync_scale()


def show(v=None):
    """显示"""
    _init_engine()
    global _visible
    _visible = True
    if _optics is not None:
        try:
            _optics.set_visible(True)
        except Exception:
            pass
    elif _actor is not None and hasattr(_actor, 'set_visible'):
        try:
            _actor.set_visible(True)
        except Exception:
            pass


def hide(v=None):
    """隐藏"""
    _init_engine()
    global _visible
    _visible = False
    if _optics is not None:
        try:
            _optics.set_visible(False)
        except Exception:
            pass
    elif _actor is not None and hasattr(_actor, 'set_visible'):
        try:
            _actor.set_visible(False)
        except Exception:
            pass


def cartoon():
    """获取当前动画编号"""
    _init_engine()
    return _cartoon_index


def size():
    """获取当前大小"""
    _init_engine()
    return _size_val


def _sync_scale():
    s = _size_val / 100.0
    check_stop()  # 旧代码无 check_stop 时，这里兜底检查
    with _engine_lock:
        if _geometry is not None:
            try:
                _geometry.set_scale([s, s, s])
                return
            except Exception as e:
                _logger.debug(f"_sync_scale FAILED: {e}")
        if _actor is not None and hasattr(_actor, 'set_scale'):
            try:
                _actor.set_scale([s, s, s])
                return
            except Exception as e:
                _logger.debug(f"_sync_scale(actor) FAILED: {e}")


# ============================================================
# 侦测 (Detect) — 8 个函数
# ============================================================

# 全局输入状态（由 CEF 桥接或独立 demo 更新）
_key_state = {}       # 按键名 → bool (是否按下)
_mouse_pressed = False
_mouse_x = 0.0
_mouse_y = 0.0


def update_key_state(key, pressed):
    """更新按键状态（由外部事件系统调用）"""
    _key_state[key] = bool(pressed)


def update_mouse_state(pressed, x, y):
    """更新鼠标状态（由外部事件系统调用）"""
    global _mouse_pressed, _mouse_x, _mouse_y
    _mouse_pressed = bool(pressed)
    _mouse_x = float(x)
    _mouse_y = float(y)


def touch(target):
    """检测是否碰到目标"""
    return False


def distance(target):
    """到目标的距离"""
    return 0.0


def ask(question):
    """询问并等待回答"""
    _logger.info(f"[ScratchWrapper] ask: {question}")
    try:
        return input(question)
    except (EOFError, OSError):
        return ""


def keyboard(key):
    """检测按键是否按下"""
    return _key_state.get(key, False)


def keyboard0(key):
    """检测按键是否未按下"""
    return not _key_state.get(key, False)


def mouse1():
    """检测鼠标是否按下"""
    return _mouse_pressed


def mouse0():
    """检测鼠标是否未按下"""
    return not _mouse_pressed


def attribute(name):
    """获取属性值
    支持: X, Y, Z, SIZE, DIRECTION, NAME, ID
    """
    _init_engine()
    if name == 'X':
        return _x
    elif name == 'Y':
        return _y
    elif name == 'Z':
        return _z
    elif name == 'SIZE':
        return _size_val
    elif name == 'DIRECTION':
        return _rot_y
    elif name == 'ROTX':
        return _rot_x
    elif name == 'ROTY':
        return _rot_y
    elif name == 'ROTZ':
        return _rot_z
    elif name in ('NAME', 'ID'):
        return _cartoon_index
    return 0.0


# ============================================================
# 控制 (Control) — 7 个函数
# ============================================================

def check_stop():
    """检查停止标志，如果已请求停止则抛出 SystemExit"""
    if _stop_requested:
        raise SystemExit(0)


def wait(seconds):
    """等待指定秒数，每 0.1 秒检查一次停止标志"""
    remaining = float(seconds)
    while remaining > 0:
        if _stop_requested:
            raise SystemExit(0)
        _time.sleep(min(0.1, remaining))
        remaining -= 0.1


def stop(option):
    """停止脚本
    option 可能值:
      - 'ALL_SCRIPTS' / 'all' → 停止所有脚本（退出进程）
      - 'CURRENT_SCRIPT' / 'this' → 停止当前脚本
      - 'OTHER_SCRIPTS_OF_ACTOR' → 停止该角色的其他脚本（单脚本模式下同 this）
    """
    if option in ("ALL_SCRIPTS", "all"):
        import sys
        sys.exit(0)
    raise SystemExit(0)


def cloneStart():
    """当作为克隆体启动时"""
    _logger.debug("[ScratchWrapper] cloneStart")


def clone(name):
    """克隆自身"""
    _logger.debug(f"[ScratchWrapper] clone({name})")


def deleteClone():
    """删除此克隆体"""
    _logger.debug("[ScratchWrapper] deleteClone")


def setScene(name):
    """切换场景"""
    _logger.debug(f"[ScratchWrapper] setScene({name})")


def nextScene():
    """下一个场景"""
    _logger.debug("[ScratchWrapper] nextScene")


# ============================================================
# 事件 (Event) — 4 个函数
# ============================================================

def gameStart():
    """游戏开始事件标记"""
    _logger.debug("[ScratchWrapper] gameStart")


def RB(message):
    """发送消息（广播）"""
    _logger.debug(f"[ScratchWrapper] RB: {message}")


def broadcast(message):
    """广播消息"""
    _logger.debug(f"[ScratchWrapper] broadcast: {message}")


def broadcastWait(message):
    """广播消息并等待"""
    _logger.debug(f"[ScratchWrapper] broadcastWait: {message}")


# ============================================================
# 数学 (Math)
# ============================================================

def random(a, b):
    """返回 a 到 b 之间的随机数"""
    return _random.uniform(float(a), float(b))


# ============================================================
# 变量 (Variable)
# ============================================================

def var_add(name, value):
    """变量增加"""
    _variables[name] = _variables.get(name, 0.0) + float(value)


def var_set(name, value):
    """设置变量值"""
    _variables[name] = float(value)


def var_show(name):
    """显示变量"""
    _logger.info(f"[ScratchWrapper] var_show: {name} = {_variables.get(name, 0.0)}")


def var_hide(name):
    """隐藏变量"""
    _logger.debug(f"[ScratchWrapper] var_hide: {name}")


# ============================================================
# 列表 (List)
# ============================================================

def list_show(name):
    """显示列表"""
    _logger.debug(f"[ScratchWrapper] list_show: {name}")


def list_hide(name):
    """隐藏列表"""
    _logger.debug(f"[ScratchWrapper] list_hide: {name}")


# ============================================================
# 脚本停止控制
# ============================================================

def reset_state():
    """重置所有运行时状态（新脚本执行前调用）"""
    global _x, _y, _z, _rot_x, _rot_y, _rot_z, _size_val, _cartoon_index, _visible
    global _variables, _initialized, _external_target
    global _stop_requested, _key_state, _mouse_pressed, _mouse_x, _mouse_y
    global _target_scene_name, _target_actor_name, _target_scene, _target_actor
    global _geometry, _optics, _kinematics, _mechanics, _actor, _scene
    global _key_handler, _mouse_handler

    _x = 0.0
    _y = 0.0
    _z = 0.0
    _rot_x = 0.0
    _rot_y = 0.0
    _rot_z = 0.0
    _size_val = 100.0
    _cartoon_index = 0
    _visible = True
    _variables = {}
    _initialized = False
    _external_target = False
    _stop_requested = False
    _key_state = {}
    _mouse_pressed = False
    _mouse_x = 0.0
    _mouse_y = 0.0
    _target_scene_name = None
    _target_actor_name = None
    _target_scene = None
    _target_actor = None
    _geometry = None
    _optics = None
    _kinematics = None
    _mechanics = None
    _actor = None
    _scene = None
    _key_handler = None
    _mouse_handler = None
    global _run_count
    _run_count += 1
    print(f"[ROT-DIAG] reset_state #{_run_count}: _rot_z={_rot_z:.1f} _initialized={_initialized} _geometry={_geometry is not None} _kinematics={_kinematics is not None}", flush=True)


def request_stop():
    """请求停止当前正在执行的脚本"""
    global _stop_requested
    _stop_requested = True
    _logger.info("[ScratchWrapper] 停止请求已发送")


def reset_stop():
    """重置停止标志（新脚本执行前调用）"""
    global _stop_requested
    _stop_requested = False


def is_stop_requested():
    """检查是否已请求停止"""
    return _stop_requested