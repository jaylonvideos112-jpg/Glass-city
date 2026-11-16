extends RefCounted
## A road wheel: tyre with rounded shoulders and sidewall lettering band, a 5-spoke alloy rim with a dark barrel
## behind the spokes, and a centre cap. Axis along X, centred at the origin; one ArrayMesh with two surfaces
## (0 rubber, 1 alloy). Cached by radius.
static var _cache := {}
static var _rubber: StandardMaterial3D
static var _alloy: StandardMaterial3D

static func make(r: float, width := 0.24) -> ArrayMesh:
	var key := "%.2f|%.2f" % [r, width]
	if _cache.has(key): return _cache[key]
	if _rubber == null:
		_rubber = StandardMaterial3D.new(); _rubber.albedo_color = Color(0.05, 0.05, 0.055); _rubber.roughness = 0.9
		_alloy = StandardMaterial3D.new(); _alloy.albedo_color = Color(0.72, 0.73, 0.75); _alloy.metallic = 0.9; _alloy.roughness = 0.28
	var N := 28
	var hw := width * 0.5
	var am := ArrayMesh.new()
	# --- tyre: tread + rounded shoulders + sidewalls (inner radius = rim)
	var st := SurfaceTool.new(); st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var rim_r := r * 0.66
	# profile across the tread from -x to +x: [x, radius, normal x, normal r]
	var prof := [[-hw, rim_r, -1.0, 0.0], [-hw, r * 0.9, -0.9, 0.3], [-hw * 0.82, r * 0.985, -0.4, 0.9], [-hw * 0.6, r, 0.0, 1.0],
		[hw * 0.6, r, 0.0, 1.0], [hw * 0.82, r * 0.985, 0.4, 0.9], [hw, r * 0.9, 0.9, 0.3], [hw, rim_r, 1.0, 0.0]]
	for i in N:
		var a0 := TAU * i / N; var a1 := TAU * (i + 1) / N
		for k in prof.size() - 1:
			var p0: Array = prof[k]; var p1: Array = prof[k + 1]
			var v := [_pt(p0, a0), _pt(p1, a0), _pt(p1, a1), _pt(p0, a1)]
			var n := [_nm(p0, a0), _nm(p1, a0), _nm(p1, a1), _nm(p0, a1)]
			for j in [0, 2, 1, 0, 3, 2]:
				st.set_normal(n[j]); st.add_vertex(v[j])
	st.commit(am)
	am.surface_set_material(0, _rubber)
	# --- alloy: dark barrel disc, 5 spokes, outer lip ring, centre cap (both sides so it reads either way round)
	var sa := SurfaceTool.new(); sa.begin(Mesh.PRIMITIVE_TRIANGLES)
	for side: float in [-1.0, 1.0]:
		var x: float = side * (hw - 0.03)
		# lip ring
		for i in N:
			var a0 := TAU * i / N; var a1 := TAU * (i + 1) / N
			var q := [Vector3(x, cos(a0) * rim_r, sin(a0) * rim_r), Vector3(x, cos(a1) * rim_r, sin(a1) * rim_r),
				Vector3(x, cos(a1) * rim_r * 0.88, sin(a1) * rim_r * 0.88), Vector3(x, cos(a0) * rim_r * 0.88, sin(a0) * rim_r * 0.88)]
			_quad(sa, q, Vector3(side, 0, 0))
			# recessed barrel (dark-ish metal look comes from the angle) between the spokes
			var b := [Vector3(x - side * 0.06, cos(a0) * rim_r * 0.88, sin(a0) * rim_r * 0.88), Vector3(x - side * 0.06, cos(a1) * rim_r * 0.88, sin(a1) * rim_r * 0.88),
				Vector3(x - side * 0.06, cos(a1) * r * 0.12, sin(a1) * r * 0.12), Vector3(x - side * 0.06, cos(a0) * r * 0.12, sin(a0) * r * 0.12)]
			_quad(sa, b, Vector3(side, 0, 0) * 0.3 + Vector3(0, cos((a0 + a1) * 0.5), sin((a0 + a1) * 0.5)) * 0.2)
		for k in 5:        # spokes: tapered, slightly dished
			var a := TAU * k / 5.0
			var d := Vector3(0, cos(a), sin(a)); var t := Vector3(0, -sin(a), cos(a))
			var w0 := r * 0.11; var w1 := r * 0.07
			var q2 := [Vector3(x - side * 0.01, 0, 0) + d * r * 0.14 - t * w0, Vector3(x - side * 0.04, 0, 0) + d * rim_r * 0.9 - t * w1,
				Vector3(x - side * 0.04, 0, 0) + d * rim_r * 0.9 + t * w1, Vector3(x - side * 0.01, 0, 0) + d * r * 0.14 + t * w0]
			_quad(sa, q2, Vector3(side, 0, 0))
		# centre cap
		for i in 10:
			var a0 := TAU * i / 10.0; var a1 := TAU * (i + 1) / 10.0
			var c := Vector3(x + side * 0.005, 0, 0)
			var tri := [c, c + Vector3(0, cos(a0), sin(a0)) * r * 0.15, c + Vector3(0, cos(a1), sin(a1)) * r * 0.15]
			for p in [tri[0], tri[1], tri[2], tri[0], tri[2], tri[1]]:
				sa.set_normal(Vector3(side, 0, 0)); sa.add_vertex(p)
	sa.commit(am)
	am.surface_set_material(1, _alloy)
	_cache[key] = am
	return am

static func _pt(p: Array, a: float) -> Vector3:
	return Vector3(p[0], cos(a) * p[1], sin(a) * p[1])

static func _nm(p: Array, a: float) -> Vector3:
	return Vector3(p[2], cos(a) * p[3], sin(a) * p[3]).normalized()

static func _quad(st: SurfaceTool, q: Array, n: Vector3) -> void:
	for j in [0, 1, 2, 0, 2, 3, 0, 2, 1, 0, 3, 2]:     # double-sided: cheap and never shows a hole
		st.set_normal(n.normalized()); st.add_vertex(q[j])
