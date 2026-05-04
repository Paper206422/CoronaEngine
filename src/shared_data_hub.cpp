#include <corona/shared_data_hub.h>

namespace Corona {

SharedDataHub& SharedDataHub::instance() {
    static SharedDataHub instance;
    return instance;
}

// Storage accessors definitions
SharedDataHub::ModelResourceStorage& SharedDataHub::model_resource_storage() { return model_resource_storage_; }
const SharedDataHub::ModelResourceStorage& SharedDataHub::model_resource_storage() const { return model_resource_storage_; }

SharedDataHub::ModelTransformStorage& SharedDataHub::model_transform_storage() { return model_transform_storage_; }
const SharedDataHub::ModelTransformStorage& SharedDataHub::model_transform_storage() const { return model_transform_storage_; }

SharedDataHub::GeometryStorage& SharedDataHub::geometry_storage() { return geometry_storage_; }
const SharedDataHub::GeometryStorage& SharedDataHub::geometry_storage() const { return geometry_storage_; }

SharedDataHub::KinematicsStorage& SharedDataHub::kinematics_storage() { return kinematics_storage_; }
const SharedDataHub::KinematicsStorage& SharedDataHub::kinematics_storage() const { return kinematics_storage_; }

SharedDataHub::MechanicsStorage& SharedDataHub::mechanics_storage() { return mechanics_storage_; }
const SharedDataHub::MechanicsStorage& SharedDataHub::mechanics_storage() const { return mechanics_storage_; }

SharedDataHub::AcousticsStorage& SharedDataHub::acoustics_storage() { return acoustics_storage_; }
const SharedDataHub::AcousticsStorage& SharedDataHub::acoustics_storage() const { return acoustics_storage_; }

SharedDataHub::OpticsStorage& SharedDataHub::optics_storage() { return optics_storage_; }
const SharedDataHub::OpticsStorage& SharedDataHub::optics_storage() const { return optics_storage_; }

SharedDataHub::ProfileStorage& SharedDataHub::profile_storage() { return profile_storage_; }
const SharedDataHub::ProfileStorage& SharedDataHub::profile_storage() const { return profile_storage_; }

SharedDataHub::ActorStorage& SharedDataHub::actor_storage() { return actor_storage_; }
const SharedDataHub::ActorStorage& SharedDataHub::actor_storage() const { return actor_storage_; }

SharedDataHub::CameraStorage& SharedDataHub::camera_storage() { return camera_storage_; }
const SharedDataHub::CameraStorage& SharedDataHub::camera_storage() const { return camera_storage_; }

SharedDataHub::EnvironmentStorage& SharedDataHub::environment_storage() { return environment_storage_; }
const SharedDataHub::EnvironmentStorage& SharedDataHub::environment_storage() const { return environment_storage_; }

SharedDataHub::SceneStorage& SharedDataHub::scene_storage() { return scene_storage_; }
const SharedDataHub::SceneStorage& SharedDataHub::scene_storage() const { return scene_storage_; }

SharedDataHub::ImageStorage& SharedDataHub::image_storage() { return image_storage_; }
const SharedDataHub::ImageStorage& SharedDataHub::image_storage() const { return image_storage_; }
}  // namespace Corona