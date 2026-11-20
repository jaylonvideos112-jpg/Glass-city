shader_type spatial;
// Real Ohio OSIP aerial photo for one 200 m chunk, projected from above (plan UVs from model-space position),
// modulated by a tiling detail texture so surfaces keep texture up close. Wet and snowy looks come from the
// global shader parameters set by time_of_day.gd.
uniform sampler2D aerial : source_color, filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D detail : source_color, filter_linear_mipmap, repeat_enable;
uniform float chunk_size = 200.0;
uniform float detail_scale = 0.25;
uniform float detail_strength = 0.35;
// how much of the aerial photo to keep (1 = all). Below 1 the ground blends toward a clean tiled texture whose
// brightness follows the photo - photos of lots and lawns are blurry and full of shadows and parked cars.
uniform float photo_mix = 1.0;
uniform sampler2D clean : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform float clean_scale = 0.25;
// classify = 1: no photo pixels at all. A heavily blurred photo only decides WHERE the ground is lawn (alt texture)
// and where it is paved (clean texture), so lots get real-world lawn shapes without blotches, cars or shadows.
uniform float classify = 0.0;
uniform sampler2D alt : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform float alt_scale = 0.15;
// photo-scanned normal / roughness for the clean (paved) and alt (lawn) layers
uniform sampler2D clean_nor : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D clean_rough : hint_default_white, filter_linear_mipmap, repeat_enable;
uniform sampler2D alt_nor : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D alt_rough : hint_default_white, filter_linear_mipmap, repeat_enable;
uniform float use_pbr = 0.0;
// roof_uv = 1: pitched roofs. Colour comes from the (softened) photo, relief from a shingle scan laid out along the
// roof's own UVs (rows parallel to the eave) so it reads as asphalt shingles up close.
uniform float roof_uv = 0.0;
uniform vec3 alt_tint : source_color = vec3(1.0);
uniform float alt_tint_mix = 0.0;
global uniform float wetness;
global uniform float snow_cover;
varying vec2 plan;
varying float up;
void vertex() {
	plan = VERTEX.xz;
	up = NORMAL.y;
	TANGENT = vec3(1.0, 0.0, 0.0);
	BINORMAL = vec3(0.0, 0.0, 1.0);
}
float n2(vec2 p) { return fract(sin(dot(floor(p), vec2(12.9898, 78.233))) * 43758.5453); }
float vn(vec2 p) { vec2 i = floor(p); vec2 f = fract(p); f = f * f * (3.0 - 2.0 * f);
	return mix(mix(n2(i), n2(i + vec2(1, 0)), f.x), mix(n2(i + vec2(0, 1)), n2(i + vec2(1, 1)), f.x), f.y); }
void fragment() {
	vec2 auv = vec2(plan.x / chunk_size, (plan.y + chunk_size) / chunk_size);
	vec3 a = texture(aerial, clamp(auv, vec2(0.001), vec2(0.999))).rgb;
	float d = dot(texture(detail, plan * detail_scale).rgb, vec3(0.333));
	// photo already contains sunlight: pull exposure down, add a little contrast/saturation back
	a = pow(a, vec3(1.18)) * 0.82;
	float l = dot(a, vec3(0.299, 0.587, 0.114));
	a = mix(vec3(l), a, 1.18);
	vec3 col = a * mix(1.0, 0.75 + d * 0.6, detail_strength);
	float pbr_rough = -1.0;
	float big = vn(plan * 0.05) * 0.5 + vn(plan * 0.013 + 7.0) * 0.5;   // broad patchiness
	if (classify > 0.5) {
		vec3 b = textureLod(aerial, clamp(auv, vec2(0.001), vec2(0.999)), 4.0).rgb;
		float bl = dot(b, vec3(0.299, 0.587, 0.114));
		float g = b.g - max(b.r, b.b);
		float lawn = smoothstep(0.004, 0.03, g) * smoothstep(0.05, 0.11, bl);
		vec3 paved = texture(clean, plan * clean_scale).rgb;
		vec3 grass = texture(alt, plan * alt_scale).rgb;
		float gl = dot(grass, vec3(0.299, 0.587, 0.114));
		grass = mix(grass, alt_tint * gl * 2.0, alt_tint_mix) * mix(0.85, 1.08, big);
		col = mix(paved, grass, lawn);
		if (use_pbr > 0.5) {
			NORMAL_MAP = mix(texture(clean_nor, plan * clean_scale).rgb, texture(alt_nor, plan * alt_scale).rgb, lawn);
			pbr_rough = mix(texture(clean_rough, plan * clean_scale).r, texture(alt_rough, plan * alt_scale).r, lawn);
		}
	} else if (photo_mix < 0.01) {
		col = texture(clean, plan * clean_scale).rgb * mix(0.86, 1.06, big);
		if (use_pbr > 0.5) {
			float cl2 = dot(col, vec3(0.299, 0.587, 0.114));
			col = mix(col, alt_tint * cl2 * 2.0, alt_tint_mix);
			NORMAL_MAP = texture(clean_nor, plan * clean_scale).rgb;
			pbr_rough = texture(clean_rough, plan * clean_scale).r;
		}
	} else if (photo_mix < 0.999) {
		vec3 c = texture(clean, plan * clean_scale).rgb;
		float cl = max(dot(c, vec3(0.299, 0.587, 0.114)), 0.02);
		vec3 tint = mix(vec3(1.0), a / max(l, 0.02), 0.35);          // keep a little of the photo's hue
		vec3 cc = c * clamp(l / cl, 0.7, 1.25) * tint;
		col = mix(cc, col, photo_mix);
	}
	if (roof_uv > 0.5) {
		vec3 rb = textureLod(aerial, clamp(auv, vec2(0.001), vec2(0.999)), 1.5).rgb;
		rb = pow(rb, vec3(1.18)) * 0.82;
		float rl = dot(rb, vec3(0.299, 0.587, 0.114));
		rb = mix(vec3(rl), rb, 0.9);
		vec3 sh = texture(clean, UV).rgb;
		float sl = dot(sh, vec3(0.299, 0.587, 0.114));
		col = rb * clamp(sl / 0.42, 0.45, 1.6);
		NORMAL_MAP = texture(clean_nor, UV).rgb;
		NORMAL_MAP_DEPTH = 1.4;
		pbr_rough = texture(clean_rough, UV).r;
	}
	float rough = pbr_rough >= 0.0 ? pbr_rough : 0.92;
	// snow settles on flat surfaces first; patchy while thin
	float flat_ = smoothstep(0.6, 0.95, up);
	float patch = smoothstep(0.0, 1.0, snow_cover * 1.6 - 0.6 * d - 0.3 * n2(plan * 0.7));
	float s = clamp(patch * flat_, 0.0, 1.0);
	// wet: darker, glossier (less where snow lies)
	float w = wetness * (1.0 - s);
	col *= 1.0 - 0.32 * w;
	rough = mix(rough, 0.28, w * flat_);
	col = mix(col, vec3(0.86, 0.88, 0.92), s);
	rough = mix(rough, 0.75, s);
	ALBEDO = col;
	ROUGHNESS = rough;
}
