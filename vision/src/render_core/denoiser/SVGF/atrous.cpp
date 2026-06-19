#include "atrous.h"
#include "svgf.h"
#include "svgf_config.h"
#include "math/util.h"

namespace vision::svgf {

using Cfg = SVGFConfig;

void AtrousFilter::prepare() noexcept {
    uint pixel_num = pipeline()->pixel_num();
    init_buffer_zero(device(), temp_buffer_direct_, pixel_num, "AtrousFilter::temp_buffer_direct");
    init_buffer_zero(device(), temp_buffer_indirect_, pixel_num, "AtrousFilter::temp_buffer_indirect");
}

void AtrousFilter::compile() noexcept {
    compile_combined();
}


void AtrousFilter::compile_combined() noexcept {
Pipeline *pipeline_ref = pipeline();
Kernel kernel = [&, pipeline_ref](Var<CombinedAtrousParam> param) {
    Int2 screen_size = make_int2(dispatch_dim().xy());
    Int2 cur_pixel = make_int2(dispatch_idx().xy());
    Uint cur_idx = dispatch_id();
        
    TriangleHitVar center_hit = param.visibility_buffer.read(cur_idx);
    RadType4Var direct_center = param.direct_src.read(cur_idx);
    RadType4Var indirect_center = param.indirect_src.read(cur_idx);
        
        
    $if(!PixelStateUtils::is_sky(center_hit)) {
        Interaction center_it = pipeline_ref->geometry().compute_surface_interaction(center_hit, false);
        
        // Clamp luminance for half precision safety
        Float lum_center_direct = HalfSafeUtils::clamp_luminance(luminance(direct_center.xyz()));
        Float lum_center_indirect = HalfSafeUtils::clamp_luminance(luminance(indirect_center.xyz()));
        
        // Clamp variance to half-safe range before computing phi_l
        Float var_direct_clamped = max(Float(direct_center.w), Cfg::Epsilon::kVariance);
        Float var_indirect_clamped = max(Float(indirect_center.w), Cfg::Epsilon::kVariance);
        Float phi_l_direct = LuminanceWeightUtils::compute_phi_l(param.l_phi, var_direct_clamped);
        Float phi_l_indirect = LuminanceWeightUtils::compute_phi_l(param.l_phi, var_indirect_clamped);
            
        Float3 sum_direct = make_float3(0.f);
        Float3 sum_indirect = make_float3(0.f);
        Float weight_sum_direct = 0.f;
        Float weight_sum_indirect = 0.f;
        Float variance_sum_direct = 0.f;
        Float variance_sum_indirect = 0.f;
            
        using AR = Cfg::AdaptiveRadius;
        
        Float scale_direct = lerp(1.f, lerp(AR::kMinScale, AR::kMaxScale, 
            saturate(sqrt(var_direct_clamped) * AR::kVarianceScale)), AR::kDirectAdaptiveStrength);
        Float scale_indirect = lerp(1.f, lerp(AR::kMinScale, AR::kMaxScale, 
            saturate(sqrt(var_indirect_clamped) * AR::kVarianceScale)), AR::kIndirectAdaptiveStrength);
            
        Float3 view_dir = normalize(param.camera_pos.as_vec3() - center_it.pos);
            
        // Mix frame_index into the seed so the rotated Poisson disk jitters every frame;
        // a frame-static pattern bakes a fixed structured bias that temporal accumulation
        // cannot average out (which is the whole point of random-rotation a-trous).
        Uint hash_seed = tea<D>(tea<D>(tea<D>(cast<uint>(cur_pixel.x), cast<uint>(cur_pixel.y)), param.iteration), param.frame_index);
        Float rotation_angle = lcg<D>(hash_seed) * 2.f * Pi;
        Float cos_rot = cos(rotation_angle);
        Float sin_rot = sin(rotation_angle);
        
        Float step_f = cast<float>(param.step_size);
        
        auto probe_direction = [&](Int2 offset) -> Float {
            Int2 p = cur_pixel + offset * param.step_size;
            Float weight = 0.f;
            
            $if(all(p >= 0) && all(p < screen_size)) {
                Uint idx = cast<uint>(p.y) * cast<uint>(screen_size.x) + cast<uint>(p.x);
                TriangleHitVar neighbor_hit = param.visibility_buffer.read(idx);
                Bool neighbor_is_sky = PixelStateUtils::is_sky(neighbor_hit);
                
                Float boundary_w = BoundaryUtils::compute_boundary_weight(
                    pipeline_ref, center_hit, neighbor_hit);
                
                $if(!neighbor_is_sky && boundary_w > 0.f) {
                    Interaction neighbor_it = pipeline_ref->geometry().compute_surface_interaction(neighbor_hit, false);
                    weight = boundary_w * GeometryWeightUtils::compute_geometry_weight(
                        center_it.pos, center_it.ng, neighbor_it.pos, neighbor_it.ng,
                        param.n_phi, param.z_phi, Cfg::GeometryWeight::kEpsilon);
                };
            };
            return weight;
        };
        
        Float w_right = probe_direction(make_int2(1, 0));
        Float w_up = probe_direction(make_int2(0, -1));
        Float w_left = probe_direction(make_int2(-1, 0));
        Float w_down = probe_direction(make_int2(0, 1));
        
        using AnisotropyInfo = AnisotropicUtils::EdgeAnisotropyInfo;
        AnisotropyInfo aniso_info;
        
        $if(Cfg::Anisotropic::kEnabled && Cfg::Anisotropic::kEdgeAwareEnabled) {
            aniso_info = AnisotropicUtils::compute_combined_anisotropy(
                center_it.ng, view_dir, w_right, w_up, w_left, w_down);
        }
        $else {
            aniso_info.stretch_dir = make_float2(1.f, 0.f);
            aniso_info.ratio = AnisotropicUtils::compute_grazing_anisotropy(center_it.ng, view_dir);
        };
        
        auto sample_neighbor = [&](Float sample_x, Float sample_y, Float base_weight) {
            Float2 base_offset = make_float2(sample_x, sample_y);
            Float2 aniso_sample = AnisotropicUtils::apply_edge_anisotropic_transform(base_offset, aniso_info);
            
            Float step = step_f * scale_indirect;
            Int2 p = cur_pixel + make_int2(
                cast<int>(round((aniso_sample.x * cos_rot - aniso_sample.y * sin_rot) * step * 2.f)),
                cast<int>(round((aniso_sample.x * sin_rot + aniso_sample.y * cos_rot) * step * 2.f)));
                
            $if(all(p >= 0) && all(p < screen_size)) {
                Uint idx = cast<uint>(p.y) * cast<uint>(screen_size.x) + cast<uint>(p.x);
                    
                RadType4Var direct_neighbor = param.direct_src.read(idx);
                RadType4Var indirect_neighbor = param.indirect_src.read(idx);
                    
                TriangleHitVar neighbor_hit = param.visibility_buffer.read(idx);
                Bool neighbor_is_sky = PixelStateUtils::is_sky(neighbor_hit);
                
                Float boundary_weight = BoundaryUtils::compute_boundary_weight(
                    pipeline_ref, center_hit, neighbor_hit);
                    
                Float3 neighbor_normal = make_float3(0.f, 1.f, 0.f);
                Float3 neighbor_pos = make_float3(0.f);
                    
                $if(!neighbor_is_sky) {
                    Interaction neighbor_it = pipeline_ref->geometry().compute_surface_interaction(neighbor_hit, false);
                    neighbor_normal = neighbor_it.ng;
                    neighbor_pos = neighbor_it.pos;
                };
                    
                Float w_geo = GeometryWeightUtils::handle_sky_weight(false, neighbor_is_sky,
                    ocarina::select(neighbor_is_sky, 1.f,
                        GeometryWeightUtils::compute_geometry_weight(
                            center_it.pos, center_it.ng, neighbor_pos, neighbor_normal,
                            param.n_phi, param.z_phi, Cfg::GeometryWeight::kEpsilon)));
                
                w_geo *= boundary_weight;
                
                
                Float aniso_compensation = 1.f / aniso_info.ratio;
                
                // Clamp neighbor luminance for half precision safety
                Float lum_neighbor_direct = HalfSafeUtils::clamp_luminance(luminance(direct_neighbor.xyz()));
                Float lum_neighbor_indirect = HalfSafeUtils::clamp_luminance(luminance(indirect_neighbor.xyz()));
                    
                Float w_direct = base_weight * w_geo * aniso_compensation *
                    LuminanceWeightUtils::compute_variance_guided(lum_center_direct, lum_neighbor_direct, phi_l_direct) *
                    lerp(1.f, 1.f / max(scale_direct, 0.5f), length(base_offset));
                Float w_indirect = base_weight * w_geo * aniso_compensation *
                    LuminanceWeightUtils::compute_variance_guided(lum_center_indirect, lum_neighbor_indirect, phi_l_indirect);
                
                // Clamp variance to prevent underflow in w*w computation
                Float var_neighbor_direct = max(Float(direct_neighbor.w), Cfg::Epsilon::kVariance);
                Float var_neighbor_indirect = max(Float(indirect_neighbor.w), Cfg::Epsilon::kVariance);
                    
                sum_direct += direct_neighbor.xyz() * w_direct;
                sum_indirect += indirect_neighbor.xyz() * w_indirect;
                variance_sum_direct += var_neighbor_direct * w_direct * w_direct;
                variance_sum_indirect += var_neighbor_indirect * w_indirect * w_indirect;
                weight_sum_direct += w_direct;
                weight_sum_indirect += w_indirect;
            };
        };
            
        sample_neighbor(0.0f, 0.0f, 1.0f);
        sample_neighbor(-0.5f, -0.5f, 0.7f);
        sample_neighbor( 0.5f, -0.5f, 0.7f);
        sample_neighbor(-0.5f,  0.5f, 0.7f);
        sample_neighbor( 0.5f,  0.5f, 0.7f);
        sample_neighbor(-0.85f,  0.0f, 0.4f);
        sample_neighbor( 0.0f,  -0.85f, 0.4f);
        sample_neighbor( 0.85f,  0.0f, 0.4f);
        sample_neighbor( 0.0f,   0.85f, 0.4f);
        sample_neighbor(-0.65f, -0.65f, 0.25f);
        sample_neighbor( 0.65f, -0.65f, 0.25f);
        sample_neighbor(-0.65f,  0.65f, 0.25f);
            
        param.direct_dst.write(cur_idx, make_RadType4(make_float4(
            sum_direct / max(weight_sum_direct, Cfg::Epsilon::kWeight),
            VarianceUtils::propagate_filtered_variance(variance_sum_direct, weight_sum_direct * weight_sum_direct))));
        param.indirect_dst.write(cur_idx, make_RadType4(make_float4(
            sum_indirect / max(weight_sum_indirect, Cfg::Epsilon::kWeight),
            VarianceUtils::propagate_filtered_variance(variance_sum_indirect, weight_sum_indirect * weight_sum_indirect))));
    }
    $else {
        param.direct_dst.write(cur_idx, direct_center);
        param.indirect_dst.write(cur_idx, indirect_center);
    };
};
    
    combined_shader_ = device().compile(kernel, "SVGF-AtrousFilter-EdgeAware");
}




CommandBatch AtrousFilter::dispatch_combined(vision::RealTimeDenoiseInput &input,
                                         uint step_width, uint iteration) noexcept {
    CombinedAtrousParam param;
    
    bool read_from_temp = (iteration % 2 == 1);
    if (!read_from_temp) {
        param.direct_src = input.direct.descriptor();
        param.direct_dst = temp_buffer_direct_.descriptor();
        param.indirect_src = input.indirect.descriptor();
        param.indirect_dst = temp_buffer_indirect_.descriptor();
    } else {
        param.direct_src = temp_buffer_direct_.descriptor();
        param.direct_dst = input.direct.descriptor();
        param.indirect_src = temp_buffer_indirect_.descriptor();
        param.indirect_dst = input.indirect.descriptor();
    }
    
    param.visibility_buffer = input.visibility.descriptor();
    param.camera_pos = input.camera_pos;
    
    float l_phi = svgf_->sigma_rt();
    float n_phi = svgf_->sigma_normal();
    
    if (step_width >= Cfg::Atrous::kLargeStepThreshold) {
        l_phi *= Cfg::Atrous::kLargeStepLPhiMultiplier;
        n_phi *= Cfg::Atrous::kLargeStepNPhiMultiplier;
    }
    
    param.l_phi = l_phi;
    param.n_phi = n_phi;
    param.z_phi = svgf_->sigma_depth();
    param.step_size = static_cast<int>(step_width);
    param.iteration = iteration;
    param.frame_index = input.frame_index;
    
    CommandBatch ret;
    ret << combined_shader_(param).dispatch(input.resolution);
    return ret;
}


void AtrousFilter::update_resolution(uint2 resolution) noexcept {
    uint num = resolution.x * resolution.y;
    init_buffer_zero(device(), temp_buffer_direct_, num, "AtrousFilter::temp_buffer_direct");
    init_buffer_zero(device(), temp_buffer_indirect_, num, "AtrousFilter::temp_buffer_indirect");
}

}// namespace vision::svgf
