// Per-building parametric facade (downtown "exact" buildings).
// Per-vertex inputs written by tools/build_city.py:
//   UV      = (metres along the wall, metres above the facade base)
//   UV2     = (floor height m, bay width m for this wall)
//   COLOR   = wall colour (rgb), a = wall material: 0 brick, .25 stone/limestone, .5 concrete/precast, .75 metal panel, 1 glass curtain wall
//   CUSTOM0 = (window width fraction of bay, window height fraction of floor, storefront base height m, style + glass*8)
//             style: 0 punched windows, 1 ribbon windows, 2 curtain-wall grid, 3 vertical piers (deco), 4 blank wall,
//                    5 arched punched windows, 6 blank precast panels (2 per floor, joints on the bay grid)
//             glass: 0 dark grey, 1 blue, 2 green, 3 bronze, 4 black, 5 silver mirror
shader_type spatial;
render_mode blend_mix, cull_back, diffuse_burley, specular_schlick_ggx;

uniform sampler2D noise_tex : hint_default_white, filter_linear_mipmap, repeat_enable;
uniform float night = 0.0;

varying vec4 c0;
varying vec2 fb;

const vec3 GLASS[6] = vec3[](vec3(0.16, 0.19, 0.22), vec3(0.12, 0.23, 0.29), vec3(0.20, 0.33, 0.30),
                             vec3(0.30, 0.24, 0.17), vec3(0.06, 0.07, 0.08), vec3(0.55, 0.60, 0.64));

void vertex() {
	c0 = CUSTOM0;
	fb = UV2;
}

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

void fragment() {
	vec2 m = UV;                       // metres
	float fh = max(fb.x, 2.0), bw = max(fb.y, 0.8);
	float ww = c0.x, wh = c0.y, base = c0.z;
	int style = int(mod(c0.w, 8.0) + 0.01);
	int gl = int(floor(c0.w / 8.0) + 0.01);
	vec3 wall = pow(COLOR.rgb, vec3(2.2));          // hex colours are sRGB; albedo is linear
	float wmat = COLOR.a;
	vec3 glass = pow(GLASS[clamp(gl, 0, 5)], vec3(2.2));
	float n = texture(noise_tex, m * 0.37).r;
	// wall surface detail by material
	vec3 col = wall * (0.92 + 0.12 * n);
	if (wmat < 0.12) {                 // brick coursing
		vec2 b = m * vec2(1.0 / 0.21, 1.0 / 0.075);
		b.x += step(1.0, mod(b.y, 2.0)) * 0.5;
		vec2 f = fract(b);
		vec2 fw = fwidth(b);
		float fade = clamp(1.6 - 2.2 * max(fw.x, fw.y), 0.0, 1.0);   // pattern finer than ~2 px -> its average
		float mortar = clamp(step(f.x, 0.06) + step(f.y, 0.14), 0.0, 1.0);
		float pat = mix(1.0, 0.78, mortar) * (0.9 + 0.2 * hash(floor(b)));
		col *= mix(0.955, pat, fade);
	} else if (wmat < 0.37) {          // stone blocks
		vec2 b = m * vec2(1.0 / 1.2, 1.0 / 0.6); b.x += step(1.0, mod(b.y, 2.0)) * 0.5;
		vec2 f = fract(b); vec2 fw = fwidth(b);
		float fade = clamp(1.6 - 2.2 * max(fw.x, fw.y), 0.0, 1.0);
		col *= mix(0.992, mix(1.0, 0.86, clamp(step(f.x, 0.02) + step(f.y, 0.04), 0.0, 1.0)), fade);
	} else if (wmat < 0.62) {          // precast panel joints at floor lines
		float fade = clamp(1.6 - 2.2 * fwidth(m.y / fh) * 40.0, 0.0, 1.0);
		col *= mix(0.996, mix(1.0, 0.85, step(fract(m.y / fh), 0.025)), fade);
	}
	float rough = 0.85, metal = 0.0, spec = 0.4;
	vec3 emit = vec3(0.0);
	float fy = fract(m.y / fh), fx = fract(m.x / bw);
	vec2 cell = vec2(floor(m.x / bw), floor(m.y / fh));
	float lit = step(0.62, hash(cell + 3.1));
	if (m.y < base && base > 0.5) {
		// storefront: tall glazing between thin piers, dark frame, sign band at the top
		float bx = fract(m.x / max(bw, 3.0));
		float glz = step(0.08, bx) * step(bx, 0.92) * step(0.25, m.y) * step(m.y, base - 0.8);
		float band = step(base - 0.8, m.y);
		col = mix(col * 0.55, glass * 0.9, glz);
		col = mix(col, wall * 0.45, band * 0.6);
		if (glz > 0.5) { rough = 0.08; spec = 0.9; emit = vec3(1.0, 0.85, 0.6) * 0.5 * night; }
	} else if (style == 2 || wmat > 0.88) {
		// curtain wall: glass everywhere, thin mullions on the bay grid, spandrel line at each floor
		float mull = step(fx, 0.025) + step(0.975, fx);
		float spand = step(fy, 0.1);
		col = mix(glass * (0.85 + 0.25 * hash(cell)), wall * 0.6, clamp(mull + spand * 0.7, 0.0, 1.0));
		rough = mix(0.06, 0.5, clamp(mull + spand, 0.0, 1.0)); metal = 0.2; spec = 0.8;
		emit = vec3(1.0, 0.9, 0.7) * 0.6 * night * lit * (1.0 - spand);
	} else if (style == 4 || style == 6) {
		if (style == 6) col *= mix(1.0, 0.8, clamp(step(fx, 0.012) + step(fract(m.y / (fh * 0.5)), 0.02), 0.0, 1.0));
	} else {
		float y0 = (1.0 - wh) * 0.55, y1 = y0 + wh;
		float inx, iny;
		if (style == 1) {                // ribbon: continuous horizontal band
			inx = 1.0; iny = step(y0, fy) * step(fy, y1);
		} else if (style == 3) {         // vertical piers: recessed window strips, dark spandrels
			inx = step(0.5 - ww * 0.5, fx) * step(fx, 0.5 + ww * 0.5); iny = 1.0;
		} else {                         // punched (5 = with a round arch on top)
			inx = step(0.5 - ww * 0.5, fx) * step(fx, 0.5 + ww * 0.5); iny = step(y0, fy) * step(fy, y1);
			if (style == 5) {
				float rx = ww * 0.5 * bw;                          // arch radius in metres
				float ytop = y1 * fh - rx;                          // springline (m within floor)
				vec2 q = vec2((fx - 0.5) * bw, fy * fh - ytop);
				if (q.y > 0.0) inx *= step(length(q), rx);
			}
		}
		float win = inx * iny;
		if (style == 3 && win > 0.5 && (fy < y0 || fy > y1)) {
			col = glass * 0.35 + wall * 0.25;    // spandrel inside the pier recess
		} else if (win > 0.5) {
			float frame = 1.0 - step(0.035, min(min(fx - (0.5 - ww * 0.5), (0.5 + ww * 0.5) - fx) / max(ww, 0.05), 1.0));
			if (style == 1) frame = 0.0;
			float sash = step(abs(fy - (y0 + y1) * 0.5), 0.012);
			col = mix(glass * (0.8 + 0.3 * hash(cell)), vec3(0.85), clamp(frame + sash, 0.0, 1.0));
			rough = 0.08; spec = 0.9; metal = 0.15;
			emit = vec3(1.0, 0.88, 0.65) * 0.7 * night * lit;
		} else {
			// sill / lintel shadow lines
			float sill = step(abs(fy - y0 + 0.02), 0.02) * inx;
			col *= 1.0 - 0.25 * sill;
		}
	}
	ALBEDO = col;
	ROUGHNESS = rough;
	METALLIC = metal;
	SPECULAR = spec;
	EMISSION = emit;
}
