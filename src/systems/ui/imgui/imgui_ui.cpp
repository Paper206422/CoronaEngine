#include "imgui_ui.h"

#include <corona/kernel/core/i_logger.h>
#include <corona/systems/ui/vulkan_backend.h>
#include <imgui_impl_sdl3.h>

#include "cef/browser_manager.h"
#include "cef/cef_client.h"

namespace Corona::Systems::UI {

// ============================================================================
// SDL/ImGui 生命周期管理
// ============================================================================

bool initialize_sdl_imgui(SDL_Window*& window, ImGuiIO*& io, std::unique_ptr<VulkanBackend>& vulkan_backend) {
    if (!SDL_Init(SDL_INIT_VIDEO)) {
        CFW_LOG_ERROR("Failed to initialize SDL: {}", SDL_GetError());
        return false;
    }

    SDL_SetHint(SDL_HINT_VIDEO_X11_NET_WM_BYPASS_COMPOSITOR, "0");

    // 获取当前桌面分辨率，并为 SDL 窗口标题栏预留高度（估计值）
    int initial_width = 1920;
    int initial_height = 1080;
    // SDL3: SDL_GetDesktopDisplayMode 接受一个 SDL_DisplayID
    const int kTitlebarEstimate = 80;  // 估计的标题栏高度（像素）
    SDL_DisplayID primary_display = SDL_GetPrimaryDisplay();
    const SDL_DisplayMode* desktop_mode = nullptr;
    if (primary_display != 0) {
        desktop_mode = SDL_GetDesktopDisplayMode(primary_display);
    }

    if (desktop_mode) {
        initial_width = desktop_mode->w * 0.8;
        initial_height = desktop_mode->h * 0.8;
    }

    window = SDL_CreateWindow("Corona Engine (Horizon)", initial_width, initial_height, SDL_WINDOW_RESIZABLE | SDL_WINDOW_HIDDEN);
    if (window == nullptr) {
        CFW_LOG_ERROR("Failed to create window: {}", SDL_GetError());
        SDL_Quit();
        return false;
    }

    SDL_SetWindowPosition(window, SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED);
    // SDL_ShowWindow(window);
    SDL_StartTextInput(window);
    // SDL_MaximizeWindow(window);
    SDL_SetHint(SDL_HINT_IME_IMPLEMENTED_UI, "1");
    BrowserManager::instance().set_main_window(window);

    vulkan_backend = std::make_unique<VulkanBackend>(window);
    if (!vulkan_backend->initialize()) {
        CFW_LOG_ERROR("Failed to initialize Cabbage UI backend");
        SDL_DestroyWindow(window);
        window = nullptr;
        SDL_Quit();
        return false;
    }

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    io = &ImGui::GetIO();
    io->ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    io->ConfigFlags |= ImGuiConfigFlags_DockingEnable;
    io->ConfigFlags |= ImGuiConfigFlags_ViewportsEnable;

    // TODO: 明确这是自定义 renderer，并禁用未实现的 RendererHasTextures 路径
    // 确保字体图集在首帧前已建立，避免 atlas->Builder 为 nullptr
    // 不熟看你们怎么改
    io->BackendRendererName = "Corona.Horizon";
    io->BackendFlags &= ~ImGuiBackendFlags_RendererHasTextures;

    io->Fonts->AddFontDefault();

    // 加载中文字体（微软雅黑），合并到默认字体图集中
    {
        ImFontConfig cfg;
        cfg.MergeMode = true;
        cfg.OversampleH = 2;
        cfg.OversampleV = 2;
        static const ImWchar cjk_ranges[] = {
            0x0020, 0x00FF,   // Basic Latin + Latin Supplement
            0x2000, 0x206F,   // General Punctuation
            0x3000, 0x30FF,   // CJK Symbols and Punctuations, Hiragana, Katakana
            0x31F0, 0x31FF,   // Katakana Phonetic Extensions
            0xFF00, 0xFFEF,   // Half-width characters
            0x4E00, 0x9FFF,   // CJK Unified Ideographs
            0,
        };
        const char* cjk_fonts[] = {
            "C:\\Windows\\Fonts\\msyh.ttc",   // 微软雅黑 Win10+
            "C:\\Windows\\Fonts\\simhei.ttf", // 黑体（备选）
            "C:\\Windows\\Fonts\\simsun.ttc", // 宋体（备选）
        };
        bool loaded = false;
        for (const char* path : cjk_fonts) {
            if (ImFont* f = io->Fonts->AddFontFromFileTTF(path, 18.0f, &cfg, cjk_ranges)) {
                loaded = true;
                break;
            }
        }
        if (!loaded) {
            CFW_LOG_WARNING("Failed to load any CJK font, Chinese text may display as '?'");
        }
    }

    io->Fonts->Build();

    ImGui::StyleColorsDark();
    ImGuiStyle& style = ImGui::GetStyle();
    style.Colors[ImGuiCol_WindowBg] = ImVec4(0.0f, 0.0f, 0.0f, 0.0f);
    style.Colors[ImGuiCol_DockingEmptyBg] = ImVec4(0.0f, 0.0f, 0.0f, 0.0f);
    style.Colors[ImGuiCol_DockingPreview] = ImVec4(0.2f, 0.2f, 0.8f, 0.3f);
    style.WindowRounding = 1.0f;
    style.WindowBorderSize = 1.0f;
    style.WindowPadding = ImVec2(1.0f, 1.0f);

    /*ImGui_ImplSDL3_InitForVulkan(window);

    ImGui_ImplVulkan_InitInfo init_info = {};
    init_info.Instance = vulkan_backend->get_instance();
    init_info.PhysicalDevice = vulkan_backend->get_physical_device();
    init_info.Device = vulkan_backend->get_device();
    init_info.QueueFamily = vulkan_backend->get_queue_family();
    init_info.Queue = vulkan_backend->get_queue();
    init_info.DescriptorPool = vulkan_backend->get_descriptor_pool();
    init_info.PipelineInfoMain.RenderPass = vulkan_backend->get_render_pass();
    init_info.MinImageCount = vulkan_backend->get_min_image_count();
    init_info.ImageCount = vulkan_backend->get_image_count();
    init_info.PipelineInfoMain.MSAASamples = VK_SAMPLE_COUNT_1_BIT;
    init_info.UseDynamicRendering = false;

    ImGui_ImplVulkan_Init(&init_info);*/

    ImGui_ImplSDL3_InitForOther(window);

    // Register renderer viewport callbacks now that ImGui context and SDL3 platform are ready.
    vulkan_backend->register_viewport_callbacks();

    return true;
}

void shutdown_sdl_imgui(SDL_Window*& window, ImGuiIO*& io, std::unique_ptr<VulkanBackend>& vulkan_backend) {
    ImGui_ImplSDL3_Shutdown();
    ImGui::DestroyContext();

    if (vulkan_backend) {
        vulkan_backend->shutdown();
        vulkan_backend.reset();
        // BrowserManager::instance().set_vulkan_backend(nullptr);
    }

    if (window) {
        SDL_DestroyWindow(window);
        window = nullptr;
    }

    SDL_StopTextInput(window);
    SDL_Quit();

    io = nullptr;
}

// ============================================================================
// UiLayoutManager 实现
// ============================================================================

ImGuiID UiLayoutManager::setup_dockspace() {
    ImGuiViewport* viewport = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(viewport->WorkPos);
    ImGui::SetNextWindowSize(viewport->WorkSize);
    ImGui::SetNextWindowViewport(viewport->ID);

    ImGuiWindowFlags window_flags = ImGuiWindowFlags_NoDocking |
                                    ImGuiWindowFlags_NoTitleBar |
                                    ImGuiWindowFlags_NoCollapse |
                                    ImGuiWindowFlags_NoResize |
                                    ImGuiWindowFlags_NoMove |
                                    ImGuiWindowFlags_NoBringToFrontOnFocus |
                                    ImGuiWindowFlags_NoNavFocus |
                                    ImGuiWindowFlags_NoBackground;

    ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding, 0.0f);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize, 0.0f);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(0.0f, 0.0f));

    ImGui::PushStyleColor(ImGuiCol_WindowBg, ImVec4(0.0f, 0.0f, 0.0f, 0.0f));
    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImVec4(0.0f, 0.0f, 0.0f, 0.0f));
    ImGui::PushStyleColor(ImGuiCol_DockingEmptyBg, ImVec4(0.0f, 0.0f, 0.0f, 0.0f));

    ImGui::Begin("DockSpace", nullptr, window_flags);

    ImGui::PopStyleVar(3);
    ImGui::PopStyleColor(3);

    ImGuiID dock_space_id = ImGui::GetID("MyDockSpace");
    ImGui::DockSpace(dock_space_id, ImVec2(0.0f, 0.0f), ImGuiDockNodeFlags_PassthruCentralNode | ImGuiDockNodeFlags_AutoHideTabBar);

    dockspace_active_ = true;

    return dock_space_id;
}

void UiLayoutManager::end_dockspace() {
    if (dockspace_active_) {
        ImGui::End();
        dockspace_active_ = false;
    }
}

// ============================================================================
// UiFrameRunner 实现
// ============================================================================

void UiFrameRunner::run_frame(UiFrameContext& context) {
    if (!context.running || !context.active_tab_id || !context.vulkan_backend) {
        return;
    }

    auto result = event_handler_.process_events(context.window, url_input_active_tab_, [&](const SDL_Event& e) { input_handler_.process_sdl_key_event(e); }, [&](const SDL_Event& e) { input_handler_.process_sdl_text_event(e); }, [&](const SDL_Event& e) { input_handler_.process_sdl_ime_event(e); });

    if (result.should_quit) {
        *context.running = false;
    }

    if (result.window_resized && context.window && context.window_size_changed) {
        *context.window_size_changed = true;
        context.vulkan_backend->request_rebuild();
    }

    if (context.vulkan_backend->is_rebuild_needed()) {
        int width = 0;
        int height = 0;
        SDL_GetWindowSize(context.window, &width, &height);
        context.vulkan_backend->rebuild(width, height);
    }

    context.vulkan_backend->new_frame();
    ImGui_ImplSDL3_NewFrame();

    // Ensure RendererHasTextures stays disabled — our custom renderer does not
    // implement the ImGui texture management API (font atlas is manual).
    if (context.io) {
        context.io->BackendFlags &= ~ImGuiBackendFlags_RendererHasTextures;
    }

    ImGui::NewFrame();

    // ESC 快捷键：打开/关闭 Vue 编辑器设置页面
    if (ImGui::IsKeyPressed(ImGuiKey_Escape) && !ImGui::IsPopupOpen(nullptr, ImGuiPopupFlags_AnyPopupId)) {
        auto& mgr = BrowserManager::instance();
        if (settings_tab_id_ == -1 || mgr.get_tab(settings_tab_id_) == nullptr) {
            // 直接加载源目录中的 Vue 页面，无需复制
            std::string abs_path = CORONA_SETTINGS_HTML_PATH;
            std::string file_url = "file://";
            for (char c : abs_path) {
                if (c == '\\') file_url += '/';
                else file_url += c;
            }
            settings_tab_id_ = mgr.create_tab(file_url, "", "right_top", 420, 650, false);
            CFW_LOG_INFO("[ESC] Created settings tab: id={} url={}", settings_tab_id_, file_url);
        } else {
            BrowserTab* tab = mgr.get_tab(settings_tab_id_);
            if (tab->minimized) {
                mgr.show_tab(settings_tab_id_);
            } else {
                mgr.hide_tab(settings_tab_id_);
            }
        }
    }

    // 自动存档计时器累加
    editor_settings_.autosave_accumulator += context.delta_time;
    if (editor_settings_.autosave_accumulator >= editor_settings_.autosave_interval * 60.0f) {
        editor_settings_.autosave_accumulator = 0.0f;
        TriggerAutoSavePlaceholder();
    }

    ImGuiID dock_space_id = layout_manager_.setup_dockspace();

    std::vector<int> tabs_to_close = browser_renderer_.render_browser_tabs(dock_space_id, *context.active_tab_id, url_input_active_tab_, context.io);

    layout_manager_.end_dockspace();

    if (*context.active_tab_id != -1 && url_input_active_tab_ == -1) {
        auto* tab = BrowserManager::instance().get_tab(*context.active_tab_id);
        if (tab && tab->client && tab->client->GetBrowser()) {
            input_handler_.send_key_events_to_browser(tab->client->GetBrowser());
        } else {
            input_handler_.clear_pending_events();
        }
    } else {
        input_handler_.clear_pending_events();
    }

    for (auto tab_id : tabs_to_close) {
        BrowserManager::instance().remove_tab(tab_id);
        if (tab_id == *context.active_tab_id) {
            *context.active_tab_id = -1;
        }
        if (tab_id == url_input_active_tab_) {
            url_input_active_tab_ = -1;
        }
        if (tab_id == settings_tab_id_) {
            settings_tab_id_ = -1;
        }
    }

    ImGui::Render();
    ImDrawData* draw_data = ImGui::GetDrawData();
    const bool is_minimized = (draw_data->DisplaySize.x <= 0.0f || draw_data->DisplaySize.y <= 0.0f);
    if (!is_minimized) {
        context.vulkan_backend->render_frame(draw_data);
        context.vulkan_backend->present_frame();
    }

    if (context.io && (context.io->ConfigFlags & ImGuiConfigFlags_ViewportsEnable)) {
        ImGui::UpdatePlatformWindows();
        ImGui::RenderPlatformWindowsDefault();
    }
}

}  // namespace Corona::Systems::UI