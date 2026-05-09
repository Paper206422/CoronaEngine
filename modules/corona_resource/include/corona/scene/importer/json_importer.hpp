#pragma once

#include <fstream>
#include <iostream>

#include "i_importer.hpp"
#include "nlohmann/json.hpp"

namespace Corona::Resource::Scene {

class JsonImporter : public IImporter<JsonImporter> {
   public:
    JsonImporter() = default;
    ~JsonImporter() override = default;

   public:
    Corona::Resource::Scene::SceneDesc import_impl(const std::filesystem::path& path) {
        // Dummy implementation for example purposes
        Corona::Resource::Scene::SceneDesc scene_desc;
        std::cout << "Importing scene from JSON file: " << path << "\n";
        scene_desc = Corona::Resource::Scene::SceneDesc::from_json(path);
        return scene_desc;
    }
};
}  // namespace Corona::Resource::Scene