shader_type spatial;
// Vehicle body (one vertex-coloured mesh). Vertex alpha picks the surface: 1 = car paint (glossy with a clear
// coat), 0.5 = glass, 0.3 = chrome / metal trim, 0 = rubber, plastic, lights housing.
render_mode diffuse_burley, specular_schlick_ggx;
global uniform float wetness;
varying vec4 vc;
void vertex() { vc = COLOR; }
void fragment() {
	vec3 c = mix(vc.rgb / 12.92, pow((vc.rgb + 0.055) / 1.055, vec3(2.4)), step(0.04045, vc.rgb));
	float a = vc.a;
	float rough = 0.75, metal = 0.0, cc = 0.0;
	if (a > 0.9) { rough = 0.28; metal = 0.25; cc = 1.0; }
	else if (a > 0.4) { rough = 0.04; metal = 0.65; }
	else if (a > 0.2) { rough = 0.16; metal = 0.95; }
	ALBEDO = c;
	ROUGHNESS = mix(rough, rough * 0.4, wetness);
	METALLIC = metal;
	CLEARCOAT = cc;
	CLEARCOAT_ROUGHNESS = 0.08;
}
