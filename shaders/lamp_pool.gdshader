shader_type spatial;
// Fake light pool on the ground under a street lamp: additive radial glow, only at night.
render_mode blend_add, unshaded, depth_draw_never, cull_disabled, shadows_disabled;
uniform vec3 color : source_color = vec3(1.0, 0.72, 0.4);
uniform float energy = 0.55;
global uniform float night_level;
global uniform float wetness;
void fragment() {
	float r = length(UV - vec2(0.5)) * 2.0;
	float f = pow(clamp(1.0 - r, 0.0, 1.0), 2.2);
	ALBEDO = color * f * energy * night_level * (1.0 + 0.6 * wetness);
}
