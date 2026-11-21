shader_type canvas_item;
// "Painted" look (Bully-style test): a 4-sector Kuwahara filter turns photo noise into flat brush areas while
// keeping edges crisp, then a warm, saturated grade with lifted shadows. Full-screen ColorRect under the HUD.
uniform sampler2D screen_tex : hint_screen_texture, filter_linear_mipmap;
uniform int radius : hint_range(1, 6) = 3;
uniform float saturation = 1.22;
uniform float warmth = 0.05;
uniform float shadow_lift = 0.06;
uniform float strength : hint_range(0.0, 1.0) = 1.0;

vec4 sector(vec2 uv, vec2 px, int x0, int x1, int y0, int y1) {
	vec3 m = vec3(0.0); vec3 m2 = vec3(0.0); float n = 0.0;
	for (int y = y0; y <= y1; y++) {
		for (int x = x0; x <= x1; x++) {
			vec3 c = texture(screen_tex, uv + vec2(float(x), float(y)) * px).rgb;
			m += c; m2 += c * c; n += 1.0;
		}
	}
	m /= n; vec3 v = abs(m2 / n - m * m);
	return vec4(m, v.r + v.g + v.b);
}

void fragment() {
	vec2 px = SCREEN_PIXEL_SIZE;
	vec2 uv = SCREEN_UV;
	vec3 orig = texture(screen_tex, uv).rgb;
	vec4 a = sector(uv, px, -radius, 0, -radius, 0);
	vec4 b = sector(uv, px, 0, radius, -radius, 0);
	vec4 c = sector(uv, px, -radius, 0, 0, radius);
	vec4 d = sector(uv, px, 0, radius, 0, radius);
	vec4 best = a;
	if (b.a < best.a) best = b;
	if (c.a < best.a) best = c;
	if (d.a < best.a) best = d;
	vec3 col = best.rgb;
	// grade: lift shadows (soft, sunny-afternoon look), push saturation, warm the mids
	float l = dot(col, vec3(0.299, 0.587, 0.114));
	col = mix(vec3(l), col, saturation);
	col = col + shadow_lift * (1.0 - col) * (1.0 - smoothstep(0.0, 0.5, l));
	col.r += warmth * (1.0 - abs(l - 0.5) * 2.0);
	col.b -= warmth * 0.6 * (1.0 - abs(l - 0.5) * 2.0);
	COLOR = vec4(mix(orig, clamp(col, 0.0, 1.0), strength), 1.0);
}
