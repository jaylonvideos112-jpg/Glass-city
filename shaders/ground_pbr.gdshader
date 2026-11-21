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
uniform float wear = 0.0;
uniform int wear_mode = 0;           // 0 asphalt streets, 1 concrete sidewalks (cracks, gum, dirt, weeds)            // asphalt streets: repair patches, crack networks, tar snakes (lived-in look)
global uniform float wetness;
global uniform float snow_cover;
varying vec2 plan;
varying float up;
varying vec2 wpl;

float h2(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float vn(vec2 p) { vec2 i = floor(p); vec2 f = fract(p); f = f * f * (3.0 - 2.0 * f);
	return mix(mix(h2(i), h2(i + vec2(1, 0)), f.x), mix(h2(i + vec2(0, 1)), h2(i + vec2(1, 1)), f.x), f.y); }

void vertex() {
	plan = VERTEX.xz;
	wpl = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xz;
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
	if (wear > 0.0 && wear_mode == 1) {
		// concrete sidewalks: hairline cracks, black gum spots, dirt drifted to the edges, weeds in the cracks
		vec2 g = wpl / 2.2; vec2 gi = floor(g); vec2 gf = fract(g);
		float d1 = 9.0, d2 = 9.0;
		for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++) {
			vec2 o = vec2(float(x), float(y));
			vec2 pnt = o + vec2(h2(gi + o), h2(gi + o + 17.0)) - gf;
			float dd2 = dot(pnt, pnt);
			if (dd2 < d1) { d2 = d1; d1 = dd2; } else if (dd2 < d2) d2 = dd2;
		}
		float edge = sqrt(d2) - sqrt(d1);
		float crack = (1.0 - smoothstep(0.0, 0.025, edge)) * smoothstep(0.45, 0.6, vn(wpl * 0.08 + 4.0));
		a *= 1.0 - crack * 0.6 * wear;
		float weed = crack * smoothstep(0.7, 0.8, vn(wpl * 0.7));
		a = mix(a, vec3(0.2, 0.32, 0.1), weed * wear);
		float gum = step(0.985, h2(floor(wpl * 7.0))) * step(length(fract(wpl * 7.0) - 0.5), 0.3);
		a = mix(a, vec3(0.12, 0.12, 0.11), gum * 0.8 * wear);
		a *= mix(1.0, 0.85, smoothstep(0.55, 0.8, vn(wpl * 0.35 + 9.0)) * wear);     // dirt drifts
	}
	if (wear > 0.0 && wear_mode == 0) {
		// repair patches: one in ~6 cells of 7 m gets a rotated rectangle of darker, smoother fresh asphalt
		vec2 cell = floor(wpl / 7.0); vec2 f = fract(wpl / 7.0) - 0.5;
		float pr = h2(cell + 3.1);
		if (pr < 0.17) {
			float an = h2(cell + 7.7) * 0.5 - 0.25;
			vec2 q = mat2(vec2(cos(an), sin(an)), vec2(-sin(an), cos(an))) * (f - (vec2(h2(cell + 1.3), h2(cell + 2.9)) - 0.5) * 0.3);
			vec2 hs = vec2(0.12 + 0.25 * h2(cell + 4.4), 0.1 + 0.2 * h2(cell + 5.5));
			vec2 dd = abs(q) - hs;
			float inside = step(max(dd.x, dd.y), 0.0);
			float rim = step(abs(max(dd.x, dd.y)), 0.006);
			a = mix(a, a * 0.7 + vec3(0.01), inside * wear);
			r = mix(r, r * 0.8, inside * wear);
			a = mix(a, vec3(0.05), rim * wear * 0.8);
		}
		// alligator cracking in worn zones: voronoi cell edges, only where a slow noise says the road is tired
		vec2 g = wpl / 1.3; vec2 gi = floor(g); vec2 gf = fract(g);
		float d1 = 9.0, d2 = 9.0;
		for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++) {
			vec2 o = vec2(float(x), float(y));
			vec2 pnt = o + vec2(h2(gi + o), h2(gi + o + 17.0)) - gf;
			float dd2 = dot(pnt, pnt);
			if (dd2 < d1) { d2 = d1; d1 = dd2; } else if (dd2 < d2) d2 = dd2;
		}
		float edge = sqrt(d2) - sqrt(d1);
		float zone = smoothstep(0.62, 0.78, vn(wpl * 0.05 + 11.0));
		a *= 1.0 - (1.0 - smoothstep(0.0, 0.06, edge)) * zone * 0.55 * wear;
		// tar snakes: glossy sealed cracks wandering along the road
		float ts = abs(sin(wpl.x * 0.31 + vn(wpl * 0.21) * 6.0 + wpl.y * 0.07));
		float snake = (1.0 - smoothstep(0.0, 0.035, ts)) * smoothstep(0.55, 0.7, vn(wpl * 0.03 + 5.0));
		a = mix(a, vec3(0.03), snake * 0.85 * wear);
		r = mix(r, 0.35, snake * wear);
		// oil drips: soft dark blots
		a *= 1.0 - 0.25 * smoothstep(0.82, 0.95, vn(wpl * 0.6 + 2.0)) * wear;
	}
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
