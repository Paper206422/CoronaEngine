# 修复用户上传图像 file:// URL 泄漏到 Agent 历史的问题

## 问题描述

用户上传图像时，原始的本地 `file://` URL 被泄漏到 Agent 的会话历史中，违反了"Agent 内部只使用 `fileid://` 引用"的设计原则。

## 问题根源

1. **原地修改问题**：在 `interface.py` 第 68 行，直接修改了原始 `part["content_url"]`，将其从 `file://` 替换为 `fileid://`
2. **引用传递**：修改后的 `part` 对象被传入 `wrap_part_as_tool_message()`，创建的 ToolMessage 会被添加到历史记录中
3. **废弃代码残留**：`USE_ARTIFICIAL_TOOL_FOR_MEDIA=False` 分支代码仍然存在，且直接使用 `file_url_to_data_uri()` 处理可能包含原始 URL 的 part

## 解决方案

### 1. 创建 Part 副本而非原地修改

```python
# 修改前（原地修改，污染原始数据）
for part, file_id in zip(uploaded_media_parts, file_ids):
    part["content_url"] = f"fileid://{file_id}"  # ❌ 原地修改
    tool_msg = wrap_part_as_tool_message(part, session_id)

# 修改后（创建干净的副本）
for part, file_id in zip(uploaded_media_parts, file_ids):
    # 创建干净的 part 副本，只包含 fileid:// URL
    clean_part = {
        "content_type": part.get("content_type"),
        "content_url": f"fileid://{file_id}",  # ✅ 只包含 fileid://
        "content_text": part.get("content_text", ""),
    }
    if "parameter" in part:
        clean_part["parameter"] = part["parameter"]
    
    tool_msg = wrap_part_as_tool_message(clean_part, session_id)
```

### 2. 移除废弃的 USE_ARTIFICIAL_TOOL_FOR_MEDIA 相关代码

- 从 `interface.py` 移除 `USE_ARTIFICIAL_TOOL_FOR_MEDIA` 和 `file_url_to_data_uri` 导入
- 从 `integrated.py` 移除相同的导入和废弃分支
- 从 `protocol.py` 移除 `USE_ARTIFICIAL_TOOL_FOR_MEDIA` 常量定义
- 更新 `protocol.py` 的 `__all__` 导出列表

## 修改文件

1. **Backend/Quasar/agent/interface.py**
   - 移除废弃导入
   - 修改媒体收集逻辑：保持原始 part 不变
   - 创建 clean_part 副本用于构造 ToolMessage

2. **Backend/Quasar/service/integrated.py**
   - 移除废弃导入
   - 应用相同的 clean_part 创建逻辑

3. **Backend/Quasar/agent/protocol.py**
   - 移除 `USE_ARTIFICIAL_TOOL_FOR_MEDIA` 常量定义
   - 更新 `__all__` 导出列表

## 验证

创建了测试脚本 `test_media_url_fix.py`，验证：

1. ✅ 原始 part 不被修改
2. ✅ clean_part 只包含 `fileid://` URL
3. ✅ ToolMessage 内容不包含 `file://` URL
4. ✅ 历史记录中只有 `fileid://` 引用

所有测试通过。

## 设计原则确认

- **Agent 上下文隔离**：Agent 的历史记录和消息中永远不包含真实的 `file://` URL
- **延迟解析**：只在返回客户端或调用上游 API 时才通过 `media_registry.resolve()` 解析 `fileid://` 为真实 URL
- **数据不变性**：输入的原始数据保持不变，所有转换都基于副本进行

## 影响范围

- ✅ 用户上传图像/视频/音频的流程
- ✅ 会话历史存储
- ✅ Agent 内部消息传递
- ⚠️ 工具生成的媒体资源（已通过 `submit()` 注册，使用 `fileid://`，无影响）

## 后续建议

1. 考虑在 `MediaRecord.to_part()` 中添加参数控制是否返回 `fileid://` 或真实 URL
2. 定期审查是否有其他代码路径可能泄漏真实 URL
3. 考虑在 `wrap_part_as_tool_message()` 中添加 URL 格式验证，拒绝 `file://` URL
