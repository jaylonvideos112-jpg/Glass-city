shader_type spatial;
// Low-poly pedestrian, one draw call. Parts are tagged in UV2.x (0 body, 1/2 legs, 3/4 arms, 5 umbrella) with the
// joint height in UV2.y; the walk cycle swings legs and arms in the vertex shader from per-instance parameters.
render_mode cull_back, diffuse_burley;
instance uniform float phase = 0.0;
instance uniform float swing = 0.0;      // 0 standing .. 1 full stride
instance uniform float umbrella = 0.0;   // 1 = holding an umbrella (rain)
varying vec3 col;
void vertex() {
	col = mix(COLOR.rgb / 12.92, pow((COLOR.rgb + 0.055) / 1.055, vec3(2.4)), step(0.04045, COLOR.rgb));   // sRGB -> linear
	int part = int(UV2.x + 0.5);
	float pivot = UV2.y;
	float a = 0.0;
	if (part == 1) a = sin(phase) * 0.55 * swing;
	if (part == 2) a = -sin(phase) * 0.55 * swing;
	if (part == 3) a = -sin(phase) * 0.45 * swing;
	if (part == 4) a = sin(phase) * 0.45 * swing * (1.0 - umbrella);
	if (part == 4 && umbrella > 0.5) a = -1.2;                   // umbrella arm raised forward
	if (part >= 1 && part <= 4) {
		vec3 p = VERTEX; p.y -= pivot;
		float c = cos(a), s = sin(a);
		p = vec3(p.x, p.y * c - p.z * s, p.y * s + p.z * c);
		p.y += pivot;
		VERTEX = p;
	}
	if (part == 5) VERTEX = mix(vec3(0.0, 1.0, 0.0), VERTEX, umbrella);
	// body bob and a slight forward lean at a run
	VERTEX.y += abs(sin(phase)) * 0.03 * min(swing, 1.0);
	if (swing > 1.0) VERTEX.z -= (swing - 1.0) * 0.25 * VERTEX.y * 0.3;
}
void fragment() {
	ALBEDO = col;
	ROUGHNESS = 0.8;
}
