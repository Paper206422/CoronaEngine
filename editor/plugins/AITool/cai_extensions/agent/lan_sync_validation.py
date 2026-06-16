"""LAN 同传验证（突击方案 COMMIT 6）。

结论：渐进传输底座已有，无需改动。但有一个 P0 中文路径 bug 需 demo 绕过。

## 验证 1：渐进传输底座已有 ✅

现有机制（codegraph 确认）：
- `actor.py:221 _broadcast_actor_created` → `network_sync_policy.publish_actor_created`
- 每个 actor 创建时立即广播（或在 DeferredActorBroadcasts 事务 commit 时批量 flush）
- 前端收到 `actor-sync-broadcast` → 转发给 peers

渐进式 `incremental_import` 里每导入一个 actor，它的 `__init__` 就会调
`_broadcast_actor_created`，**自动广播出去**——host 分层节奏 = peer 到达节奏，
**渐进传输几乎免费**（突击方案 §3.1 判断正确）。

## 验证 2：⟦RISK:cjk-path-P0⟧ 中文模型路径 FILE_REQUEST 打不开 ⚠️

**Bug 位置**：`include/corona/systems/network/file_transfer.h:15`
```cpp
std::filesystem::path rel(relative_path);  // ← std::string 按当前 locale（GBK）解码
```
Windows 上 `std::filesystem::path(std::string)` 按 GBK 解码，导致 UTF-8 中文字节被误解。
peer 请求中文路径模型时，host 打不开文件（路径乱码）。

**正式修法（需重编译引擎）**：
```cpp
// C++17
auto rel = std::filesystem::u8path(relative_path);
// 或 C++20
std::filesystem::path rel(std::u8string_view(
    reinterpret_cast<const char8_t*>(relative_path.data()),
    relative_path.size()
));
```

**Demo 临时绕法（突击方案 §3.1 已标）**：
- 生成场景时只用英文物体名（"yurt" / "table" / "cushion"）
- 或提前把中文模型路径改成拼音/英文（在 AssetPool 注册时）
- 这样 FILE_REQUEST 的 `relative_path` 是纯 ASCII，绕过 GBK/UTF-8 歧义

## 验证 3：操作同传（用户介入）

用户介入 = 改 Actor transform → actor 自己没有变换事件广播。
但 LANChat 可以在用户操作时手动广播（通过 `actor-sync-broadcast` 同样的通道）。

当前 `scene_diff.py` 在 phase 边界捕获用户介入（轮询 diff），可以在捕获到变化时
显式调用同样的广播接口，让 peers 同步看到。

简化版（demo 可接受）：phase 边界批量同步一次用户介入（不是实时，但渐进生成本就
是 phase 粒度，体感够）。

## 执行建议

COMMIT 6（LAN 同传）不需要新代码——底座已有。

需要的是：
1. **Demo 准备**：提前把场景物体名改成英文，或用拼音（绕 ⟦RISK:cjk-path-P0⟧）。
2. **F5 验收**：host 渐进生成草原蒙古包，peer 同时看到分层到达（terrain → yurt_shell
   → interior_floor → fence → cushions 逐步出现）。
3. **记录风险**：中文路径 bug 已知、有绕法、正式修需重编译（非 Python 能修）。
"""
__all__ = []
