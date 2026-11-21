shader_type spatial;
render_mode cull_disabled, diffuse_lambert_wrap, specular_disabled;
// 3D grass blades (scripts/grass.gd): tapered, curved blades in clumps, instanced on lawns and parks near the
// camera. UV.y = 0 at the root, 1 at the tip. Sways with a gusty wind; shrinks into the ground near the edge of
// the grass radius so nothing pops. Colours are Bully-style lively greens (dark at the root, sunlit at the tips).
uniform vec3 root_col : source_color = vec3(0.16, 0.30, 0.07);
uniform vec3 tip_col : source_color = vec3(0.36, 0.58, 0.16);
uniform vec3 dry_col : source_color = vec3(0.62, 0.62, 0.30);
uniform float wind = 1.0;
uniform float fade_start = 28.0;
uniform float fade_end = 40.0;
global uniform float snow_cover;

varying float h;
varying float tone;

void vertex() {
	vec3 wp = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	vec3 cam = INV_VIEW_MATRIX[3].xyz;
	float d = length(wp.xz - cam.xz);
	float k = 1.0 - smoothstep(fade_start, fade_end, d);
	h = UV.y;
	tone = INSTANCE_CUSTOM.r;
	// shrink toward the root with distance (no popping at the radius edge)
	VERTEX.y *= k;
	// wind: a slow gust wave across the lawn plus a quick flutter, stronger at the tip
	float g = sin(dot(wp.xz, vec2(0.11, 0.07)) + TIME * 1.3) * 0.5 + 0.5;
	float f = sin(wp.x * 1.7 + wp.z * 1.3 + TIME * 4.1);
	float bend = (0.06 + 0.10 * g + 0.025 * f) * wind * h * h;
	vec3 wdir = (inverse(mat3(MODEL_MATRIX)) * vec3(0.8, 0.0, 0.6));
	VERTEX.xz += wdir.xz * bend;
	// normals tilted up so lawns light softly like a surface, not like paper strips
	NORMAL = normalize(mix(NORMAL, vec3(0.0, 1.0, 0.0), 0.65));
}

void fragment() {
	vec3 tip = mix(tip_col, dry_col, clamp(tone - 0.75, 0.0, 1.0) * 1.6);
	vec3 c = mix(root_col, tip, smoothstep(0.0, 1.0, h));
	c *= 0.88 + 0.24 * tone;
	c = mix(c, vec3(0.92, 0.94, 0.97), clamp(snow_cover * 1.2 - 0.2, 0.0, 1.0) * h);
	ALBEDO = c;
	ROUGHNESS = 0.85;
	BACKLIGHT = vec3(0.35, 0.45, 0.15) * h;
	AO = mix(0.55, 1.0, h);
	AO_LIGHT_AFFECT = 0.6;
}
