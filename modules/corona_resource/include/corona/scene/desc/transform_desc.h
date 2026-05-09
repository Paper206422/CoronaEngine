#pragma once

#include <ktm/ktm.h>

#include "ktm/type_mat.h"
#include "node_desc.h"

namespace Corona::Resource::Scene {

struct TransformDesc : public NodeDesc {
    ktm::fmat4x4 mat{1.0f, 0.0f, 0.0f, 0.0f,
                     0.0f, 1.0f, 0.0f, 0.0f,
                     0.0f, 0.0f, 1.0f, 0.0f,
                     0.0f, 0.0f, 0.0f, 1.0f};

    void init(const JsonWrapper& params) override;
};

}  // namespace Corona::Resource::Scene