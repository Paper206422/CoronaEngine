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
// Canonical SVGF a-trous wavelet pass (Schied et al. 2017): a deterministic
// 5x5 cross-bilateral B-spline kernel with depth/normal/luminance edge stopping.
//
// P0 rewrite rationale: the previous kernel used a per-frame RANDOMLY ROTATED
// sparse 12-tap Poisson disk. Because the a-trous output is never fed back into
// the temporal history buffer (history is written only by the variance stage),
// that per-frame rotation produced shimmering, blotchy "blocky" noise that
// temporal accumulation could not average out. A fixed, dense, deterministic
// kernel is temporally stable by construction. Anisotropic stretching and the
// variance-driven adaptive radius were removed for the same reason (they made
// every pixel's footprint frame/varying-dependent); they can be re-added later
// on top of a stable base if needed.
Kernel kernel = [&, pipeline_ref](Var<CombinedAtrousParam> param) {
    Int2 screen_size = make_int2(dispatch_dim().xy());
    Int2 cur_pixel = make_int2(dispatch_idx().xy());
    Uint cur_idx = dispatch_id();

    TriangleHitVar center_hit = param.visibility_buffer.read(cur_idx);
    RadType4Var direct_center = param.direct_src.read(cur_idx);
    RadType4Var indirect_center = param.indirect_src.read(cur_idx);

    $if(!PixelStateUtils::is_sky(center_hit)) {
        Interaction center_it = pipeline_ref->geometry().compute_surface_interaction(center_hit, false);

        Float lum_center_direct = HalfSafeUtils::clamp_luminance(luminance(direct_center.xyz()));
        Float lum_center_indirect = HalfSafeUtils::clamp_luminance(luminance(indirect_center.xyz()));

        Float var_direct_clamped = max(Float(direct_center.w), Cfg::Epsilon::kVariance);
        Float var_indirect_clamped = max(Float(indirect_center.w), Cfg::Epsilon::kVariance);
        Float phi_l_direct = LuminanceWeightUtils::compute_phi_l(param.l_phi, var_direct_clamped);
        Float phi_l_indirect = LuminanceWeightUtils::compute_phi_l(param.l_phi, var_indirect_clamped);

        // Center tap: kernel weight h(0)*h(0), geometry/luminance weight == 1.
        constexpr float kW0 = Cfg::Atrous::kBSpline1D[0] * Cfg::Atrous::kBSpline1D[0];
        Float3 sum_direct = direct_center.xyz() * kW0;
        Float3 sum_indirect = indirect_center.xyz() * kW0;
        Float weight_sum_direct = kW0;
        Float weight_sum_indirect = kW0;
        Float variance_sum_direct = var_direct_clamped * (kW0 * kW0);
        Float variance_sum_indirect = var_indirect_clamped * (kW0 * kW0);

        auto accumulate_tap = [&](int dx, int dy, float h) {
            // h is the host-side separable B-spline kernel weight for this tap.
            Int2 p = cur_pixel + make_int2(dx, dy) * param.step_size;

            $if(all(p >= 0) && all(p < screen_size)) {
                Uint idx = cast<uint>(p.y) * cast<uint>(screen_size.x) + cast<uint>(p.x);

                RadType4Var direct_neighbor = param.direct_src.read(idx);
                RadType4Var indirect_neighbor = param.indirect_src.read(idx);

                TriangleHitVar neighbor_hit = param.visibility_buffer.read(idx);
                Bool neighbor_is_sky = PixelStateUtils::is_sky(neighbor_hit);

                Float boundary_weight = BoundaryUtils::compute_boundary_weight(
                    pipeline_ref, center_hit, neighbor_hit);

                Float w_geo = 0.f;
                $if(!neighbor_is_sky && boundary_weight > 0.f) {
                    Interaction neighbor_it = pipeline_ref->geometry().compute_surface_interaction(neighbor_hit, false);
                    w_geo = GeometryWeightUtils::compute_geometry_weight(
                        center_it.pos, center_it.ng, neighbor_it.pos, neighbor_it.ng,
                        param.n_phi, param.z_phi, Cfg::GeometryWeight::kEpsilon);
                };
                w_geo *= boundary_weight;

                Float lum_neighbor_direct = HalfSafeUtils::clamp_luminance(luminance(direct_neighbor.xyz()));
                Float lum_neighbor_indirect = HalfSafeUtils::clamp_luminance(luminance(indirect_neighbor.xyz()));

                Float w_direct = h * w_geo *
                    LuminanceWeightUtils::compute_variance_guided(lum_center_direct, lum_neighbor_direct, phi_l_direct);
                Float w_indirect = h * w_geo *
                    LuminanceWeightUtils::compute_variance_guided(lum_center_indirect, lum_neighbor_indirect, phi_l_indirect);

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

        // Host-unrolled 5x5 separable B-spline {0.375, 0.25, 0.0625}; center handled above.
        for (int dy = -2; dy <= 2; ++dy) {
            for (int dx = -2; dx <= 2; ++dx) {
                if (dx == 0 && dy == 0) { continue; }
                float h = Cfg::Atrous::kBSpline1D[dx < 0 ? -dx : dx] *
                          Cfg::Atrous::kBSpline1D[dy < 0 ? -dy : dy];
                accumulate_tap(dx, dy, h);
            }
        }

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

    combined_shader_ = device().compile(kernel, "SVGF-AtrousFilter-BSpline");
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
