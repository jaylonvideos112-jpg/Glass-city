shader_type spatial;
// Real Ohio OSIP aerial photo for one 200 m chunk, projected from above (plan UVs from model-space position),
// modulated by a tiling detail texture so surfaces keep texture up close. Wet and snowy looks come from the
// global shader parameters set by time_of_day.gd.
uniform sampler2D aerial : source_color, filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D detail : source_color, filter_linear_mipmap, repeat_enable;
uniform float chunk_size = 200.0;
uniform float detail_scale = 0.25;
uniform float detail_strength = 0.35;
global uniform float wetness;
global uniform float snow_cover;
varying vec2 plan;
varying float up;
void vertex() {
	plan = VERTEX.xz;
	up = NORMAL.y;
}
float n2(vec2 p) { return fract(sin(dot(floor(p), vec2(12.9898, 78.233))) * 43758.5453); }
void fragment() {
	vec2 auv = vec2(plan.x / chunk_size, (plan.y + chunk_size) / chunk_size);
	vec3 a = texture(aerial, clamp(auv, vec2(0.001), vec2(0.999))).rgb;
	float d = dot(texture(detail, plan * detail_scale).rgb, vec3(0.333));
	// photo already contains sunlight: pull exposure down, add a little contrast/saturation back
	a = pow(a, vec3(1.18)) * 0.82;
	float l = dot(a, vec3(0.299, 0.587, 0.114));
	a = mix(vec3(l), a, 1.18);
	vec3 col = a * mix(1.0, 0.75 + d * 0.6, detail_strength);
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
