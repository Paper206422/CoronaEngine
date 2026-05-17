#pragma once

namespace Corona::Systems::UI {

// ============================================================================
// EditorSettings - 编辑器设置数据结构
// ============================================================================

struct EditorSettings {
    // ── 工作流与提示 ──
    float cabbage_hint_time = 3.0f;   // 包菜提示时间 (秒)
    int autosave_interval = 15;       // 自动存档间隔 (分钟)

    // ── 引擎与图形 ──
    bool vsync = true;                // 垂直同步
    float camera_speed = 2.5f;       // 编辑器相机移动速度
    float grid_snap_size = 50.0f;     // 网格对齐大小

    // ── 音频 ──
    float master_volume = 0.8f;      // 主音量
    float sfx_volume = 1.0f;         // 音效音量
    float bgm_volume = 0.7f;         // 背景音乐音量

    // ── 外观 ──
    int theme_index = 0;             // UI 主题: 0=暗色, 1=亮色, 2=古典
    int language_index = 0;          // 界面语言: 0=中文, 1=English
    float ui_scale = 1.0f;           // UI 缩放

    // ── 运行时状态 ──
    float autosave_accumulator = 0.0f; // 自动存档计时器 (秒)
};

// ============================================================================
// 渲染设置面板 (Dockable Window)
// ============================================================================

bool RenderSettingsPanel(EditorSettings& settings, bool* p_open = nullptr);

void TriggerAutoSavePlaceholder();

}  // namespace Corona::Systems::UI
