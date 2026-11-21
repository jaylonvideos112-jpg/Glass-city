shader_type spatial;
// Vehicle body (one vertex-coloured mesh). Vertex alpha picks the surface: 1 = car paint (glossy with a clear
// coat), 0.5 = glass, 0.3 = chrome / metal trim, 0 = rubber, plastic, lights housing.
render_mode diffuse_burley, specular_schlick_ggx;
global uniform float wetness;
varying vec4 vc;
varying vec3 lp;      // model-space position (y up, 0 = ground)
float hh(vec3 p) { return fract(sin(dot(p, vec3(12.9898, 78.233, 37.719))) * 43758.5453); }
float vn3(vec3 p) { vec3 i = floor(p); vec3 f = fract(p); f = f * f * (3.0 - 2.0 * f);
	return mix(mix(mix(hh(i), hh(i + vec3(1,0,0)), f.x), mix(hh(i + vec3(0,1,0)), hh(i + vec3(1,1,0)), f.x), f.y),
		mix(mix(hh(i + vec3(0,0,1)), hh(i + vec3(1,0,1)), f.x), mix(hh(i + vec3(0,1,1)), hh(i + vec3(1,1,1)), f.x), f.y), f.z); }
void vertex() { vc = COLOR; lp = VERTEX; }
void fragment() {
	vec3 c = mix(vc.rgb / 12.92, pow((vc.rgb + 0.055) / 1.055, vec3(2.4)), step(0.04045, vc.rgb));
	float a = vc.a;
	float rough = 0.75, metal = 0.0, cc = 0.0;
	if (a > 0.9) { rough = 0.28; metal = 0.25; cc = 1.0; }
	else if (a > 0.4) { rough = 0.04; metal = 0.65; }
	else if (a > 0.2) { rough = 0.16; metal = 0.95; }
	// lived-in Toledo cars: road grime up the lower body, a few sun-faded / rusty beaters (seeded by the paint
	// colour, so a car keeps its look while it drives)
	float seed = hh(floor(vc.rgb * 31.0));
	if (a > 0.9) {
		float grime = (1.0 - smoothstep(0.25, 0.75, lp.y)) * (0.55 + 0.45 * vn3(lp * 6.0));
		c = mix(c, c * 0.55 + vec3(0.06, 0.05, 0.04), grime * (0.35 + 0.4 * seed));
		rough = mix(rough, 0.7, grime * 0.7); cc *= 1.0 - grime * 0.8;
		if (seed > 0.72) {                   // faded paint and rust round the arches / rockers
			c = mix(c, vec3(dot(c, vec3(0.33))) * 1.15 + 0.05, 0.3);
			cc *= 0.3; rough = max(rough, 0.55);
			float rust = smoothstep(0.62, 0.72, vn3(lp * 4.0 + seed * 9.0)) * (1.0 - smoothstep(0.3, 0.8, lp.y));
			c = mix(c, vec3(0.28, 0.12, 0.05), rust); rough = mix(rough, 0.9, rust); cc *= 1.0 - rust;
		}
	} else if (a > 0.4) {
		c *= 1.0 - 0.25 * (1.0 - smoothstep(0.6, 1.0, lp.y));       // dusty lower glass
	}
	ALBEDO = c;
	ROUGHNESS = mix(rough, rough * 0.4, wetness);
	METALLIC = metal;
	CLEARCOAT = cc;
	CLEARCOAT_ROUGHNESS = 0.08;
}
