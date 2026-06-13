#pragma once

#include <memory>

#include "../event/i_event_bus.h"
#include "../event/i_event_stream.h"
#include "../system/i_system_manager.h"

namespace Corona::Kernel {

class KernelContext {
   public:
    static KernelContext& instance();

    bool initialize();
    void shutdown();

    IEventBus* event_bus() const { return event_bus_.get(); }
    IEventBusStream* event_stream() const { return event_stream_.get(); }
    ISystemManager* system_manager() const { return system_manager_.get(); }

   private:
    KernelContext() = default;
    ~KernelContext() = default;

    KernelContext(const KernelContext&) = delete;
    KernelContext& operator=(const KernelContext&) = delete;
    KernelContext(KernelContext&&) = delete;
    KernelContext& operator=(KernelContext&&) = delete;

    std::unique_ptr<IEventBus> event_bus_;
    std::unique_ptr<IEventBusStream> event_stream_;
    std::unique_ptr<ISystemManager> system_manager_;
    bool initialized_ = false;
};

}  // namespace Corona::Kernel
