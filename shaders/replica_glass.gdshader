shader_type spatial;
// Window glass on hand-made replicas: dark reflective panes; at night a share of windows (per-window id in UV2.x)
// glow with warm interior light, shop windows more so.
uniform vec4 tint : source_color = vec4(0.05, 0.08, 0.11, 1.0);
uniform float night = 0.0;
uniform float occupancy = 0.5;
uniform float shop = 0.0;
void fragment() {
	float id = UV2.x;
	float lit = step(id, mix(0.15, 0.75, occupancy) + shop * 0.5) * night;
	vec3 warm = mix(vec3(1.0, 0.78, 0.5), vec3(0.85, 0.9, 1.0), step(0.7, fract(id * 7.13)));
	ALBEDO = tint.rgb;
	METALLIC = 0.6; ROUGHNESS = 0.06; SPECULAR = 0.6;
	EMISSION = warm * lit * (0.9 + 0.6 * fract(id * 13.7)) * (1.0 + shop);
}
