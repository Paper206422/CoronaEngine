//
// Created by Zero on 2023/7/14.
//

#include "importer.h"
#include "base/mgr/scene.h"
#include "base/mgr/global.h"
#include "base/mgr/pipeline.h"

namespace vision {

SP<Importer> Importer::create(const std::string &ext_name) {
    ImporterDesc desc;
    if (ext_name == ".json" || ext_name == ".bson") {
        desc.sub_type = "json";
    } else if (ext_name == ".usda" || ext_name == ".usdc") {
        desc.sub_type = "usd";
    } else {
        desc.sub_type = "assimp";
    }
    return Node::create_shared<Importer>(desc);
}

SP<Pipeline> Importer::import_scene(const fs::path &fn) {
    auto importer = Importer::create(fn.extension().string());
    return importer->read_file(fn);
}

SP<Pipeline> Importer::import_scene(const fs::path &fn, const ImportSceneOptions &options) {
    auto importer = Importer::create(fn.extension().string());
    return importer->read_file(fn, options);
}

SP<Pipeline> Importer::read_file(const fs::path &fn,
                                 const ImportSceneOptions &options) {
    (void)options;
    return read_file(fn);
}

void Importer::bind_shared_scene_resources(Pipeline &pipeline,
                                           const ImportSceneOptions &options) noexcept {
    if (options.scene_data) {
        pipeline.bind_shared_scene_data(options.scene_data);
    }
    if (options.geometry_gpu_resource) {
        pipeline.scene().bind_geometry_gpu_resource(options.geometry_gpu_resource);
    }
}

}// namespace vision
