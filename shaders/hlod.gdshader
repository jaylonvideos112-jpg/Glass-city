// Far-distance city (scripts/hlod.gd): vertex-coloured merged meshes.
// COLOR.rgb = surface colour (sRGB), COLOR.a = 1 on building walls (get lit windows at night), 0 elsewhere.
// night / occupancy are set by time_of_day.gd like the facade shader.
shader_type spatial;
render_mode blend_mix, cull_back, diffuse_burley, specular_disabled;

uniform float night = 0.0;
uniform float occupancy = 0.5;
uniform float gain = 1.08;   // matches the brightness of the detailed materials (which add texture detail)

varying vec3 wpos;
varying vec3 wnrm;

void vertex() {
	// merged meshes carry some degenerate triangles with zero normals: those made NaN speckles in sunlight
	if (!(dot(NORMAL, NORMAL) > 0.0001)) NORMAL = vec3(0.0, 1.0, 0.0);
	wpos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	wnrm = (MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz;
}

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

void fragment() {
	vec3 c = COLOR.rgb;
	c = mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(0.04045, c));   // sRGB -> linear
	ALBEDO = clamp(c * gain, vec3(0.0), vec3(1.0));
	// interpolated normals can cancel to zero on merged geometry (NaN light = speckles)
	if (!(dot(NORMAL, NORMAL) > 0.0001)) NORMAL = VIEW;
	NORMAL = normalize(NORMAL);
	ROUGHNESS = 0.95;
	float wall = COLOR.a * (1.0 - smoothstep(0.3, 0.6, abs(wnrm.y) / max(length(wnrm), 0.001)));
	if (wall > 0.0 && night > 0.0) {
		// window grid: 3.2 m floors, 2.6 m bays along the wall; each window on or off by occupancy
		float along = dot(wpos.xz, normalize(vec2(-wnrm.z, wnrm.x)));
		vec2 cell = vec2(floor(along / 2.6), floor(wpos.y / 3.2));
		vec2 f = vec2(fract(along / 2.6), fract(wpos.y / 3.2));
		float win = step(0.2, f.x) * step(f.x, 0.8) * step(0.3, f.y) * step(f.y, 0.8);
		float lit = step(hash(cell + floor(wpos.xz / 40.0)), occupancy);
		vec3 warm = mix(vec3(1.0, 0.78, 0.45), vec3(0.75, 0.85, 1.0), step(0.8, hash(cell * 1.7)));
		EMISSION = warm * win * lit * night * wall * 1.6;
	}
}
