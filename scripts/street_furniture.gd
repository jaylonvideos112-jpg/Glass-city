extends RefCounted
## Street furniture beside the street lamps: fire hydrants, trash cans, benches, newspaper boxes and mailboxes.
## Placed deterministically from each lamp's position (same props every visit), along the curb (the lamp's local X),
## one MultiMesh per kind per chunk. Meshes are vertex-coloured low-poly, built once.

const KINDS := ["hydrant", "trash", "bench", "newsbox", "mailbox"]
static var _meshes := {}
static var _mat: StandardMaterial3D

static func add_to(root: Node3D, lamps: Array) -> void:
	var items := {}
	for k in KINDS: items[k] = []
	for p in lamps:
		var h: int = absi(hash(Vector2i(int(p[1] * 4.0), int(p[2] * 4.0))))
		var b := Basis(Vector3.UP, p[4])
		var base := Vector3(p[1], p[3], p[2])
		# up to two items per lamp, either side along the curb
		for slot in 2:
			var r := (h >> (slot * 8)) & 255
			if r < 90: continue
			var kind: String = ["trash", "hydrant", "bench", "trash", "newsbox", "bench", "mailbox", "hydrant"][r % 8]
			var along := (2.6 + float((r >> 3) % 5) * 0.5) * (1.0 if slot == 0 else -1.0)
			var inset := -1.4 if kind == "bench" else -1.6       # toward the road side (lamp arm points -Z)
			if kind == "hydrant": inset = -1.9
			var pos := base + b * Vector3(along, 0.02, inset + 0.6)
			items[kind].append(Transform3D(b, pos))
	for k in KINDS:
		if items[k].is_empty(): continue
		var mm := MultiMesh.new(); mm.transform_format = MultiMesh.TRANSFORM_3D
		mm.mesh = mesh(k); mm.instance_count = items[k].size()
		for i in items[k].size(): mm.set_instance_transform(i, items[k][i])
		var mmi := MultiMeshInstance3D.new(); mmi.multimesh = mm; mmi.visibility_range_end = 220.0
		mmi.name = "furniture_" + k
		root.add_child(mmi)

static func mesh(kind: String) -> ArrayMesh:
	if _meshes.has(kind): return _meshes[kind]
	if _mat == null:
		_mat = StandardMaterial3D.new(); _mat.vertex_color_use_as_albedo = true; _mat.roughness = 0.6
	var st := SurfaceTool.new(); st.begin(Mesh.PRIMITIVE_TRIANGLES)
	match kind:
		"hydrant":
			var red := Color(0.78, 0.12, 0.08)
			_cyl(st, Vector3(0, 0, 0), 0.17, 0.1, Color(0.3, 0.3, 0.3), 10)
			_cyl(st, Vector3(0, 0.1, 0), 0.13, 0.5, red, 10)
			_cyl(st, Vector3(0, 0.6, 0), 0.15, 0.06, red.darkened(0.2), 10)
			_cyl(st, Vector3(0, 0.66, 0), 0.09, 0.12, red, 8)
			_box(st, Vector3(0.42, 0.09, 0.09), Vector3(0, 0.42, 0), red.darkened(0.1))
			_box(st, Vector3(0.1, 0.1, 0.2), Vector3(0, 0.38, -0.12), Color(0.85, 0.82, 0.75))
		"trash":
			var g := Color(0.12, 0.2, 0.15)
			_cyl(st, Vector3.ZERO, 0.28, 0.92, g, 12)
			_cyl(st, Vector3(0, 0.92, 0), 0.31, 0.06, Color(0.08, 0.08, 0.08), 12)
			for i in 6: _box(st, Vector3(0.04, 0.8, 0.02), Basis(Vector3.UP, TAU * i / 6.0) * Vector3(0, 0.46, -0.285), g.lightened(0.15))
		"bench":
			var wood := Color(0.48, 0.3, 0.16); var iron := Color(0.1, 0.1, 0.11)
			for sx in [-0.7, 0.7]:
				_box(st, Vector3(0.06, 0.45, 0.5), Vector3(sx, 0.22, 0), iron)
				_box(st, Vector3(0.06, 0.5, 0.06), Vector3(sx, 0.7, 0.24), iron)
			for i in 3: _box(st, Vector3(1.6, 0.04, 0.13), Vector3(0, 0.46, -0.17 + i * 0.16), wood)
			for i in 2: _box(st, Vector3(1.6, 0.12, 0.035), Vector3(0, 0.66 + i * 0.17, 0.27), wood)
		"newsbox":
			var bl := Color(0.15, 0.3, 0.6)
			_box(st, Vector3(0.45, 0.06, 0.4), Vector3(0, 0.25, 0), Color(0.1, 0.1, 0.1))
			for sx in [-0.18, 0.18]: _box(st, Vector3(0.04, 0.25, 0.04), Vector3(sx, 0.12, 0), Color(0.1, 0.1, 0.1))
			_box(st, Vector3(0.45, 0.6, 0.4), Vector3(0, 0.58, 0), bl)
			_box(st, Vector3(0.36, 0.26, 0.02), Vector3(0, 0.66, -0.205), Color(0.75, 0.8, 0.85))
		"mailbox":
			var bl := Color(0.08, 0.2, 0.48)
			for sx in [-0.2, 0.2]: _box(st, Vector3(0.05, 0.25, 0.4), Vector3(sx, 0.12, 0), bl.darkened(0.3))
			_box(st, Vector3(0.5, 0.75, 0.45), Vector3(0, 0.62, 0), bl)
			_cyl(st, Vector3(0, 1.0, 0), 0.25, 0.0, bl, 10)
			var rs := Basis(Vector3(0, 0, 1), PI * 0.5)
			for i in 10:     # rounded top
				var a0 := PI * i / 10.0; var a1 := PI * (i + 1) / 10.0
				var p0 := Vector3(cos(a0) * 0.25, 1.0 + sin(a0) * 0.22, 0); var p1 := Vector3(cos(a1) * 0.25, 1.0 + sin(a1) * 0.22, 0)
				var n := Vector3(cos((a0 + a1) * 0.5), sin((a0 + a1) * 0.5), 0)
				for v in [p0 + Vector3(0, 0, -0.225), p1 + Vector3(0, 0, -0.225), p1 + Vector3(0, 0, 0.225), p0 + Vector3(0, 0, -0.225), p1 + Vector3(0, 0, 0.225), p0 + Vector3(0, 0, 0.225)]:
					st.set_color(bl); st.set_normal(n); st.add_vertex(v)
			_box(st, Vector3(0.3, 0.05, 0.02), Vector3(0, 0.95, -0.23), Color(0.7, 0.7, 0.72))
	var am := st.commit()
	am.surface_set_material(0, _mat)
	_meshes[kind] = am
	return am

static func _box(st: SurfaceTool, size: Vector3, c: Vector3, col: Color) -> void:
	var h := size * 0.5
	var faces := [[Vector3(1, 0, 0), Vector3(0, 0, 1), Vector3(0, 1, 0)], [Vector3(-1, 0, 0), Vector3(0, 0, -1), Vector3(0, 1, 0)],
		[Vector3(0, 1, 0), Vector3(1, 0, 0), Vector3(0, 0, 1)], [Vector3(0, -1, 0), Vector3(1, 0, 0), Vector3(0, 0, -1)],
		[Vector3(0, 0, 1), Vector3(-1, 0, 0), Vector3(0, 1, 0)], [Vector3(0, 0, -1), Vector3(1, 0, 0), Vector3(0, 1, 0)]]
	for f in faces:
		var n: Vector3 = f[0]; var u: Vector3 = f[1]; var v: Vector3 = f[2]
		var o := c + n * h; var uu := u * h; var vv := v * h
		var q := [o - uu - vv, o + uu - vv, o + uu + vv, o - uu + vv]
		for i in [0, 2, 1, 0, 3, 2]:
			st.set_color(col); st.set_normal(n); st.add_vertex(q[i])

static func _cyl(st: SurfaceTool, c: Vector3, r: float, h: float, col: Color, n: int) -> void:
	for i in n:
		var a0 := TAU * i / n; var a1 := TAU * (i + 1) / n
		var p0 := Vector3(cos(a0) * r, 0, sin(a0) * r); var p1 := Vector3(cos(a1) * r, 0, sin(a1) * r)
		var nm := Vector3(cos((a0 + a1) * 0.5), 0, sin((a0 + a1) * 0.5))
		if h > 0.0:
			for v in [c + p0, c + p1 + Vector3(0, h, 0), c + p1, c + p0, c + p0 + Vector3(0, h, 0), c + p1 + Vector3(0, h, 0)]:
				st.set_color(col); st.set_normal(nm); st.add_vertex(v)
		var top := c + Vector3(0, h, 0)
		for v in [top, top + p1, top + p0]:
			st.set_color(col.lightened(0.05)); st.set_normal(Vector3.UP); st.add_vertex(v)
