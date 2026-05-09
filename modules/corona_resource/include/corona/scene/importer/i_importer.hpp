#pragma once

#include <filesystem>

#include "../desc/scene_desc.h"

namespace Corona::Resource::Scene {
// CRTP 导入器基类
template <typename Derived>
class IImporter {
   public:
    IImporter() = default;
    virtual ~IImporter() = default;

   public:
    [[nodiscard]]
    SceneDesc import(const std::filesystem::path& path) {
        return static_cast<Derived*>(this)->import_impl(path);
    }
};
}  // namespace Corona::Resource::Scene