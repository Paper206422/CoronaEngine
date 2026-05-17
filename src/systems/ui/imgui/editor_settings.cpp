#include "editor_settings.h"

#include <corona/kernel/core/i_logger.h>
#include <imgui.h>

namespace Corona::Systems::UI {

void TriggerAutoSavePlaceholder() {
    CFW_LOG_INFO("[自动存档] 已触发 (占位符)");
}

bool RenderSettingsPanel(EditorSettings& s, bool* p_open) {
    if (p_open && !*p_open) return false;

    // 柔和背景色
    ImGui::PushStyleColor(ImGuiCol_WindowBg, ImVec4(0.12f, 0.13f, 0.16f, 0.96f));
    ImGui::PushStyleColor(ImGuiCol_Header, ImVec4(0.20f, 0.22f, 0.28f, 0.60f));
    ImGui::PushStyleColor(ImGuiCol_HeaderHovered, ImVec4(0.26f, 0.28f, 0.36f, 0.70f));
    ImGui::PushStyleColor(ImGuiCol_HeaderActive, ImVec4(0.22f, 0.24f, 0.30f, 0.80f));
    ImGui::PushStyleColor(ImGuiCol_FrameBg, ImVec4(0.18f, 0.19f, 0.22f, 0.70f));
    ImGui::PushStyleColor(ImGuiCol_FrameBgHovered, ImVec4(0.24f, 0.26f, 0.32f, 0.80f));
    ImGui::PushStyleColor(ImGuiCol_FrameBgActive, ImVec4(0.22f, 0.24f, 0.30f, 0.90f));
    ImGui::PushStyleColor(ImGuiCol_SliderGrab, ImVec4(0.32f, 0.36f, 0.48f, 0.80f));
    ImGui::PushStyleColor(ImGuiCol_SliderGrabActive, ImVec4(0.40f, 0.44f, 0.58f, 0.90f));
    ImGui::PushStyleColor(ImGuiCol_Button, ImVec4(0.22f, 0.24f, 0.30f, 0.70f));
    ImGui::PushStyleColor(ImGuiCol_ButtonHovered, ImVec4(0.28f, 0.30f, 0.38f, 0.80f));
    ImGui::PushStyleColor(ImGuiCol_CheckMark, ImVec4(0.40f, 0.55f, 0.80f, 1.00f));
    ImGui::PushStyleColor(ImGuiCol_Separator, ImVec4(0.22f, 0.24f, 0.30f, 0.60f));
    ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(0.82f, 0.84f, 0.90f, 1.00f));
    ImGui::PushStyleColor(ImGuiCol_TextDisabled, ImVec4(0.48f, 0.50f, 0.56f, 1.00f));

    ImGuiWindowFlags flags = ImGuiWindowFlags_None;
    if (!ImGui::Begin("编辑器设置", p_open, flags)) {
        ImGui::PopStyleColor(15);
        ImGui::End();
        return false;
    }

    // ========================================================================
    // 工作流与提示
    // ========================================================================
    if (ImGui::CollapsingHeader("工作流与提示", ImGuiTreeNodeFlags_DefaultOpen)) {

        ImGui::Text("包菜提示时间");
        ImGui::SetNextItemWidth(200.0f);
        ImGui::SliderFloat("##CabbageHintTime", &s.cabbage_hint_time, 0.5f, 10.0f, "%.1f 秒");

        ImGui::Spacing();
        ImGui::Text("自动存档间隔");
        ImGui::SetNextItemWidth(200.0f);
        ImGui::SliderInt("##AutoSaveInterval", &s.autosave_interval, 1, 60, "%d 分钟");

        float remaining = s.autosave_interval * 60.0f - s.autosave_accumulator;
        if (remaining < 0.0f) remaining = 0.0f;
        ImGui::SameLine();
        ImGui::TextDisabled("(下次存档: %.0f 秒)", remaining);
    }

    ImGui::Spacing();

    // ========================================================================
    // 引擎与图形
    // ========================================================================
    if (ImGui::CollapsingHeader("引擎与图形", ImGuiTreeNodeFlags_DefaultOpen)) {

        if (ImGui::Checkbox("垂直同步", &s.vsync)) {
            // TODO: 同步到 VulkanBackend 的 present mode
        }

        ImGui::Spacing();
        ImGui::Text("相机速度");
        ImGui::SetNextItemWidth(200.0f);
        ImGui::SliderFloat("##CameraSpeed", &s.camera_speed, 0.1f, 10.0f, "%.1f");

        ImGui::Spacing();
        ImGui::Text("网格对齐");
        ImGui::SetNextItemWidth(200.0f);
        ImGui::SliderFloat("##GridSnapSize", &s.grid_snap_size, 1.0f, 200.0f, "%.0f");
    }

    ImGui::Spacing();

    // ========================================================================
    // 音频
    // ========================================================================
    if (ImGui::CollapsingHeader("音频", ImGuiTreeNodeFlags_DefaultOpen)) {

        ImGui::Text("主音量");
        ImGui::SetNextItemWidth(200.0f);
        ImGui::SliderFloat("##MasterVolume", &s.master_volume, 0.0f, 1.0f, "%.0f%%");

        ImGui::Spacing();
        ImGui::Text("背景音乐");
        ImGui::SetNextItemWidth(200.0f);
        ImGui::SliderFloat("##BGMVolume", &s.bgm_volume, 0.0f, 1.0f, "%.0f%%");

        ImGui::Spacing();
        ImGui::Text("效果音");
        ImGui::SetNextItemWidth(200.0f);
        ImGui::SliderFloat("##SFXVolume", &s.sfx_volume, 0.0f, 1.0f, "%.0f%%");
    }

    ImGui::Spacing();

    // ========================================================================
    // 外观
    // ========================================================================
    if (ImGui::CollapsingHeader("外观", ImGuiTreeNodeFlags_DefaultOpen)) {

        ImGui::Text("界面主题");
        ImGui::SameLine();
        ImGui::SetNextItemWidth(160.0f);
        const char* themes[] = {"暗色", "亮色", "古典"};
        if (ImGui::Combo("##ThemeCombo", &s.theme_index, themes, IM_ARRAYSIZE(themes))) {
            switch (s.theme_index) {
                case 0: ImGui::StyleColorsDark(); break;
                case 1: ImGui::StyleColorsLight(); break;
                case 2: ImGui::StyleColorsClassic(); break;
            }
        }

        ImGui::Spacing();
        ImGui::Text("界面语言");
        ImGui::SameLine();
        ImGui::SetNextItemWidth(160.0f);
        const char* languages[] = {"中文", "English"};
        ImGui::Combo("##LanguageCombo", &s.language_index, languages, IM_ARRAYSIZE(languages));

        ImGui::Spacing();
        ImGui::Text("UI 缩放");
        ImGui::SameLine();
        ImGui::SetNextItemWidth(200.0f);
        ImGui::SliderFloat("##UIScale", &s.ui_scale, 0.5f, 2.0f, "%.1fx");
    }

    ImGui::PopStyleColor(15);
    ImGui::End();
    return false;
}

}  // namespace Corona::Systems::UI
