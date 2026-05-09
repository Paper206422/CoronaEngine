#include "corona/scene/desc/common.h"

namespace Corona::Resource::Scene {

bool NameID::valid() const {
    return id != Invalid_ID;
}

void NameID::fill_id(const IDMap& name2id_map) {
    if (name.empty()) {
        id = Invalid_ID;
        return;
    }

    auto it = name2id_map.find(name);
    if (it != name2id_map.end()) {
        id = it->second;
    } else {
        id = Invalid_ID;
    }
}

}  // namespace Corona::Resource::Scene