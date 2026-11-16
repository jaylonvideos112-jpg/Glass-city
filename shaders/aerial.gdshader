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
global uniform float wetness;
global uniform float snow_cover;
varying vec2 plan;
varying float up;
void vertex() {
	plan = VERTEX.xz;
	up = NORMAL.y;
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
	float big = vn(plan * 0.05) * 0.5 + vn(plan * 0.013 + 7.0) * 0.5;   // broad patchiness
	if (classify > 0.5) {
		vec3 b = textureLod(aerial, clamp(auv, vec2(0.001), vec2(0.999)), 4.0).rgb;
		float bl = dot(b, vec3(0.299, 0.587, 0.114));
		float g = b.g - max(b.r, b.b);
		float lawn = smoothstep(0.004, 0.03, g) * smoothstep(0.05, 0.11, bl);
		vec3 paved = texture(clean, plan * clean_scale).rgb;
		vec3 grass = texture(alt, plan * alt_scale).rgb * mix(0.85, 1.08, big);
		col = mix(paved, grass, lawn);
	} else if (photo_mix < 0.01) {
		col = texture(clean, plan * clean_scale).rgb * mix(0.86, 1.06, big);
	} else if (photo_mix < 0.999) {
		vec3 c = texture(clean, plan * clean_scale).rgb;
		float cl = max(dot(c, vec3(0.299, 0.587, 0.114)), 0.02);
		vec3 tint = mix(vec3(1.0), a / max(l, 0.02), 0.35);          // keep a little of the photo's hue
		vec3 cc = c * clamp(l / cl, 0.7, 1.25) * tint;
		col = mix(cc, col, photo_mix);
	}
	float rough = 0.92;
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
