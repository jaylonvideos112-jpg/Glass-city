shader_type sky;
// GLASS CITY sky: single-scattering-style atmosphere (deep zenith, bright hazy horizon, warm forward-scatter glow
// around the sun), sun disc with limb darkening, two cloud decks drifting on the wind - sunlit cumulus with
// self-shadowed bases and silver linings, and high cirrus streaks - plus stars and a moon at night.
// Driven by scripts/time_of_day.gd (palette, weather cover/darkness, night) and the Sun/Moon lights.

uniform vec3 zenith_color : source_color = vec3(0.18, 0.36, 0.72);
uniform vec3 horizon_color : source_color = vec3(0.72, 0.8, 0.88);
uniform vec3 ground_color : source_color = vec3(0.35, 0.37, 0.36);
uniform vec3 dusk_color : source_color = vec3(1.0, 0.55, 0.3);
uniform float dusk = 0.0;                 // 0..1 near sunrise/sunset
uniform float night = 0.0;                // 0 day .. 1 night
uniform float cover = 0.35;               // cumulus coverage 0..1
uniform float overcast = 0.0;             // 0..1 grey stratus sheet over everything
uniform float storm = 0.0;                // darkens cloud bases
uniform float cirrus = 0.5;
uniform vec2 wind = vec2(0.006, 0.0025);  // cloud drift (uv / s)
uniform float exposure = 1.0;
uniform sampler2D cloud_noise : filter_linear_mipmap, repeat_enable;

float n(vec2 p) { return texture(cloud_noise, p).r; }

float fbm(vec2 p) {
	float v = 0.0, a = 0.5;
	for (int i = 0; i < 4; i++) { v += a * n(p); p = p * 2.03 + vec2(0.17, 0.31); a *= 0.5; }
	return clamp((v / 0.9375 - 0.5) * 2.6 + 0.5, 0.0, 1.0);    // stretch the noise to use the full 0..1 range
}

float cumulus(vec2 uv, float cov) {
	// big billowing masses: a low-frequency shape, eroded by finer detail mostly at the edges
	float base = fbm(uv * 0.32);
	float thr = mix(0.86, 0.22, cov);
	float shape = smoothstep(thr - 0.05, thr + 0.32, base);
	float detail = fbm(uv * 1.4 + vec2(3.1, 1.7));
	float d = shape - (1.0 - shape * 0.7) * (detail - 0.4) * 0.6;
	return clamp(d, 0.0, 1.0);
}

float hash(vec3 p) { p = fract(p * 0.3183099 + 0.1); p *= 17.0; return fract(p.x * p.y * p.z * (p.x + p.y + p.z)); }

void sky() {
	vec3 d = normalize(EYEDIR);
	vec3 sd = normalize(LIGHT0_DIRECTION);
	float sun_up = clamp(sd.y * 4.0 + 0.4, 0.0, 1.0);
	float mu = dot(d, sd);
	float h = max(d.y, 0.0);

	// --- atmosphere
	float zen = pow(h, 0.38);
	// deepen and saturate toward the zenith (the palette colours are the hazy low-sky values)
	vec3 deep = zenith_color * vec3(0.72, 0.85, 1.08);
	vec3 col = mix(horizon_color, deep, zen);
	// horizon brightening band (thick air path) and Rayleigh-ish blue loss low down
	col += horizon_color * 0.18 * exp(-h * 18.0) * (1.0 - night);
	// warm glow around the sun (Mie forward scatter) and the dusk band along the horizon toward it
	float mie = pow(max(mu, 0.0), 8.0) * 0.35 + pow(max(mu, 0.0), 64.0) * 0.6;
	col += LIGHT0_COLOR * mie * sun_up * (1.0 - overcast * 0.8);
	float toward = pow(max(dot(normalize(d.xz + 1e-4), normalize(sd.xz + 1e-4)), 0.0), 3.0);
	col = mix(col, dusk_color, dusk * exp(-h * 6.0) * (0.35 + 0.65 * toward) * (1.0 - overcast * 0.6));
	if (d.y < 0.0) col = mix(horizon_color * 0.92, ground_color, smoothstep(0.0, 0.25, -d.y));

	// --- night: stars, moon
	if (night > 0.01 && d.y > 0.0) {
		vec3 g = floor(d * 260.0);
		float s = hash(g);
		float star = step(0.9975, s) * pow(hash(g + 7.0), 3.0) * 2.5;
		star *= 0.6 + 0.4 * sin(TIME * (2.0 + s * 5.0) + s * 40.0);
		col += vec3(star) * night * smoothstep(0.02, 0.2, d.y) * (1.0 - overcast);
		vec3 md = normalize(LIGHT1_DIRECTION);
		float m = dot(d, md);
		col += vec3(0.75, 0.8, 0.9) * smoothstep(0.99955, 0.9997, m) * night * 1.6;
		col += vec3(0.25, 0.3, 0.4) * pow(max(m, 0.0), 200.0) * night * 0.6;
	}

	// --- sun disc (limb-darkened), hidden behind thick cloud below
	float disc = smoothstep(0.99985, 0.99993, mu);
	float limb = sqrt(max(0.0, 1.0 - (1.0 - mu) / 0.00015));
	vec3 sun_col = LIGHT0_COLOR * LIGHT0_ENERGY * 18.0 * disc * mix(0.6, 1.0, limb) * (1.0 - night);

	// --- clouds (only above the horizon); project onto a curved deck
	if (d.y > 0.0) {
		float fade = smoothstep(0.0, 0.12, d.y);
		vec2 uv = d.xz / (d.y + 0.12) * 0.55 + wind * TIME;
		float c = cumulus(uv, cover);
		// light through the cloud: density a little way toward the sun (thick = shadowed)
		vec2 to_sun = normalize(sd.xz + 1e-4) * 0.06;
		float c2 = c, c3 = c;
		if (!AT_CUBEMAP_PASS) { c2 = cumulus(uv + to_sun, cover); c3 = cumulus(uv + to_sun * 2.5, cover); }   // lighting probe: cheap
		float lit = exp(-(c2 * 1.6 + c3 * 1.0));
		vec3 sunlight = LIGHT0_COLOR * mix(0.25, 1.0, sun_up) * (1.0 - night);
		vec3 skylight = mix(horizon_color, zenith_color, 0.6);
		vec3 shade = mix(vec3(0.5, 0.53, 0.58), vec3(0.2, 0.21, 0.24), storm) * (0.55 + 0.45 * sun_up);
		// seen from below, the thick cores are the grey bases; thin parts and sunlit flanks glow white
		// puffy relief: the density field read as a height map, lit by the sun
		float gx = 0.0, gy = 0.0;
		if (!AT_CUBEMAP_PASS) {
			float e = 0.025;
			gx = cumulus(uv + vec2(e, 0.0), cover) - c; gy = cumulus(uv + vec2(0.0, e), cover) - c;
		}
		vec3 bn = normalize(vec3(-gx * 9.0, 0.35 + c * 0.4, -gy * 9.0));
		vec3 sl = normalize(vec3(sd.x, max(sd.y, 0.05), sd.z));
		float lam = clamp(dot(bn, sl) * 0.6 + 0.45, 0.0, 1.0);
		float core = pow(c, 1.4);
		float light = mix(lam, lit, 0.35);
		vec3 ccol = mix(shade + skylight * 0.22, sunlight * 1.08 + skylight * 0.12, light);
		ccol = mix(ccol, shade * 0.9 + skylight * 0.15, core * 0.35 * (1.0 - lam));   // thick grey bellies
		// silver lining: thin edges glowing toward the sun
		ccol += LIGHT0_COLOR * pow(max(mu, 0.0), 10.0) * (1.0 - c) * c * 4.0 * sun_up;
		ccol = mix(ccol, dusk_color * 0.9 + vec3(0.1), dusk * 0.55 * (0.4 + 0.6 * toward));
		// night: dark slate clouds, their low undersides faintly lit by the city's sodium glow
		vec3 night_cloud = vec3(0.045, 0.05, 0.065) + vec3(0.09, 0.055, 0.03) * exp(-d.y * 4.0) * (0.5 + 0.5 * core);
		ccol = mix(ccol, night_cloud, night);
		// aerial perspective: far clouds melt into the horizon haze
		float far = 1.0 - exp(-d.y * 7.0);
		ccol = mix(col, ccol, far);
		float a = smoothstep(0.0, 0.55, c) * fade;

		// cirrus: thin streaks high up, stretched along the wind
		vec2 cu = d.xz / (d.y + 0.35) * vec2(0.35, 1.4) + wind * TIME * 0.6 + vec2(11.0, 5.0);
		float ci = smoothstep(0.62, 0.95, fbm(cu)) * smoothstep(0.3, 0.7, fbm(cu * 0.2 + 4.0)) * cirrus * fade * (1.0 - overcast);
		vec3 cicol = mix(vec3(1.0), LIGHT0_COLOR, 0.4) * mix(1.0, 0.1, night);
		col = mix(col, cicol * 0.95, ci * 0.3);

		col += sun_col * (1.0 - a);
		col = mix(col, ccol, a);
		// overcast stratus sheet: soft, slightly textured grey ceiling
		float st = mix(0.75, 1.0, fbm(uv * 0.3 + 20.0));
		vec3 ocol = mix(mix(horizon_color, vec3(0.62, 0.64, 0.68), 0.5) * st * mix(1.0, 0.55, storm), vec3(0.06, 0.055, 0.06) + vec3(0.07, 0.045, 0.025) * st, night);
		col = mix(col, ocol, overcast * fade);
	} else {
		col += sun_col;
	}
	// cheap cubemap pass: radiance doesn't need cloud detail at full strength
	COLOR = col * exposure;
}
