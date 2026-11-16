shader_type spatial;
// Photo-scanned ground (CC0 Poly Haven sets: colour, normal, roughness), planar-mapped from the chunk-local
// position so tiles line up across chunks. Two rotated/offset samples blended by low-frequency noise hide the
// tiling; a broad tone variation adds wear. Wet / snow looks come from the global parameters (time_of_day.gd).
uniform sampler2D albedo_tex : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D normal_tex : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D rough_tex : hint_default_white, filter_linear_mipmap_anisotropic, repeat_enable;
uniform float tile_m = 3.0;          // real-world size of one texture repeat
uniform vec3 tint : source_color = vec3(1.0);
uniform float tint_mix = 0.0;        // 0 = photo colour, 1 = fully tinted (keeps photo luminance)
uniform float brightness = 1.0;
uniform float normal_strength = 1.0;
uniform float break_tiling = 1.0;    // 0 for regular patterns (paving slabs) where rotation would show
global uniform float wetness;
global uniform float snow_cover;
varying vec2 plan;
varying float up;

float h2(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float vn(vec2 p) { vec2 i = floor(p); vec2 f = fract(p); f = f * f * (3.0 - 2.0 * f);
	return mix(mix(h2(i), h2(i + vec2(1, 0)), f.x), mix(h2(i + vec2(0, 1)), h2(i + vec2(1, 1)), f.x), f.y); }

void vertex() {
	plan = VERTEX.xz;
	up = NORMAL.y;
	TANGENT = vec3(1.0, 0.0, 0.0);
	BINORMAL = vec3(0.0, 0.0, 1.0);
}

void fragment() {
	vec2 uv = plan / tile_m;
	vec2 uv2 = mat2(vec2(0.0, 1.0), vec2(-1.0, 0.0)) * uv + vec2(0.37, 0.61);   // 90 degrees + offset: same scale
	float n = vn(plan * 0.09) * 0.65 + vn(plan * 0.31) * 0.35;
	float k = smoothstep(0.35, 0.65, n) * break_tiling;
	vec3 a = mix(texture(albedo_tex, uv).rgb, texture(albedo_tex, uv2).rgb, k);
	vec3 nm = mix(texture(normal_tex, uv).rgb, texture(normal_tex, uv2).rgb, k);
	float r = mix(texture(rough_tex, uv).r, texture(rough_tex, uv2).r, k);
	float l = dot(a, vec3(0.299, 0.587, 0.114));
	a = mix(a, tint * l * 2.0, tint_mix);
	float macro = vn(plan * 0.02) * 0.6 + vn(plan * 0.007 + 3.0) * 0.4;
	a *= brightness * mix(0.86, 1.1, macro);
	float flat_ = smoothstep(0.6, 0.95, up);
	float s = clamp(smoothstep(0.0, 1.0, snow_cover * 1.6 - 0.6 * l - 0.3 * n) * flat_, 0.0, 1.0);
	float w = wetness * (1.0 - s);
	a *= 1.0 - 0.35 * w;
	r = mix(r, 0.12, w * flat_ * 0.85);
	a = mix(a, vec3(0.86, 0.88, 0.92), s);
	ALBEDO = a;
	ROUGHNESS = mix(r, 0.75, s);
	NORMAL_MAP = nm;
	NORMAL_MAP_DEPTH = normal_strength * (1.0 - s);
}
