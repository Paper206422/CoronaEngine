//
// Created by Zero on 2023/7/14.
//

#include "base/import/importer.h"
#include "base/import/json_util.h"
#include "base/mgr/pipeline.h"

namespace vision {

class JsonImporter : public Importer {
public:
    explicit JsonImporter(const ImporterDesc &desc)
        : Importer(desc) {}

    [[nodiscard]] SP<Pipeline> read_file(const fs::path &fn) override {
        return read_file(fn, {});
    }

    [[nodiscard]] SP<Pipeline> read_file(const fs::path &fn,
                                         const ImportSceneOptions &options) override {
        auto project_desc = ProjectDesc::from_json(fn);
        SP<Pipeline> ret = Node::create_shared<Pipeline>(project_desc.pipeline_desc);
        bind_shared_scene_resources(*ret, options);
        ret->init_project(project_desc);
        ret->init_postprocessor(project_desc.renderer_desc.denoiser_desc);
        return ret;
    }
    VS_MAKE_PLUGIN_NAME_FUNC
};

}// namespace vision

VS_MAKE_CLASS_CREATOR(vision::JsonImporter)
