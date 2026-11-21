// Lived-in house windows (Bully-style art direction): every pane of glass on every house paints its own room.
// Each pane picks, from a hash of its world position, a window treatment:
//   curtains (open, half-open or shut, tied back, some with a valance), blinds (white/beige/yellowed, pulled to a
//   random height, the odd crooked slat), a bedsheet or flag hung as a curtain, or bare glass.
// Behind the treatment is a fake room ("interior mapping"): back wall, side walls, floor and ceiling at fixed
// depths, seen with real parallax from the camera, plus dark furniture shapes.
// On top of that: glass reflection (fresnel sky tint plus a painted diagonal streak) and grime in the corners.
// At night (global night_level) some rooms are lit: warm light glows through the curtains and blinds.
// The pane's UV runs 0..1 across the glass (tools/blender/house_parts.py pane_uv). Local +Z points into the house.
shader_type spatial;
render_mode cull_back, diffuse_burley, specular_schlick_ggx;

global uniform float night_level;
uniform float occupancy = 0.55;          // share of rooms lit at night
uniform float pane_w = 0.82;             // metres, for slat and fold spacing (close enough for every pane size)
uniform float pane_h = 1.45;

varying vec3 pos_l;
varying vec3 cam_l;

float h1(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float h2(float s, float k) { return fract(sin(s * 91.3 + k * 17.17) * 43758.5453); }

vec3 pick(float r, vec3 a, vec3 b, vec3 c, vec3 d, vec3 e, vec3 f) {
	if (r < 0.17) return a;
	if (r < 0.34) return b;
	if (r < 0.5) return c;
	if (r < 0.67) return d;
	if (r < 0.84) return e;
	return f;
}

void vertex() {
	pos_l = VERTEX;
	cam_l = (inverse(MODEL_MATRIX) * vec4(CAMERA_POSITION_WORLD, 1.0)).xyz;
}

void fragment() {
	vec2 uv = UV;
	// a pane = one model instance (+ which pane of a mulled pair)
	float seed = h1(floor(NODE_POSITION_WORLD.xz * 3.0) + vec2(round(pos_l.x * 3.0) * 7.31, floor(NODE_POSITION_WORLD.y * 2.0) * 3.7));
	// ---------------- the room behind the glass
	vec3 vd = normalize(pos_l - cam_l);
	vec3 o = pos_l;
	float into = max(vd.z, 0.04);
	float depth = 2.2 + 1.8 * h2(seed, 1.0);
	float tb = (depth - o.z) / into;
	float tf = vd.y < 0.0 ? (-0.85 - o.y) / vd.y : 1e9;           // floor ~0.85 m under the sill
	float tc = vd.y > 0.0 ? (2.05 - o.y) / vd.y : 1e9;            // ceiling
	float tsd = vd.x > 0.0 ? (1.7 - o.x) / vd.x : (-1.7 - o.x) / min(vd.x, -1e-4);
	float t = min(min(tb, tf), min(tc, tsd));
	vec3 hp = o + vd * t;
	vec3 wall = pick(h2(seed, 2.0), vec3(0.72, 0.66, 0.54), vec3(0.62, 0.66, 0.6), vec3(0.6, 0.64, 0.7),
		vec3(0.74, 0.7, 0.62), vec3(0.66, 0.56, 0.46), vec3(0.55, 0.6, 0.5));
	vec3 room = wall;
	if (t == tf) room = vec3(0.32, 0.22, 0.14) * (0.85 + 0.15 * step(0.5, fract(hp.x * 4.0)));      // wood / carpet floor
	else if (t == tc) room = vec3(0.8, 0.78, 0.74);
	else if (t == tsd) room = wall * 0.78;
	else {
		// back wall: a dark couch / dresser shape, a picture frame, a doorway
		float fx = hp.x - (h2(seed, 3.0) - 0.5) * 1.2;
		if (abs(fx) < 0.75 && hp.y < -0.05) room = mix(vec3(0.16, 0.12, 0.1), vec3(0.22, 0.14, 0.12), h2(seed, 4.0));
		float px = hp.x + (h2(seed, 5.0) - 0.5) * 1.6;
		if (abs(px) < 0.22 && abs(hp.y - 0.75) < 0.16) room = vec3(0.24, 0.2, 0.16) + 0.25 * vec3(h2(seed, 6.0), h2(seed, 7.0), 0.3);
		if (h2(seed, 8.0) < 0.35 && abs(hp.x + 1.0) < 0.42 && hp.y < 1.4) room = wall * 0.35;            // doorway to the next room
	}
	room *= 0.35 + 0.65 * clamp(t * 0.0 + 1.0 - (t / 6.0), 0.3, 1.0);
	bool lit = h2(seed, 9.0) < occupancy;
	// ---------------- window treatment
	float kind = h2(seed, 10.0);
	vec3 tcol = vec3(0.0); float cover = 0.0; float glow = 0.0;     // glow = how much light passes at night
	vec3 cur = pick(h2(seed, 11.0), vec3(0.82, 0.78, 0.66), vec3(0.5, 0.14, 0.12), vec3(0.18, 0.24, 0.4),
		vec3(0.78, 0.66, 0.36), vec3(0.42, 0.5, 0.36), vec3(0.9, 0.88, 0.84));
	if (kind < 0.42) {
		// curtains: two panels from the sides, folds, sometimes tied back at 55% height, sometimes a valance
		float open_ = kind < 0.08 ? 0.0 : 0.12 + 0.3 * h2(seed, 12.0);
		bool tied = h2(seed, 13.0) < 0.45;
		float y = uv.y;
		float waist = tied ? 1.0 - 0.75 * exp(-pow((y - 0.5) / 0.22, 2.0)) : 1.0;
		float a = (0.5 - open_) * waist + (tied ? 0.06 : 0.0);
		float d = min(uv.x, 1.0 - uv.x);
		if (d < a) {
			float fold = 0.72 + 0.28 * pow(abs(sin(uv.x * pane_w * 34.0 + y * 1.5)), 0.6);
			tcol = cur * fold; cover = 1.0; glow = 0.55;
		}
		if (h2(seed, 14.0) < 0.4 && y > 0.86) { tcol = cur * (0.8 + 0.2 * abs(sin(uv.x * 30.0))); cover = 1.0; glow = 0.5; }
	} else if (kind < 0.78) {
		// blinds pulled down to a random height; slats; some yellowed; one crooked slat now and then
		float down = 0.25 + 0.75 * h2(seed, 15.0);
		vec3 bc = pick(h2(seed, 16.0), vec3(0.9, 0.89, 0.86), vec3(0.86, 0.82, 0.72), vec3(0.78, 0.72, 0.56),
			vec3(0.9, 0.89, 0.86), vec3(0.7, 0.66, 0.6), vec3(0.84, 0.84, 0.8));
		float y = 1.0 - uv.y;
		if (y < down) {
			float sl = fract(uv.y * pane_h / 0.032);
			float crook = step(0.82, h2(seed, 17.0)) * step(abs(y - down * 0.6), 0.03) * (uv.x - 0.5) * 0.08;
			sl = fract((uv.y + crook) * pane_h / 0.032);
			tcol = bc * (0.68 + 0.32 * smoothstep(0.0, 0.35, sl) * (1.0 - smoothstep(0.75, 1.0, sl)));
			cover = 1.0; glow = 0.75;
			if (abs(y - down) < 0.012) tcol *= 0.6;                     // bottom rail
		}
	} else if (kind < 0.84) {
		// bedsheet / flag hung as a curtain: whole pane, saggy wrinkles
		vec3 sc = pick(h2(seed, 18.0), vec3(0.3, 0.36, 0.6), vec3(0.7, 0.2, 0.18), vec3(0.85, 0.8, 0.7),
			vec3(0.2, 0.3, 0.22), vec3(0.5, 0.42, 0.6), vec3(0.85, 0.6, 0.2));
		tcol = sc * (0.8 + 0.2 * sin(uv.x * 9.0 + sin(uv.y * 5.0) * 2.0)); cover = 1.0; glow = 0.4;
	}
	// day: the room is dim behind glass; treatments catch some daylight
	vec3 inside = mix(room * 0.22, tcol * 0.62, cover);
	// ---------------- glass: fresnel sky tint, painted diagonal streak, grimy corners
	float fres = 0.06 + 0.5 * pow(1.0 - clamp(dot(NORMAL, VIEW), 0.0, 1.0), 4.0);
	vec3 sky = mix(vec3(0.5, 0.58, 0.66), vec3(0.75, 0.8, 0.85), uv.y);
	float streak = smoothstep(0.08, 0.0, abs(uv.x + uv.y * 0.7 - 0.55 - 0.3 * h2(seed, 19.0))) * 0.12;
	vec3 col = mix(inside, sky * (1.0 - night_level * 0.85), fres) + streak * (1.0 - night_level);
	float edge = min(min(uv.x, 1.0 - uv.x), min(uv.y, 1.0 - uv.y));
	col *= 0.82 + 0.18 * smoothstep(0.0, 0.09, edge);
	ALBEDO = col;
	ROUGHNESS = 0.12;
	SPECULAR = 0.55;
	// ---------------- night: lit rooms glow warm through curtains / blinds; unlit stay dark
	if (lit && night_level > 0.01) {
		vec3 lamp = mix(vec3(1.0, 0.72, 0.42), vec3(0.85, 0.85, 1.0), step(0.85, h2(seed, 20.0)));   // a few TV-blue rooms
		vec3 e = mix(room * 1.3, tcol * glow * 1.6 + lamp * 0.15 * glow, cover) * lamp;
		EMISSION = e * night_level * 1.6;
	}
}
