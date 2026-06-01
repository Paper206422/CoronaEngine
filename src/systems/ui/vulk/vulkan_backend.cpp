#include <corona/events/display_system_events.h>
#include <corona/kernel/core/i_logger.h>
#include <corona/kernel/core/kernel_context.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/shared_data_hub.h>
#include <corona/systems/script/corona_engine_api.h>
#include <corona/systems/ui/vulkan_backend.h>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <type_traits>
#include <vector>

namespace {
struct ImGuiGpuVertex {
    float pos[2]{};
    float uv[2]{};
    float color[4]{};
};

inline ktm::fvec4 unpack_imgui_color(const ImU32 color) {
    constexpr float kInv255 = 1.0f / 255.0f;
    const float r = static_cast<float>((color >> IM_COL32_R_SHIFT) & 0xFFu) * kInv255;
    const float g = static_cast<float>((color >> IM_COL32_G_SHIFT) & 0xFFu) * kInv255;
    const float b = static_cast<float>((color >> IM_COL32_B_SHIFT) & 0xFFu) * kInv255;
    const float a = static_cast<float>((color >> IM_COL32_A_SHIFT) & 0xFFu) * kInv255;
    return ktm::fvec4(r, g, b, a);
}

inline uint32_t texture_id_to_descriptor(ImTextureID tex_id) {
    const ImU64 raw = static_cast<ImU64>(tex_id);
    if (raw > static_cast<ImU64>(std::numeric_limits<uint32_t>::max())) {
        CFW_LOG_ERROR("VulkanBackend: ImTextureID out of uint32 range: {}", raw);
    }
    return static_cast<uint32_t>(raw);
}
}  // namespace

namespace Corona::Systems {

// Per-secondary-viewport data stored in ImGuiViewport::RendererUserData.
struct ViewportData {
    HardwareDisplayer displayer;                                    // per-window swapchain/presentation
    ViewportRenderResources resources;                              // per-window render target + geometry buffers
    RasterizerPipeline<imgui_vert_glsl, imgui_frag_glsl> pipeline;  // independent pipeline instance
    bool pipeline_ready = false;
    bool pending_show = false;  // deferred show: wait until first frame is rendered
};

// Deferred Platform_ShowWindow: intercept to delay OS window visibility until after the
// first Renderer_SwapBuffers, eliminating the 1-frame white/black flash on dock-out.
static void (*s_original_platform_show_window)(ImGuiViewport*) = nullptr;

static void deferred_platform_show_window(ImGuiViewport* vp) {
    if (auto* vd = static_cast<ViewportData*>(vp->RendererUserData)) {
        vd->pending_show = true;  // defer until after first swap
    } else if (s_original_platform_show_window) {
        s_original_platform_show_window(vp);  // main viewport: show immediately
    }
}

VulkanBackend* VulkanBackend::s_instance_ = nullptr;

VulkanBackend::VulkanBackend(SDL_Window* window)
    : window_(window) {
}

bool VulkanBackend::initialize() {
    if (initialized_) {
        return true;
    }

    if (window_ == nullptr) {
        CFW_LOG_ERROR("VulkanBackend: initialize failed, window is null");
        return false;
    }

    void* native_handle = nullptr;
#if defined(_WIN32)
    native_handle = SDL_GetPointerProperty(
        SDL_GetWindowProperties(window_),
        SDL_PROP_WINDOW_WIN32_HWND_POINTER,
        nullptr);
#elif defined(__APPLE__)
    native_handle = SDL_GetPointerProperty(
        SDL_GetWindowProperties(window_),
        SDL_PROP_WINDOW_COCOA_WINDOW_POINTER,
        nullptr);
#endif

    if (native_handle == nullptr) {
        CFW_LOG_ERROR("VulkanBackend: failed to get native window handle from SDL");
        return false;
    }

    surface_ = native_handle;
    Corona::API::set_default_surface(surface_);
    if (auto* event_bus = Kernel::KernelContext::instance().event_bus()) {
        event_bus->publish<Events::DisplaySurfaceChangedEvent>({surface_});
    }

    int w = 0;
    int h = 0;
    SDL_GetWindowSize(window_, &w, &h);

    if (w > 0 && h > 0) {
        if (!ensure_render_target(main_resources_, static_cast<uint32_t>(w), static_cast<uint32_t>(h))) {
            CFW_LOG_ERROR("VulkanBackend: failed to create initial render target");
            return false;
        }
    } else {
        rebuild_needed_ = true;
    }

    image_handle_ = SharedDataHub::instance().image_storage().allocate();
    if (auto image_device = SharedDataHub::instance().image_storage().acquire_write(image_handle_)) {
        // Keep storage entry alive; per-frame values are updated in present_frame().
    } else {
        CFW_LOG_ERROR("VulkanBackend: failed to acquire shared image storage handle");
        SharedDataHub::instance().image_storage().deallocate(image_handle_);
        image_handle_ = 0;
        return false;
    }

    initialized_ = true;
    CFW_LOG_INFO("VulkanBackend: initialized");
    return true;
}

void VulkanBackend::register_viewport_callbacks() {
    if (!initialized_) {
        CFW_LOG_ERROR("VulkanBackend: register_viewport_callbacks called before initialize");
        return;
    }

    if (ImGui::GetCurrentContext() == nullptr) {
        CFW_LOG_ERROR("VulkanBackend: register_viewport_callbacks called without ImGui context");
        return;
    }

    s_instance_ = this;

    ImGuiIO& io = ImGui::GetIO();
    io.BackendFlags |= ImGuiBackendFlags_RendererHasViewports;

    ImGuiPlatformIO& platform_io = ImGui::GetPlatformIO();
    platform_io.Renderer_CreateWindow = renderer_create_window;
    platform_io.Renderer_DestroyWindow = renderer_destroy_window;
    platform_io.Renderer_SetWindowSize = renderer_set_window_size;
    platform_io.Renderer_RenderWindow = renderer_render_window;
    platform_io.Renderer_SwapBuffers = renderer_swap_buffers;

    // Intercept Platform_ShowWindow to defer OS window visibility until first frame is presented.
    s_original_platform_show_window = platform_io.Platform_ShowWindow;
    platform_io.Platform_ShowWindow = deferred_platform_show_window;

    // Main viewport is rendered via render_frame()/present_frame(), not via callbacks.
    // Set RendererUserData to nullptr so callbacks skip it (they check for null).
    ImGuiViewport* main_vp = ImGui::GetMainViewport();
    if (main_vp != nullptr) {
        main_vp->RendererUserData = nullptr;
    }

    CFW_LOG_INFO("VulkanBackend: viewport callbacks registered (RendererHasViewports enabled)");
}

void VulkanBackend::shutdown() {
    if (!initialized_) {
        return;
    }

    // Destroy all secondary viewport data before releasing shared resources.
    if (ImGui::GetCurrentContext() != nullptr) {
        ImGui::DestroyPlatformWindows();
    }

    main_resources_.executor.waitForDeferredResources();

    main_resources_.frame_ready = false;
    imgui_pipeline_ready_ = false;
    font_ready_ = false;
    rebuild_needed_ = false;

    main_resources_.render_target = HardwareImage();
    main_resources_.executor = HardwareExecutor();
    font_atlas_image_ = HardwareImage();
    imgui_pipeline_ = RasterizerPipeline<imgui_vert_glsl, imgui_frag_glsl>();

    main_resources_.vertex_buffer = HardwareBuffer();
    main_resources_.index_buffer = HardwareBuffer();
    main_resources_.vertex_buffer_capacity = 0;
    main_resources_.index_buffer_capacity = 0;

    main_resources_.width = 0;
    main_resources_.height = 0;

    surface_ = nullptr;
    frame_index_ = 0;

    if (image_handle_ != 0) {
        SharedDataHub::instance().image_storage().deallocate(image_handle_);
        image_handle_ = 0;
    }

    initialized_ = false;
    s_instance_ = nullptr;
    CFW_LOG_INFO("VulkanBackend: shutdown");
}

void VulkanBackend::new_frame() {
    if (!initialized_) {
        return;
    }

    // GPU sync: wait for Display to finish consuming our image
    // before we clear and render new UI content into it.
    if (image_handle_ != 0) {
        if (auto image_device = SharedDataHub::instance().image_storage().acquire_write(image_handle_)) {
            main_resources_.executor.wait(image_device->consumed_executor);
        }
    }

    main_resources_.executor.cleanupDeferredResources();
}

void VulkanBackend::render_frame(ImDrawData* draw_data) {
    if (!initialized_ || draw_data == nullptr) {
        return;
    }

    if (!ensure_imgui_pipeline() || !ensure_font_texture()) {
        return;
    }

    if (render_draw_data(draw_data, main_resources_, imgui_pipeline_, font_atlas_image_)) {
        main_resources_.frame_ready = true;
    }
}

// ============================================================================
// Static reusable render function — works with any ViewportRenderResources
// ============================================================================

bool VulkanBackend::render_draw_data(
    ImDrawData* draw_data,
    ViewportRenderResources& res,
    RasterizerPipeline<imgui_vert_glsl, imgui_frag_glsl>& pipeline,
    const HardwareImage& font_atlas,
    ImageUsage render_target_usage) {
    if (draw_data == nullptr) {
        return false;
    }

    const int fb_w = static_cast<int>(draw_data->DisplaySize.x * draw_data->FramebufferScale.x);
    const int fb_h = static_cast<int>(draw_data->DisplaySize.y * draw_data->FramebufferScale.y);
    if (fb_w <= 0 || fb_h <= 0) {
        return false;
    }

    const auto fb_width = static_cast<uint32_t>(fb_w);
    const auto fb_height = static_cast<uint32_t>(fb_h);

    // --- Ensure render target ---
    if (!ensure_render_target(res, fb_width, fb_height, render_target_usage)) {
        return false;
    }

    if (draw_data->TotalVtxCount <= 0) {
        return false;
    }

    // --- Set pipeline output ---
    pipeline.out_color = res.render_target;

    // --- Merge all draw lists into single vertex/index arrays ---
    const auto total_vtx = static_cast<size_t>(draw_data->TotalVtxCount);
    const auto total_idx = static_cast<size_t>(draw_data->TotalIdxCount);

    std::vector<ImGuiGpuVertex> merged_vertices;
    merged_vertices.reserve(total_vtx);
    std::vector<ImDrawIdx> merged_indices;
    merged_indices.reserve(total_idx);

    for (int n = 0; n < draw_data->CmdListsCount; ++n) {
        const ImDrawList* cmd_list = draw_data->CmdLists[n];
        if (cmd_list == nullptr) {
            continue;
        }

        for (const ImDrawVert& v : cmd_list->VtxBuffer) {
            ImGuiGpuVertex gv{};
            gv.pos[0] = v.pos.x;
            gv.pos[1] = v.pos.y;
            gv.uv[0] = v.uv.x;
            gv.uv[1] = v.uv.y;
            const ktm::fvec4 color = unpack_imgui_color(v.col);
            gv.color[0] = color.x;
            gv.color[1] = color.y;
            gv.color[2] = color.z;
            gv.color[3] = color.w;
            merged_vertices.push_back(gv);
        }

        const auto* idx_src = cmd_list->IdxBuffer.Data;
        merged_indices.insert(merged_indices.end(), idx_src, idx_src + cmd_list->IdxBuffer.Size);
    }

    if (merged_vertices.empty() || merged_indices.empty()) {
        return false;
    }

    // --- Ensure buffer capacity, only reallocate when needed ---
    const size_t vtx_bytes = merged_vertices.size() * sizeof(ImGuiGpuVertex);
    const size_t idx_bytes = merged_indices.size() * sizeof(ImDrawIdx);

    if (!res.vertex_buffer || res.vertex_buffer_capacity < vtx_bytes) {
        const size_t new_capacity = vtx_bytes + 5000 * sizeof(ImGuiGpuVertex);
        res.vertex_buffer = HardwareBuffer(new_capacity, BufferUsage::VertexBuffer);
        res.vertex_buffer_capacity = new_capacity;
        if (!res.vertex_buffer) {
            CFW_LOG_ERROR("VulkanBackend: failed to allocate vertex buffer ({} bytes)", new_capacity);
            return false;
        }
    }

    if (!res.index_buffer || res.index_buffer_capacity < idx_bytes) {
        const size_t new_capacity = idx_bytes + 10000 * sizeof(ImDrawIdx);
        res.index_buffer = HardwareBuffer(new_capacity, BufferUsage::IndexBuffer);
        res.index_buffer_capacity = new_capacity;
        if (!res.index_buffer) {
            CFW_LOG_ERROR("VulkanBackend: failed to allocate index buffer ({} bytes)", new_capacity);
            return false;
        }
    }

    res.vertex_buffer.copyFromData(merged_vertices.data(), vtx_bytes);
    res.index_buffer.copyFromData(merged_indices.data(), idx_bytes);

    // --- Record draw commands with global offsets ---
    const float sx = 2.0f / draw_data->DisplaySize.x;
    const float sy = 2.0f / draw_data->DisplaySize.y;
    const ktm::fvec2 scale(sx, sy);
    const ktm::fvec2 translate(-1.0f - draw_data->DisplayPos.x * sx,
                               -1.0f - draw_data->DisplayPos.y * sy);

    int global_vtx_offset = 0;
    int global_idx_offset = 0;
    int recorded_draw_cmds = 0;

    for (int n = 0; n < draw_data->CmdListsCount; ++n) {
        const ImDrawList* cmd_list = draw_data->CmdLists[n];
        if (cmd_list == nullptr) {
            continue;
        }

        for (int cmd_i = 0; cmd_i < cmd_list->CmdBuffer.Size; ++cmd_i) {
            const ImDrawCmd& pcmd = cmd_list->CmdBuffer[cmd_i];

            if (pcmd.UserCallback != nullptr) {
                if (pcmd.UserCallback == ImDrawCallback_ResetRenderState) {
                    pipeline.out_color = res.render_target;
                    continue;
                }
                pcmd.UserCallback(cmd_list, &pcmd);
                continue;
            }

            ImVec2 clip_min((pcmd.ClipRect.x - draw_data->DisplayPos.x) * draw_data->FramebufferScale.x,
                            (pcmd.ClipRect.y - draw_data->DisplayPos.y) * draw_data->FramebufferScale.y);
            ImVec2 clip_max((pcmd.ClipRect.z - draw_data->DisplayPos.x) * draw_data->FramebufferScale.x,
                            (pcmd.ClipRect.w - draw_data->DisplayPos.y) * draw_data->FramebufferScale.y);

            clip_min.x = std::max(clip_min.x, 0.0f);
            clip_min.y = std::max(clip_min.y, 0.0f);
            clip_max.x = std::min(clip_max.x, static_cast<float>(fb_width));
            clip_max.y = std::min(clip_max.y, static_cast<float>(fb_height));

            if (clip_max.x <= clip_min.x || clip_max.y <= clip_min.y) {
                continue;
            }

            uint32_t texture_index = texture_id_to_descriptor(pcmd.GetTexID());
            if (texture_index == 0 && font_atlas) {
                texture_index = const_cast<HardwareImage&>(font_atlas).storeDescriptor();
            }

            pipeline.pushConsts.scale = scale;
            pipeline.pushConsts.translate = translate;
            pipeline[imgui_frag_glsl::pushConsts::clip_rect] = ktm::fvec4(
                clip_min.x, clip_min.y, clip_max.x, clip_max.y);
            pipeline[imgui_frag_glsl::pushConsts::texture_index] = texture_index;

            const int32_t scissor_x = static_cast<int32_t>(std::floor(clip_min.x));
            const int32_t scissor_y = static_cast<int32_t>(std::floor(clip_min.y));
            const int32_t scissor_w = static_cast<int32_t>(std::ceil(clip_max.x)) - scissor_x;
            const int32_t scissor_h = static_cast<int32_t>(std::ceil(clip_max.y)) - scissor_y;
            if (scissor_w <= 0 || scissor_h <= 0) {
                continue;
            }

            DrawIndexedParams draw_params;
            draw_params.indexCount = static_cast<uint32_t>(pcmd.ElemCount);
            draw_params.firstIndex = static_cast<uint32_t>(pcmd.IdxOffset + global_idx_offset);
            draw_params.vertexOffset = static_cast<int32_t>(pcmd.VtxOffset + global_vtx_offset);
            draw_params.indexType = sizeof(ImDrawIdx) == sizeof(uint16_t) ? IndexType::UInt16 : IndexType::UInt32;
            draw_params.enableScissor = true;
            draw_params.scissor = ScissorRect{
                scissor_x,
                scissor_y,
                static_cast<uint32_t>(scissor_w),
                static_cast<uint32_t>(scissor_h)};

            pipeline.record(res.index_buffer, res.vertex_buffer, draw_params);
            ++recorded_draw_cmds;
        }

        global_idx_offset += cmd_list->IdxBuffer.Size;
        global_vtx_offset += cmd_list->VtxBuffer.Size;
    }

    if (recorded_draw_cmds == 0) {
        return false;
    }

    // --- Submit ---
    res.executor << pipeline(static_cast<uint16_t>(fb_width), static_cast<uint16_t>(fb_height))
                 << res.executor.commit();

    return true;
}

void VulkanBackend::present_frame() {
    if (!initialized_ || !main_resources_.frame_ready || !main_resources_.render_target || surface_ == nullptr || image_handle_ == 0) {
        return;
    }

    if (auto image_device = SharedDataHub::instance().image_storage().acquire_write(image_handle_)) {
        image_device->image = main_resources_.render_target;
        image_device->executor = main_resources_.executor;
    } else {
        return;
    }

    if (auto* event_bus = Kernel::KernelContext::instance().event_bus()) {
        ++frame_index_;
        event_bus->publish<Events::UIFrameReadyEvent>({surface_,
                                                       image_handle_,
                                                       frame_index_,
                                                       main_resources_.width,
                                                       main_resources_.height});
    }

    main_resources_.frame_ready = false;
}

void VulkanBackend::rebuild(int width, int height) {
    if (!initialized_) {
        return;
    }

    if (width <= 0 || height <= 0) {
        return;
    }

    if (!ensure_render_target(main_resources_, static_cast<uint32_t>(width), static_cast<uint32_t>(height))) {
        rebuild_needed_ = true;
        return;
    }

    rebuild_needed_ = false;
}

bool VulkanBackend::ensure_render_target(ViewportRenderResources& resources, uint32_t width, uint32_t height,
                                         ImageUsage usage) {
    if (width == 0 || height == 0) {
        return false;
    }

    if (resources.render_target && resources.width == width && resources.height == height) {
        return true;
    }

    // RGBA8_SRGB does not support VK_FORMAT_FEATURE_STORAGE_IMAGE_BIT on many GPUs.
    // When the render target is used as a storage image (secondary viewports), use a
    // storage-capable format (RGBA16_FLOAT) to avoid VK_ERROR_FORMAT_NOT_SUPPORTED.
    const ImageFormat target_format =
        (usage == ImageUsage::StorageImage) ? ImageFormat::RGBA16_FLOAT : ImageFormat::RGBA8_SRGB;

    HardwareImage new_target(width, height, target_format, usage);
    if (!new_target) {
        CFW_LOG_ERROR("VulkanBackend: create render target failed ({}x{})", width, height);
        return false;
    }
    new_target.setClearColor(0.0f, 0.0f, 0.0f, 0.0f);
    resources.render_target = std::move(new_target);
    resources.width = width;
    resources.height = height;
    resources.frame_ready = false;

    return true;
}

bool VulkanBackend::ensure_imgui_pipeline() {
    if (imgui_pipeline_ready_) {
        return true;
    }

    imgui_pipeline_.setDepthEnabled(false);
    imgui_pipeline_ready_ = (imgui_pipeline_.getRasterizerPipelineID() != 0);

    if (imgui_pipeline_ready_) {
        CFW_LOG_INFO("VulkanBackend: typed imgui pipeline created, pipeline_id={}",
                     imgui_pipeline_.getRasterizerPipelineID());
    } else {
        CFW_LOG_ERROR("VulkanBackend: typed imgui pipeline creation returned invalid pipeline id");
    }

    return imgui_pipeline_ready_;
}

bool VulkanBackend::ensure_font_texture() {
    if (font_ready_) {
        return true;
    }

    if (ImGui::GetCurrentContext() == nullptr) {
        return false;
    }

    ImGuiIO& io = ImGui::GetIO();
    if (io.Fonts == nullptr) {
        return false;
    }

    unsigned char* pixels = nullptr;
    int width = 0;
    int height = 0;
    io.Fonts->GetTexDataAsRGBA32(&pixels, &width, &height);

    if (pixels == nullptr || width <= 0 || height <= 0) {
        CFW_LOG_ERROR("VulkanBackend: font atlas data invalid");
        return false;
    }

    font_atlas_image_ = HardwareImage(
        static_cast<uint32_t>(width),
        static_cast<uint32_t>(height),
        ImageFormat::RGBA8_SRGB,
        ImageUsage::SampledImage);

    if (!font_atlas_image_) {
        CFW_LOG_ERROR("VulkanBackend: create font atlas image failed");
        return false;
    }

    main_resources_.executor << font_atlas_image_.copyFrom(pixels) << main_resources_.executor.commit();

    const uint32_t descriptor = font_atlas_image_.storeDescriptor();
    if (descriptor == 0) {
        CFW_LOG_ERROR("VulkanBackend: font atlas descriptor is 0 (invalid)");
        return false;
    }

    io.Fonts->SetTexID(static_cast<ImTextureID>(descriptor));

    font_ready_ = true;
    CFW_LOG_INFO("VulkanBackend: font atlas uploaded ({}x{}), descriptor={}", width, height, descriptor);
    return true;
}

// ============================================================================
// Multi-Viewport renderer callbacks
// ============================================================================

void VulkanBackend::renderer_create_window(ImGuiViewport* vp) {
    if (vp == nullptr || vp->PlatformHandleRaw == nullptr) {
        CFW_LOG_ERROR("VulkanBackend: renderer_create_window called with null viewport or handle");
        return;
    }

    auto* vd = IM_NEW(ViewportData)();
    vd->displayer = HardwareDisplayer(vp->PlatformHandleRaw);

    if (vd->displayer.getDisplayerID() == 0) {
        CFW_LOG_ERROR("VulkanBackend: failed to create HardwareDisplayer for viewport {}", vp->ID);
        IM_DELETE(vd);
        return;
    }

    // Initialize per-viewport pipeline (shares compiled VkPipeline via global ID,
    // but has independent renderTargets/geomMeshesRecord state).
    vd->pipeline.setDepthEnabled(false);
    vd->pipeline_ready = (vd->pipeline.getRasterizerPipelineID() != 0);
    if (!vd->pipeline_ready) {
        CFW_LOG_ERROR("VulkanBackend: failed to create pipeline for viewport {}", vp->ID);
        IM_DELETE(vd);
        return;
    }

    vp->RendererUserData = vd;
    CFW_LOG_INFO("VulkanBackend: secondary viewport {} created (pipeline_id={})",
                 vp->ID, vd->pipeline.getRasterizerPipelineID());
}

void VulkanBackend::renderer_destroy_window(ImGuiViewport* vp) {
    if (auto* vd = static_cast<ViewportData*>(vp->RendererUserData)) {
        vd->resources.executor.waitForDeferredResources();
        IM_DELETE(vd);
    }
    vp->RendererUserData = nullptr;
}

void VulkanBackend::renderer_set_window_size(ImGuiViewport* vp, ImVec2 size) {
    auto* vd = static_cast<ViewportData*>(vp->RendererUserData);
    if (vd == nullptr) {
        return;
    }

    const auto w = static_cast<uint32_t>(size.x);
    const auto h = static_cast<uint32_t>(size.y);
    if (w > 0 && h > 0) {
        ensure_render_target(vd->resources, w, h, ImageUsage::StorageImage);
    }
}

void VulkanBackend::renderer_render_window(ImGuiViewport* vp, void* /*render_arg*/) {
    auto* vd = static_cast<ViewportData*>(vp->RendererUserData);
    if (vd == nullptr || s_instance_ == nullptr) {
        return;
    }

    ImDrawData* draw_data = vp->DrawData;
    if (draw_data == nullptr) {
        return;
    }

    const int fb_w = static_cast<int>(draw_data->DisplaySize.x * draw_data->FramebufferScale.x);
    const int fb_h = static_cast<int>(draw_data->DisplaySize.y * draw_data->FramebufferScale.y);
    if (fb_w <= 0 || fb_h <= 0) {
        return;
    }

    vd->resources.executor.cleanupDeferredResources();

    render_draw_data(draw_data, vd->resources, vd->pipeline, s_instance_->font_atlas_image_,
                     ImageUsage::StorageImage);
}

void VulkanBackend::renderer_swap_buffers(ImGuiViewport* vp, void* /*render_arg*/) {
    auto* vd = static_cast<ViewportData*>(vp->RendererUserData);
    if (vd == nullptr || !vd->resources.render_target) {
        return;
    }

    vd->displayer.wait(vd->resources.executor) << vd->resources.render_target;

    // Deferred show: make the OS window visible now that the first frame has been presented.
    if (vd->pending_show) {
        if (s_original_platform_show_window) {
            s_original_platform_show_window(vp);
        }
        vd->pending_show = false;
    }
}

}  // namespace Corona::Systems
