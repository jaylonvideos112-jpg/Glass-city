shader_type spatial;
// Real Ohio OSIP aerial photo for one 200 m chunk, projected from above (plan UVs from model-space position),
// modulated by a tiling detail texture so surfaces keep texture up close.
uniform sampler2D aerial : source_color, filter_linear_mipmap_anisotropic, repeat_disable;
uniform sampler2D detail : source_color, filter_linear_mipmap, repeat_enable;
uniform float chunk_size = 200.0;
uniform float detail_scale = 0.25;
uniform float detail_strength = 0.35;
varying vec2 plan;
void vertex() {
	plan = VERTEX.xz;
}
void fragment() {
	vec2 auv = vec2(plan.x / chunk_size, (plan.y + chunk_size) / chunk_size);
	vec3 a = texture(aerial, clamp(auv, vec2(0.001), vec2(0.999))).rgb;
	float d = dot(texture(detail, plan * detail_scale).rgb, vec3(0.333));
	// photo already contains sunlight: pull exposure down, add a little contrast/saturation back
	a = pow(a, vec3(1.18)) * 0.82;
	float l = dot(a, vec3(0.299, 0.587, 0.114));
	a = mix(vec3(l), a, 1.18);
	ALBEDO = a * mix(1.0, 0.75 + d * 0.6, detail_strength);
	ROUGHNESS = 0.92;
}
