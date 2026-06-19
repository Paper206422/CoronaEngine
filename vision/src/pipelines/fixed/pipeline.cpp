//
// Created by Zero on 2023/6/12.
//

#include "base/mgr/pipeline.h"

namespace vision {

class FixedRenderPipeline : public Pipeline {
public:
    explicit FixedRenderPipeline(const PipelineDesc &desc)
        : Pipeline(desc) {}
    VS_MAKE_PLUGIN_NAME_FUNC
    void prepare() noexcept override {
        Pipeline::prepare();
        scene_.prepare();
        renderer_.prepare(scene_);
        image_pool().prepare();
        prepare_geometry();
        upload_bindless_array();
        compile();
        preprocess();
    }

    void init_project(const vision::ProjectDesc &project_desc) override {
        Pipeline::init_project(project_desc);
        init_postprocessor(project_desc.renderer_desc.denoiser_desc);
    }

    void init_postprocessor(const DenoiserDesc &desc) override {
//        postprocessor_.set_denoiser(Node::create_shared<Denoiser>(desc));
        postprocessor_.set_tone_mapper(renderer_.frame_buffer()->tone_mapper());
    }

    void compile() noexcept override {
        Pipeline::compile();
        integrator()->compile();
    }

    void render(double dt) noexcept override {
        integrator()->render();
    }
};

}// namespace vision

VS_MAKE_CLASS_CREATOR(vision::FixedRenderPipeline)
