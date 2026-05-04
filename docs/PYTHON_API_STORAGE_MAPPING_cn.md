# CoronaEngine Python API 与内部存储映射

## 1. 文档目的

本文档总结 Python API 暴露的对象与 CoronaEngine 内部 `SharedDataHub` 存储之间的对应关系，回答两个核心问题：

- Python 侧每个对象最终落到哪个 storage。
- 哪些接口是“直接读写引擎状态”，哪些仍然只是本地包装或占位实现。

本文以当前实现为准，主要依据：

- `include/corona/systems/script/corona_engine_api.h`
- `src/systems/script/python/corona_engine_api.cpp`
- `src/systems/script/python/engine_bindings.cpp`
- `include/corona/shared_data_hub.h`

## 2. 总体结论

当前 Python API 不是独立脚本模型，而是 `SharedDataHub` 的一层面向对象封装。

可以把它理解成：

- `engine_bindings.cpp` 决定 Python 能看到哪些类和方法。
- `corona_engine_api.cpp` 决定这些方法最终写到哪个 storage。
- `SharedDataHub` 是 Python API 和各系统共享的单一事实来源。

同时需要注意：

- 不是所有 API 都已经完整接入 storage。
- 部分接口已经有类和绑定，但内部仍是 `TODO` 或占位实现。

## 3. 总映射表

| Python API 类 | 主要存储目标 | 说明 |
| --- | --- | --- |
| `Scene` | `scene_storage` | 管理场景、Actor 列表、Camera 列表、环境句柄、开关状态 |
| `Environment` | `environment_storage` | 管理重力、地面高度、地面弹性、固定步长、太阳方向等 |
| `Geometry` | `geometry_storage` + `model_transform_storage` + `model_resource_storage` | 几何对象本体、局部变换、模型资源三部分分开存储 |
| `Optics` | `optics_storage` | 渲染可见性与材质参数 |
| `Mechanics` | `mechanics_storage` | 物理参数、碰撞回调、移动回调 |
| `Acoustics` | `acoustics_storage` | 音量等声学参数 |
| `Kinematics` | `kinematics_storage` | 已有存储句柄，但动画接口大多未实现 |
| `ActorProfile` | `profile_storage` | 组件句柄组合 |
| `Actor` | `actor_storage` | 持有 profile 句柄列表 |
| `Camera` | `camera_storage` | 相机位置、朝向、FOV、surface、输出模式等 |
| `ImageEffects` | 当前未接入 `SharedDataHub` | 仅本地占位对象 |

## 4. 绑定入口位置

Python 类暴露是在 `src/systems/script/python/engine_bindings.cpp` 中完成的，当前暴露的顶层类包括：

- `Geometry`
- `Mechanics`
- `Optics`
- `Acoustics`
- `Kinematics`
- `ActorProfile`
- `Actor`
- `Camera`
- `ImageEffects`
- `Environment`
- `Scene`

因此如果你要回答“Python 里为什么有这个类”，先看 `engine_bindings.cpp`。

如果要回答“这个类到底写到哪里”，再看 `corona_engine_api.cpp`。

## 5. 分对象映射

### 5.1 Scene

存储目标：

- `SharedDataHub::scene_storage()`

构造与析构：

- 构造时 `allocate()` 一个 `SceneDevice`
- 析构时 `deallocate()` 对应句柄

主要写入内容：

- `environment`
- `actor_handles`
- `camera_handles`
- `enabled`
- `simulation_enabled`

主要接口行为：

- `set_environment()`：写入环境句柄
- `add_actor()` / `remove_actor()` / `clear_actors()`：维护 actor 句柄列表
- `add_camera()` / `remove_camera()` / `clear_cameras()`：维护 camera 句柄列表
- `set_enabled()`：写入场景启用状态
- `set_simulation_enabled()`：写入场景仿真开关

结论：

`Scene` 是场景组织层的直接包装，几乎所有核心字段都真实落入 `scene_storage`。

### 5.2 Environment

存储目标：

- `SharedDataHub::environment_storage()`

主要写入内容：

- `sun_position`
- `floor_grid_enabled`
- `gravity`
- `floor_y`
- `floor_restitution`
- `fixed_dt`

主要接口行为：

- `set_sun_direction()`：写太阳方向
- `set_floor_grid()`：写地面网格开关
- `set_gravity()` / `get_gravity()`：写读重力
- `set_floor_y()` / `get_floor_y()`：写读地面高度
- `set_floor_restitution()` / `get_floor_restitution()`：写读弹性
- `set_fixed_dt()` / `get_fixed_dt()`：写读固定步长

结论：

`Environment` 是比较完整接入的配置对象，既有写接口，也有真实读接口。

### 5.3 Geometry

存储目标：

- `SharedDataHub::model_resource_storage()`
- `SharedDataHub::model_transform_storage()`
- `SharedDataHub::geometry_storage()`

这是当前最重要的复合对象之一。

构造时发生的事情：

1. 导入模型资源。
2. 分配 `model_resource_handle_` 并写入 `model_id`。
3. 分配 `transform_handle_`。
4. 从资源系统读取网格和材质数据。
5. 构建 `MeshDevice` 列表和纹理资源。
6. 分配 `geometry_handle_` 并写入：
   - `transform_handle`
   - `model_resource_handle`
   - `mesh_handles`

主要接口行为：

- `set_position()`：写 `model_transform_storage`
- `set_rotation()`：写 `model_transform_storage`
- `set_scale()`：写 `model_transform_storage`
- `get_position()` / `get_rotation()` / `get_scale()`：读 `model_transform_storage`
- `get_aabb()`：经 `geometry_storage -> model_resource_storage` 读取模型数据

结论：

`Geometry` 不是简单的 transform 包装，而是“模型资源 + 局部变换 + GPU 网格设备数据”的复合入口。

### 5.4 Optics

存储目标：

- `SharedDataHub::optics_storage()`

写入的关键字段：

- `geometry_handle`
- `visible`
- `metallic`
- `roughness`
- `subsurface`
- `specular`
- `specularTint`
- `anisotropic`
- `sheen`
- `sheenTint`
- `clearcoat`
- `clearcoatGloss`
- `ambient`
- `diffuse`
- `specular_color`
- `shininess`

结论：

`Optics` 是比较标准的“组件句柄 + 参数存储”包装器，渲染系统会直接读取这些字段。

### 5.5 Mechanics

存储目标：

- `SharedDataHub::mechanics_storage()`

写入的关键字段：

- `geometry_handle`
- `mass`
- `restitution`
- `damping`
- `physics_enabled`
- `collision_callback`
- `on_move_callback`

主要接口行为：

- `set_mass()` / `get_mass()`
- `set_restitution()` / `get_restitution()`
- `set_damping()` / `get_damping()`
- `set_physics_enabled()` / `get_physics_enabled()`
- `set_collision_callback()`
- `set_on_move_callback()`

说明：

- Python 回调最终被包装成 `std::function` 后写入 `mechanics_storage`。
- 真正调用这些回调的是 `MechanicsSystem`。

结论：

`Mechanics` 已经不是纯参数对象，而是“参数 + 回调桥接”的完整组件入口。

### 5.6 Acoustics

存储目标：

- `SharedDataHub::acoustics_storage()`

已接入字段：

- `geometry_handle`
- `volume`

主要接口行为：

- `set_volume()`
- `get_volume()`

结论：

`Acoustics` 已经接入 storage，但字段和功能还比较少。

### 5.7 Kinematics

存储目标：

- `SharedDataHub::kinematics_storage()`

当前状态：

- 构造时会 `allocate()` 一个句柄。
- 组件与 `Geometry` 建立关联。
- 但 `set_animation()`、`play_animation()`、`stop_animation()`、`get_animation_index()`、`get_current_time()` 目前都只是日志告警。

结论：

`Kinematics` 已经有对象壳和 storage 句柄，但动画行为尚未真正落地。

### 5.8 ActorProfile 与 Actor

存储目标：

- `SharedDataHub::profile_storage()`
- `SharedDataHub::actor_storage()`

工作方式：

- `Actor` 自身分配 `actor_storage` 句柄。
- `add_profile()` 时会为 profile 单独分配 `profile_storage` 条目。
- `profile_storage` 中写入各组件句柄：
  - `optics_handle`
  - `acoustics_handle`
  - `mechanics_handle`
  - `kinematics_handle`
  - `geometry_handle`

当前实现观察：

- 代码会校验 profile 中各组件是否都绑定到同一个 `Geometry`。
- `ActorDevice` 中只保存 `profile_handles`。
- 当前 `add_profile()` 中 `geometry_handle` 被写成了 `0`，没有把 Geometry 句柄写入 `ProfileStorage`，这属于当前实现状态，后续值得确认是否为待修问题。

结论：

`Actor` / `ActorProfile` 是当前“对象组合层”的核心包装，但它们本身不存重数据，主要负责把组件句柄组合起来。

### 5.9 Camera

存储目标：

- `SharedDataHub::camera_storage()`

已接入字段：

- `surface`
- `position`
- `forward`
- `world_up`
- `fov`
- `output_mode`

主要接口行为：

- `set()`：写相机基本姿态参数
- `set_surface()`：写 `surface`，并发布 `DisplaySurfaceChangedEvent`
- `get_surface()`：读 `surface`
- `save_screenshot()`：发布 `ScreenshotRequestEvent`
- `save_screenshot_sync()`：发布同步截图请求并等待结果
- `set_output_mode()` / `get_output_mode()`：写读输出模式

需要额外注意：

- `set_default_surface()` 会遍历 `camera_storage()`，把默认 surface 回填给已有相机。
- `set_size()` 当前只写 `Camera` 包装对象自己的 `width_` / `height_`，没有写入 `camera_storage`。
- `set_viewport_rect()` 和 `pick_actor_at_pixel()` 目前仍未实现。

结论：

`Camera` 已经是较完整的运行时入口，但尺寸、视口和拾取链路还没有完全接入底层存储和系统逻辑。

### 5.10 ImageEffects

存储目标：

- 当前未接入 `SharedDataHub`

当前状态：

- `ImageEffects` 只有本地 `handle_` 占位。
- 析构里还保留了注释掉的 `image_effects_storage` 设想。
- `Camera::set_image_effects()` / `remove_image_effects()` 当前只是在 `Camera` 包装对象里保存裸指针。

结论：

`ImageEffects` 当前还是 API 壳，还没有成为引擎内核数据模型的一部分。

## 6. Python API 哪些是“完整接入”的

当前可以认为接入较完整的对象：

- `Scene`
- `Environment`
- `Geometry`
- `Optics`
- `Mechanics`
- `Acoustics`
- `Actor`
- `Camera`

这些对象的共同特点是：

- 构造时分配 storage 句柄。
- 主要 setter / getter 直接落到 `SharedDataHub`。
- 至少有一个系统会消费这些数据。

## 7. 哪些还在过渡阶段

当前明显处于过渡阶段的对象和接口：

- `Kinematics`：句柄已存在，行为未实现。
- `ImageEffects`：API 已存在，但未进入 `SharedDataHub`。
- `Camera::set_size()`：当前只改包装对象本地状态。
- `Camera::set_viewport_rect()`：未实现。
- `Camera::pick_actor_at_pixel()`：未实现。
- `ActorProfile.geometry_handle`：当前实现里没有实际写入 Geometry 句柄。

## 8. 从 Python 到系统的主路径

当前最典型的主路径可以概括为：

1. Python 通过绑定层创建 `Scene`、`Geometry`、`Optics`、`Mechanics`、`Actor`、`Camera` 等对象。
2. `corona_engine_api.cpp` 将这些对象写入 `SharedDataHub`。
3. `OpticsSystem`、`MechanicsSystem`、`DisplaySystem` 等系统在线程中读取这些 storage。
4. 部分跨系统动作通过事件总线完成，例如：
   - `DisplaySurfaceChangedEvent`
   - `ScreenshotRequestEvent`

因此 Python API 在当前架构中的真实地位是：

- 不是纯脚本层
- 而是运行时数据构造器和引擎状态适配层

## 9. 建议阅读顺序

如果要继续深挖 Python API 与内部实现，建议按这个顺序读：

1. `src/systems/script/python/engine_bindings.cpp`
2. `include/corona/systems/script/corona_engine_api.h`
3. `src/systems/script/python/corona_engine_api.cpp`
4. `include/corona/shared_data_hub.h`
5. `src/systems/optics/optics_system.cpp`
6. `src/systems/mechanics/mechanics_system.cpp`

## 10. 一句话结论

CoronaEngine 当前的 Python API 本质上是 `SharedDataHub` 的 OOP 包装层，其中 `Scene`、`Geometry`、`Optics`、`Mechanics`、`Camera` 等对象已经真实接入引擎数据中心，而 `Kinematics`、`ImageEffects` 和部分 Camera 扩展接口仍处于过渡或占位状态。