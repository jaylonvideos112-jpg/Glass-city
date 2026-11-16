shader_type spatial;
// Low-poly pedestrian, one draw call. Parts are tagged in UV2.x (0 body, 1/2 legs, 3/4 arms, 5 umbrella) with the
// joint height in UV2.y; the walk cycle swings legs and arms in the vertex shader from per-instance parameters.
render_mode cull_back, diffuse_burley;
instance uniform float phase = 0.0;
instance uniform float swing = 0.0;      // 0 standing .. 1 full stride
instance uniform float umbrella = 0.0;   // 1 = holding an umbrella (rain)
// fighting: act 1 right punch, 2 left punch, 3 kick, 4 guard up, 5 hit reaction, 6 hook, 7 tackle lunge,
// 8 leg sweep, 9 shove, 10 kneeling ground punches, 11 hands up (gives up), 12 windup (telegraph), 13 sidestep;
// act_t 0..1 through the move
instance uniform float act = 0.0;
instance uniform float act_t = 0.0;
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
	int ia = int(act + 0.5);
	float k = sin(clamp(act_t, 0.0, 1.0) * PI);                   // out and back
	float kf = smoothstep(0.0, 0.35, act_t) * (1.0 - smoothstep(0.6, 1.0, act_t));
	if (ia == 1 && part == 4) a = 1.55 * kf;
	if (ia == 2 && part == 3) a = 1.55 * kf;
	if ((ia == 1 || ia == 2) && (part == 3 || part == 4) && a == 0.0) a = 0.45;    // the other fist stays up
	if (ia == 3 && part == 2) a = 1.35 * kf;
	if (ia == 3 && (part == 3 || part == 4)) a = 0.5;
	if (ia == 4 && (part == 3 || part == 4)) a = 0.55;
	if (ia == 5 && (part == 3 || part == 4)) a = -0.4 * k;
	if (ia == 6 && part == 4) a = 1.2 * kf;
	if (ia == 6 && part == 3) a = 0.45;
	if (ia == 7 && (part == 3 || part == 4)) a = 1.35;
	if (ia == 7 && part == 1) a = -0.5 * kf;
	if (ia == 7 && part == 2) a = 0.6 * kf;
	if (ia == 8 && part == 2) a = 1.0 * kf;
	if (ia == 8 && part == 1) a = -0.35 * kf;
	if (ia == 9 && (part == 3 || part == 4)) a = 1.45 * kf;
	if (ia == 10 && (part == 1 || part == 2)) a = -1.4;           // knees bent under
	if (ia == 10 && part == 4) a = 1.1 + 0.7 * kf;
	if (ia == 10 && part == 3) a = 0.5;
	if (ia == 11 && (part == 3 || part == 4)) a = 2.9;           // both hands up
	if (ia == 12 && part == 4) a = -0.6 * k;                      // drawing back the fist
	if (ia == 12 && part == 3) a = 0.5;
	if (ia == 13 && (part == 3 || part == 4)) a = 0.45;
	if (ia == 14 && (part == 3 || part == 4)) a = 1.5;            // long gun at the shoulder
	if (ia == 15 && part == 4) a = 1.57;                          // pistol: arm out
	if (ia == 15 && part == 3) a = 1.3;
	if (part >= 1 && part <= 4) {
		vec3 p = VERTEX; p.y -= pivot;
		float c = cos(a), s = sin(a);
		p = vec3(p.x, p.y * c - p.z * s, p.y * s + p.z * c);
		p.y += pivot;
		VERTEX = p;
	}
	// standing still: breathing, a slow weight shift and a little arm sway (offset per person by phase)
	float idle = 1.0 - clamp(swing * 4.0, 0.0, 1.0);
	if (idle > 0.0) {
		float t = TIME + phase * 3.1;
		float upper = smoothstep(0.85, 1.35, VERTEX.y);
		VERTEX.y += sin(t * 1.7) * 0.007 * idle * upper;
		VERTEX.x += sin(t * 0.45) * 0.018 * idle * clamp(VERTEX.y / 1.7, 0.0, 1.0);
		if (part == 3 || part == 4) {
			vec3 q = VERTEX; q.y -= pivot;
			float b = sin(t * 0.9 + float(part)) * 0.05 * idle;
			q = vec3(q.x, q.y * cos(b) - q.z * sin(b), q.y * sin(b) + q.z * cos(b));
			q.y += pivot; VERTEX = q;
		}
	}
	if (part == 5) VERTEX = mix(vec3(0.0, 1.0, 0.0), VERTEX, umbrella);
	// body twist into a punch, lean back when hit
	if (ia == 1 || ia == 2) VERTEX.z -= kf * 0.12 * clamp((VERTEX.y - 0.9) / 0.6, 0.0, 1.0);
	if (ia == 5) VERTEX.z += k * 0.18 * clamp(VERTEX.y / 1.7, 0.0, 1.0);
	if (ia == 6) VERTEX.x += kf * 0.1 * clamp((VERTEX.y - 0.9) / 0.6, 0.0, 1.0);
	if (ia == 7) VERTEX.z -= kf * 0.55 * clamp((VERTEX.y - 0.5) / 1.2, 0.0, 1.0);    // dive forward low
	if (ia == 7) VERTEX.y -= kf * 0.25 * clamp((VERTEX.y - 0.5) / 1.2, 0.0, 1.0);
	if (ia == 9) VERTEX.z -= kf * 0.15 * clamp((VERTEX.y - 0.9) / 0.6, 0.0, 1.0);
	if (ia == 12) VERTEX.z += 0.06 * k * clamp((VERTEX.y - 0.9) / 0.6, 0.0, 1.0);
	if (ia == 13) VERTEX.x += 0.08 * k * clamp(VERTEX.y / 1.7, 0.0, 1.0);
	// body bob and a slight forward lean at a run
	VERTEX.y += abs(sin(phase)) * 0.03 * min(swing, 1.0);
	if (swing > 1.0) VERTEX.z -= (swing - 1.0) * 0.25 * VERTEX.y * 0.3;
}
void fragment() {
	ALBEDO = col;
	ROUGHNESS = 0.7;
	RIM = 0.35; RIM_TINT = 0.3;     // a soft edge light so people read against dark backgrounds
}
