#include "base/mgr/geometry.h"
#include "base/mgr/global.h"
#include "base/mgr/scene.h"

#include <cstdlib>
#include <exception>
#include <filesystem>
#include <iostream>
#include <memory>
#include <string_view>
#include <type_traits>
#include <utility>

namespace {

[[noreturn]] void fail(std::string_view message) {
    std::cerr << "FAIL: " << message << '\n';
    std::exit(1);
}

void expect(bool condition, std::string_view message) {
    if (!condition) {
        fail(message);
    }
}

void geometry_gpu_resource_is_external_ownership_boundary() {
    static_assert(!std::is_copy_constructible_v<vision::GeometryGpuResource>);
    static_assert(!std::is_copy_assignable_v<vision::GeometryGpuResource>);
    static_assert(!std::is_move_constructible_v<vision::GeometryGpuResource>);
    static_assert(!std::is_move_assignable_v<vision::GeometryGpuResource>);
}

void geometry_requires_explicit_command_stream_for_gpu_updates() {
    static_assert(std::is_same_v<decltype(&vision::Geometry::build_accel),
                                 void (vision::Geometry::*)(vision::Stream&)>);
    static_assert(std::is_same_v<decltype(&vision::Geometry::update_accel),
                                 void (vision::Geometry::*)(vision::Stream&)>);
    static_assert(std::is_same_v<decltype(&vision::Geometry::upload),
                                 void (vision::Geometry::*)(vision::Stream&)>);
    static_assert(std::is_same_v<decltype(&vision::Geometry::upload_bindless_array),
                                 void (vision::Geometry::*)(vision::Stream&)>);
}

void geometry_defaults_to_unbound_gpu_resource() {
    vision::Geometry geometry;
    expect(!geometry.has_gpu_resource(),
           "default Geometry should not allocate scene GPU resources by itself");
    expect(geometry.data() == nullptr,
           "default Geometry data should be absent until a GPU resource is bound");
}

void geometry_binds_external_scene_gpu_resource() {
    vision::Geometry geometry;
    auto* fake_gpu_resource =
        reinterpret_cast<vision::GeometryGpuResource*>(0x3000);
    std::shared_ptr<vision::GeometryGpuResource> shared_gpu_resource(
        fake_gpu_resource,
        [](vision::GeometryGpuResource*) {});

    geometry.bind_gpu_resource(shared_gpu_resource);

    expect(geometry.has_gpu_resource(),
           "Geometry should report a bound external scene GPU resource");
    expect(geometry.gpu_resource() == shared_gpu_resource,
           "Geometry should keep the exact shared scene GPU resource object");
}

void multiple_geometry_views_share_one_scene_gpu_resource() {
    auto* fake_gpu_resource =
        reinterpret_cast<vision::GeometryGpuResource*>(0x4000);
    std::shared_ptr<vision::GeometryGpuResource> shared_gpu_resource(
        fake_gpu_resource,
        [](vision::GeometryGpuResource*) {});

    vision::Geometry svgf_geometry_view;
    vision::Geometry ssat_geometry_view;
    svgf_geometry_view.bind_gpu_resource(shared_gpu_resource);
    ssat_geometry_view.bind_gpu_resource(shared_gpu_resource);

    expect(svgf_geometry_view.gpu_resource() == ssat_geometry_view.gpu_resource(),
           "different pipeline geometry views should reference the same scene GPU resource");
    expect(shared_gpu_resource.use_count() == 3,
           "shared scene GPU resource should be held once by each geometry view and once by the owner");
}

void shape_instance_mesh_constructor_is_cpu_only() {
    vision::Mesh mesh;
    vision::ShapeInstance instance(std::move(mesh));

    expect(instance.mesh() != nullptr,
           "ShapeInstance should keep a CPU mesh before scene GPU registration");
    expect(instance.handle().mesh_id == vision::InvalidUI32,
           "ShapeInstance(Mesh) should not register a mesh id during construction");
}

void two_scene_views_bind_one_real_scene_gpu_resource() {
    try {
        ocarina::RHIContext::instance().init(std::filesystem::current_path());
        auto device = ocarina::RHIContext::instance().create_device("cuda");
        device.init_rtx();
        vision::Global::instance().set_device(&device);

        auto shared_gpu_resource =
            std::make_shared<vision::GeometryGpuResource>(device);
        vision::Scene svgf_scene_view;
        vision::Scene ssat_scene_view;

        svgf_scene_view.bind_geometry_gpu_resource(shared_gpu_resource);
        ssat_scene_view.bind_geometry_gpu_resource(shared_gpu_resource);

        expect(svgf_scene_view.geometry().gpu_resource() == shared_gpu_resource,
               "first Scene view should bind the shared scene GPU resource");
        expect(ssat_scene_view.geometry().gpu_resource() == shared_gpu_resource,
               "second Scene view should bind the same shared scene GPU resource");
        expect(svgf_scene_view.geometry().data() == ssat_scene_view.geometry().data(),
               "Scene geometry views should expose one shared GeometryData");
        expect(&svgf_scene_view.geometry().bindless_array() ==
                   &ssat_scene_view.geometry().bindless_array(),
               "Scene geometry views should expose one shared scene bindless array");
        expect(&svgf_scene_view.geometry().accel() ==
                   &ssat_scene_view.geometry().accel(),
               "Scene geometry views should expose one shared acceleration structure");
    } catch (const std::exception& e) {
        std::cout << "SKIP: CUDA-backed GeometryGpuResource integration unavailable: "
                  << e.what() << '\n';
    } catch (...) {
        std::cout << "SKIP: CUDA-backed GeometryGpuResource integration unavailable\n";
    }
}

}  // namespace

int main() {
    geometry_gpu_resource_is_external_ownership_boundary();
    geometry_requires_explicit_command_stream_for_gpu_updates();
    geometry_defaults_to_unbound_gpu_resource();
    geometry_binds_external_scene_gpu_resource();
    multiple_geometry_views_share_one_scene_gpu_resource();
    shape_instance_mesh_constructor_is_cpu_only();
    two_scene_views_bind_one_real_scene_gpu_resource();
    return 0;
}
