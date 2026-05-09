#include "corona/scene/desc/pipeline_desc.h"

namespace Corona::Resource::Scene {

// UpsamplerDesc 实现
UpsamplerDesc::UpsamplerDesc() : NodeDesc("Upsampler") {}

UpsamplerDesc::UpsamplerDesc(std::string name) : NodeDesc("Upsampler", std::move(name)) {}

void UpsamplerDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);
    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        sub_type = type_item->get<std::string>();
    } else {
        sub_type = "bilateral";  // 默认值
    }
    auto param_item = params.find("param");
    if (param_item != params.end() && param_item->is_object()) {
        update_parameters(*param_item);
    }
}

// ToneMapperDesc 实现
ToneMapperDesc::ToneMapperDesc() : NodeDesc("ToneMapper") {}

ToneMapperDesc::ToneMapperDesc(std::string name) : NodeDesc("ToneMapper", std::move(name)) {}

void ToneMapperDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);
    sub_type = "impl";  // 固定值
    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        construct_name = type_item->get<std::string>();
    } else {
        construct_name = "linear";  // 默认值
    }
    auto param_item = params.find("param");
    if (param_item != params.end() && param_item->is_object()) {
        update_parameters(*param_item);
    }
}

// FrameBufferDesc 实现
FrameBufferDesc::FrameBufferDesc() : NodeDesc("FrameBuffer") {}

FrameBufferDesc::FrameBufferDesc(std::string name) : NodeDesc("FrameBuffer", std::move(name)) {}

void FrameBufferDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);
    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        sub_type = type_item->get<std::string>();
    } else {
        sub_type = "normal";  // 默认值
    }
    auto param_item = params.find("param");
    if (param_item != params.end() && param_item->is_object()) {
        update_parameters(*param_item);
    }

    // 初始化 tone_mapper 和 upsampler
    tone_mapper.init(value("tone_mapper"));
    upsampler_desc.init(value("upsampler"));
}

// RasterizerDesc 实现
RasterizerDesc::RasterizerDesc() : NodeDesc("Rasterizer") {}

RasterizerDesc::RasterizerDesc(std::string name) : NodeDesc("Rasterizer", std::move(name)) {}

void RasterizerDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);
    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        sub_type = type_item->get<std::string>();
    } else {
        sub_type = "cpu";  // 默认值
    }
    auto param_item = params.find("param");
    if (param_item != params.end() && param_item->is_object()) {
        update_parameters(*param_item);
    }
}

// UVUnwrapperDesc 实现
UVUnwrapperDesc::UVUnwrapperDesc() : NodeDesc("UVUnwrapper") {}

UVUnwrapperDesc::UVUnwrapperDesc(std::string name) : NodeDesc("UVUnwrapper", std::move(name)) {}

void UVUnwrapperDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);
    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        sub_type = type_item->get<std::string>();
    } else {
        sub_type = "xatlas";  // 默认值
    }
    auto param_item = params.find("param");
    if (param_item != params.end() && param_item->is_object()) {
        update_parameters(*param_item);
    }
}

// PassDesc 实现
PassDesc::PassDesc() : NodeDesc("Pass") {}

PassDesc::PassDesc(std::string name) : NodeDesc("Pass", std::move(name)) {}

void PassDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);
    auto param_item = params.find("param");
    if (param_item != params.end() && param_item->is_object()) {
        update_parameters(*param_item);
    }
}

// PipelineDesc 实现
PipelineDesc::PipelineDesc() : NodeDesc("Pipeline") {}

PipelineDesc::PipelineDesc(std::string name) : NodeDesc("Pipeline", std::move(name)) {}

void PipelineDesc::init(const JsonWrapper& params) noexcept {
    NodeDesc::init(params);
    auto type_item = params.find("type");
    if (type_item != params.end() && type_item->is_string()) {
        sub_type = type_item->get<std::string>();
    } else {
        sub_type = "fixed";  // 默认值
    }
    auto param_item = params.find("param");
    if (param_item != params.end() && param_item->is_object()) {
        update_parameters(*param_item);

        // 从 param 中初始化嵌套对象
        auto rasterizer_item = param_item->find("rasterizer");
        if (rasterizer_item != param_item->end()) {
            rasterizer_desc.init(*rasterizer_item);
        }

        auto unwrapper_item = param_item->find("uv_unwrapper");
        if (unwrapper_item != param_item->end()) {
            unwrapper_desc.init(*unwrapper_item);
        }

        auto frame_buffer_item = param_item->find("frame_buffer");
        if (frame_buffer_item != param_item->end()) {
            frame_buffer_desc.init(*frame_buffer_item);
        }
    }
}

}  // namespace Corona::Resource::Scene
