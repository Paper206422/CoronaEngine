# Vision 渲染后端接入文档

本文档总结当前 Vision 路径追踪后端与 CoronaEngine 的适配代码位置与职责。

---

## 适配器一：VisionOutputBridge（像素格式转换）

**位置**
- 头文件：`src/systems/optics/vision/vision_output_bridge.h`
- 实现：`src/systems/optics/vision/vision_output_bridge.cpp`
- 命名空间：`Corona::Systems::Vision`
- 编译保护：`#ifdef CORONA_ENABLE_VISION`

**职责**

将 Vision `FrameBuffer` 输出的 `float4 RGBA32F`（每通道 32-bit 浮点）像素数组转换为
Horizon 所需的 `RGBA16F`（每通道 16-bit 半精度浮点），并通过 `HardwareExecutor` 上传
到 `HardwareImage`，供后续显示管线使用。

**关键接口**

```cpp
// 上传 RGBA32F 数据到 HardwareImage（RGBA16F 格式）
static bool upload_to_hardware_image(
    const float* rgba32f_data,
    uint32_t width,
    uint32_t height,
    HardwareImage& out_image,
    HardwareExecutor& executor);

// IEEE 754 float32 → float16 转换
static uint16_t float_to_half(float f);
```

---

## 适配器二：OpticsSystem Vision 方法（渲染循环与后端调度）

**位置**
- 头文件声明：`include/corona/systems/optics/optics_system.h`（`#ifdef CORONA_ENABLE_VISION` 块）
- 实现：`src/systems/optics/optics_system.cpp`
- 命名空间：`Corona::Systems`

**职责**

`OpticsSystem` 是 CoronaEngine 的渲染驱动系统，通过以下两个私有方法桥接 Vision 后端：

| 方法 | 作用 |
|------|------|
| `init_vision_lazy()` | 首次切换到 Vision 后端时执行懒初始化，纯代码创建 fixed `vision::Pipeline`，再把 Corona 场景数据注入到 Vision scene |
| `run_vision_frame(frame_count, frame_index)` | 每帧调用 `Pipeline::render()`，读取 `window_buffer_`（`vector<float4>`），调用 `VisionOutputBridge` 上传图像，发布 `OpticsFrameReadyEvent` |

相机同步已收敛为独立 adapter：

- 头文件：`src/systems/optics/vision/vision_camera_adapter.h`
- 实现：`src/systems/optics/vision/vision_camera_adapter.cpp`
- 职责：从引擎主相机读取位置、朝向、FOV 与尺寸，负责 Vision sensor 更新、分辨率切换与累积失效。

**后端切换机制**

`update()` 入口处优先检测 Vision 路径，绕过 Native Vulkan 管线的 Guard 条件：

```cpp
void OpticsSystem::update() {
#ifdef CORONA_ENABLE_VISION
    if (current_backend_ == RenderBackend::Vision) {
        // 直接走 Vision 帧循环，不经过 Native 初始化检查
        optics_pipeline(vc, vi);
        return;
    }
#endif
    // Native Vulkan 管线...
}
```

---

## 适配器三：Python API 实现（C++ 侧实现）

**位置**
- 文件：`src/systems/script/python/corona_engine_api.cpp`（文件末尾）
- 命名空间：`Corona::API`

**职责**

将后端切换操作暴露为 Python 可调用的 C++ 函数。通过
`KernelContext → SystemManager → get_system("Optics") → dynamic_cast<OpticsSystem*>`
访问 `OpticsSystem`。

**两个函数**

```cpp
// 切换后端，接受 "native" 或 "vision" 字符串
void set_render_backend(const std::string& backend_name);

// 返回当前后端名称 "native" / "vision"
std::string get_render_backend();
```

---

## 适配器四：nanobind 绑定（Python 模块注册）

**位置**
- 文件：`src/systems/script/python/engine_bindings.cpp`（渲染后端切换 API 块）

**职责**

通过 nanobind 将适配器三的两个 C++ 函数注册到 `corona_engine` Python 模块，
Python 脚本可直接调用：

```python
import corona_engine as ce
ce.set_render_backend("vision")   # 下一帧生效
print(ce.get_render_backend())    # "vision"
```

**注册代码**

```cpp
m.def("set_render_backend", &Corona::API::set_render_backend,
      nb::arg("backend_name"),
      "Switch render backend: 'native' or 'vision'. Takes effect on the next frame.");

m.def("get_render_backend", &Corona::API::get_render_backend,
      "Return the current active render backend name: 'native' or 'vision'.");
```

---

## 数据流总览

```
Python 脚本
  │  ce.set_render_backend("vision")
  ▼
corona_engine_api.cpp          ← 适配器三：API 实现
  │  OpticsSystem::set_render_backend(Vision)
  ▼
optics_system.cpp update()     ← 适配器二：渲染循环
  │  init_vision_lazy()        ← 首次：纯代码创建 Vision Pipeline
  │  vision_camera_adapter     ← 每帧：同步主相机与分辨率
  │  Pipeline::render()        ← Vision 渲染
  │  window_buffer_ (float4[]) ← FrameBuffer 输出
  ▼
VisionOutputBridge             ← 适配器一：RGBA32F → RGBA16F
  │  HardwareImage (RGBA16F)
  ▼
OpticsFrameReadyEvent → DisplaySystem → 屏幕显示
```

---

## 编译开关

所有 Vision 适配代码均受 `CORONA_ENABLE_VISION` 宏保护，在 CMake 中通过以下方式开启：

```cmake
target_compile_definitions(corona_engine PRIVATE CORONA_ENABLE_VISION)
```

未定义该宏时，上述适配代码均不参与编译，引擎退回 Native Vulkan 管线。
