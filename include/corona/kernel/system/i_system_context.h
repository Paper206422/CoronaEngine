#pragma once

#include <cstdint>
#include <string_view>

namespace Corona::Kernel {

class IEventBus;
class IEventBusStream;
class ISystem;

class ISystemContext {
   public:
    virtual ~ISystemContext() = default;

    virtual IEventBus* event_bus() = 0;
    virtual IEventBusStream* event_stream() = 0;
    virtual ISystem* get_system(std::string_view name) = 0;

    virtual float get_delta_time() const = 0;
    virtual uint64_t get_frame_number() const = 0;
};

}  // namespace Corona::Kernel
