#include <corona/systems/ui/vulkan_backend.h>

#include <algorithm>
#include <cstdint>
#include <mutex>
#include <utility>

#include "cef/browser_manager.h"
#include "cef/cef_client.h"

namespace Corona::Systems::UI {
namespace {
constexpr uint64_t kDeferredTextureDestroyFrames = 4;
}

void BrowserManager::destroy_tab_texture(BrowserTab* tab) {
    if (!tab || !is_valid_texture_id(tab->texture_id)) {
        return;
    }

    const ImTextureID texture_id = tab->texture_id;
    tab->texture_id = k_invalid_texture_id;

    texture_executor_.waitForDeferredResources();
    auto it = owned_images_.find(texture_id);
    if (it != owned_images_.end()) {
        deferred_texture_destroys_.push_back(
            DeferredTextureDestroy{std::move(it->second), frame_index_});
        owned_images_.erase(texture_id);
    }
}

void BrowserManager::retire_deferred_tab_textures(bool force) {
    if (deferred_texture_destroys_.empty()) {
        return;
    }

    texture_executor_.waitForDeferredResources();
    std::erase_if(
        deferred_texture_destroys_,
        [this, force](const DeferredTextureDestroy& pending) {
            return force ||
                   frame_index_ >= pending.queued_frame + kDeferredTextureDestroyFrames;
        });
}

ImTextureID BrowserManager::create_browser_texture(int width, int height) {
    const uint32_t safe_width = static_cast<uint32_t>(std::max(width, 1));
    const uint32_t safe_height = static_cast<uint32_t>(std::max(height, 1));

    OwnedImage owned{};
    owned.image = HardwareImage(safe_width, safe_height, ImageFormat::RGBA8_UNORM, ImageUsage::SampledImage);
    if (!owned.image) {
        return k_invalid_texture_id;
    }

    owned.width = safe_width;
    owned.height = safe_height;

    const uint32_t descriptor = owned.image.storeDescriptor();
    if (descriptor == 0) {
        return k_invalid_texture_id;
    }
    const ImTextureID texture_id = static_cast<ImTextureID>(descriptor);

    owned_images_[texture_id] = std::move(owned);
    return texture_id;
}

void BrowserManager::update_texture(int tab_id) {
    auto it = tabs_.find(tab_id);
    if (it == tabs_.end()) {
        return;
    }

    BrowserTab* tab = it->second.get();

    std::vector<uint8_t> pixels;
    ImTextureID texture_id = k_invalid_texture_id;

    {
        std::unique_lock<std::mutex> lock(tab->mutex);
        if (!(tab->buffer_dirty && !tab->pixel_buffer.empty() && is_valid_texture_id(tab->texture_id))) {
            return;
        }

        texture_id = tab->texture_id;
        pixels.swap(tab->pixel_buffer);
        tab->buffer_dirty = false;
    }

    auto image_it = owned_images_.find(texture_id);
    if (image_it == owned_images_.end()) {
        return;
    }

    constexpr size_t kRgbaBytesPerPixel = 4;
    const size_t expected_size =
        static_cast<size_t>(image_it->second.width) *
        static_cast<size_t>(image_it->second.height) *
        kRgbaBytesPerPixel;

    if (pixels.size() >= expected_size) {
        texture_executor_ << image_it->second.image.copyFrom(pixels.data())
                          << texture_executor_.commit();
    }
}

void BrowserManager::wait_for_texture_uploads(HardwareExecutor& consumer) {
    consumer.wait(texture_executor_);
}

void BrowserManager::resize_tab(int tab_id, int width, int height) {
    auto it = tabs_.find(tab_id);
    if (it == tabs_.end()) {
        return;
    }

    BrowserTab* tab = it->second.get();
    if (width <= 0 || height <= 0) {
        return;
    }
    if (width == tab->width && height == tab->height) {
        return;
    }

    tab->width = width;
    tab->height = height;

    destroy_tab_texture(tab);
    tab->texture_id = create_browser_texture(tab->width, tab->height);

    if (tab->client) {
        tab->client->Resize(tab->width, tab->height);
    }
}
}  // namespace Corona::Systems::UI
