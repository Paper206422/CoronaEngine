#include "vision_output_bridge.h"

#ifdef CORONA_ENABLE_VISION

#include <cstdint>
#include <cstring>
#include <vector>

namespace Corona::Systems::Vision {

uint16_t VisionOutputBridge::float_to_half(float f) {
    uint32_t bits;
    std::memcpy(&bits, &f, sizeof(bits));
    const uint32_t sign = (bits >> 31) & 0x1;
    int32_t exponent = static_cast<int32_t>((bits >> 23) & 0xFF) - 127;
    const uint32_t mantissa = bits & 0x7FFFFF;
    uint16_t result;
    if (exponent == 128) {
        result = static_cast<uint16_t>((sign << 15) | 0x7C00 | (mantissa ? 0x200 : 0));
    } else if (exponent > 15) {
        result = static_cast<uint16_t>((sign << 15) | 0x7C00);
    } else if (exponent < -14) {
        if (exponent < -24) {
            result = static_cast<uint16_t>(sign << 15);
        } else {
            const uint32_t shift = static_cast<uint32_t>(-14 - exponent);
            const uint32_t mant16 = (0x800000 | mantissa) >> (shift + 13);
            result = static_cast<uint16_t>((sign << 15) | mant16);
        }
    } else {
        const uint16_t exp16 = static_cast<uint16_t>(exponent + 15);
        const uint16_t mant16 = static_cast<uint16_t>(mantissa >> 13);
        result = static_cast<uint16_t>((sign << 15) | (exp16 << 10) | mant16);
    }
    return result;
}

bool VisionOutputBridge::upload_to_hardware_image(
    const float* rgba32f_data,
    uint32_t width,
    uint32_t height,
    HardwareImage& out_image,
    HardwareExecutor& executor,
    uint32_t& last_width,
    uint32_t& last_height) {
    if (!rgba32f_data || width == 0 || height == 0) return false;
    const uint64_t pixel_count = static_cast<uint64_t>(width) * height;
    const uint64_t channel_count = pixel_count * 4;
    std::vector<uint16_t> half_data(channel_count);
    for (uint64_t i = 0; i < channel_count; ++i) {
        half_data[i] = float_to_half(rgba32f_data[i]);
    }

    // HardwareImage does not expose its dimensions, so the caller tracks the size
    // used to create out_image via last_width/last_height. The image must be
    // (re)created whenever it is null or when the requested dimensions differ from
    // the last created ones; otherwise copyFrom() would upload width*height*4 halfs
    // into an image of a different size, producing a black or garbled frame.
    //
    // IMPORTANT: out_image must be an image OWNED by the caller (e.g. a dedicated
    // Vision output image), never a shared image such as the display pipeline's
    // finalOutputImage. Recreating a shared image here would release the underlying
    // resource while another system still references it -> black screen.
    if (!out_image || width != last_width || height != last_height) {
        //out_image = HardwareImage(width, height, ImageFormat::RGBA16_FLOAT, ImageUsage::StorageImage);
        last_width = width;
        last_height = height;
    }
    executor << out_image.copyFrom(half_data.data())
             << executor.commit();
    return true;
}

}  // namespace Corona::Systems::Vision

#endif  // CORONA_ENABLE_VISION
