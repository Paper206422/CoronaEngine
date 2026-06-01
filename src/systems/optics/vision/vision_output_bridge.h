#pragma once

// Vision output bridge - converts Vision FrameBuffer float4 data to RGBA16F HardwareImage.
// Only compiled when CORONA_ENABLE_VISION is defined.

#ifdef CORONA_ENABLE_VISION

#include <Horizon.h>

#include <cstdint>

namespace Corona::Systems::Vision {

class VisionOutputBridge {
public:
    // Upload float4 RGBA32F pixel data to a RGBA16F HardwareImage via executor.
    // Recreates out_image only when it is null or when the requested dimensions
    // differ from the caller-tracked last_width/last_height. Tracking state is
    // owned by the caller (not a function-local static) so distinct output images
    // never share size state and a resolution change can never silently rebuild a
    // shared image that another system is still referencing.
    // The copy command is submitted to executor immediately.
    static bool upload_to_hardware_image(
        const float* rgba32f_data,
        uint32_t width,
        uint32_t height,
        HardwareImage& out_image,
        HardwareExecutor& executor,
        uint32_t& last_width,
        uint32_t& last_height);

    // IEEE 754 float32 to float16 conversion helper.
    static uint16_t float_to_half(float f);
};

}  // namespace Corona::Systems::Vision

#endif  // CORONA_ENABLE_VISION
