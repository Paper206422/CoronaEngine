//
// Created by Zero on 2023/7/14.
//

#pragma once

#include <utility>
#include "core/stl.h"
#include "base/mgr/scene.h"
#include "base/using.h"

namespace vision {

class GeometryGpuResource;

struct ImportSceneOptions {
    SP<SceneData> scene_data{};
    SP<GeometryGpuResource> geometry_gpu_resource{};
};

class Importer : public Node {
public:
    using Desc = ImporterDesc;

public:
    explicit Importer(const ImporterDesc &desc) : Node(desc) {}
    static SP<Importer> create(const string &ext_name);
    static SP<Pipeline> import_scene(const fs::path &fn);
    static SP<Pipeline> import_scene(const fs::path &fn, const ImportSceneOptions &options);
    [[nodiscard]] virtual SP<Pipeline> read_file(const fs::path &fn) = 0;
    [[nodiscard]] virtual SP<Pipeline> read_file(const fs::path &fn,
                                                 const ImportSceneOptions &options);

protected:
    static void bind_shared_scene_resources(Pipeline &pipeline,
                                            const ImportSceneOptions &options) noexcept;
};

}// namespace vision
