extends Node3D
## 3D grass (owner, 2026-11-21): real blades on every lawn, park and grass area near the camera.
## Each streamed chunk keeps its grass triangles (meta "grass_tris", from city_streamer.gd). Around the camera the
## grass is split into 8 m cells; cells within RADIUS get a MultiMeshInstance3D of blade clumps scattered over the
## grass triangles (area-weighted, seeded per cell so it never changes), denser close to the camera. Cells are
## children of their chunk, so they move with origin rebasing and vanish with the chunk. shaders/grass.gdshader
## sways and fades the blades. Off with --no-grass.

const CELL := 8.0
const RADIUS := 40.0
const NEAR_DENSITY := 18.0     # clumps per m2 within 12 m: a full lawn, not tufts
const FAR_DENSITY := 5.0       # clumps per m2 at the edge
const MAX_PER_CELL := 1600

var main: Node = null
var enabled := true
var _mesh: ArrayMesh = null
var _mat: ShaderMaterial = null
var _chunks := {}              # chunk root -> {cell key: PackedVector3Array (local tris)}
var _blocks := {}              # chunk root -> {cell key: PackedVector3Array (walk/drive tris over the lawn)}
var _live := {}                # [root, key] string -> MultiMeshInstance3D
var _t := 0.0

func _ready() -> void:
	enabled = not OS.get_cmdline_user_args().has("--no-grass")
	_mesh = _clump_mesh()
	_mat = ShaderMaterial.new(); _mat.shader = load("res://shaders/grass.gdshader")
	_mat.set_shader_parameter("fade_start", RADIUS - 12.0); _mat.set_shader_parameter("fade_end", RADIUS)

## One clump: 7 tapered blades, each 3 segments with a forward curve, 0.09-0.2 m tall (a mowed, lush lawn).
func _clump_mesh() -> ArrayMesh:
	var st := SurfaceTool.new(); st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var rng := RandomNumberGenerator.new(); rng.seed = 7
	for b in 7:
		var a := rng.randf() * TAU
		var r := rng.randf() * 0.07
		var base := Vector3(cos(a) * r, 0.0, sin(a) * r)
		var yaw := rng.randf() * TAU
		var dir := Vector3(cos(yaw), 0.0, sin(yaw))
		var side := Vector3(-dir.z, 0.0, dir.x)
		var hgt := rng.randf_range(0.09, 0.2)
		var w := rng.randf_range(0.009, 0.015)
		var lean := rng.randf_range(0.03, 0.09)
		var pts: Array[Vector3] = []; var ws: Array[float] = []; var vs: Array[float] = []
		for i in 4:
			var t := float(i) / 3.0
			pts.append(base + dir * lean * t * t + Vector3(0.0, hgt * t, 0.0))
			ws.append(w * (1.0 - t * 0.92)); vs.append(t)
		var n := dir.cross(side).normalized()
		for i in 3:
			var p0 := pts[i]; var p1 := pts[i + 1]
			var a0 := p0 - side * ws[i]; var b0 := p0 + side * ws[i]
			var a1 := p1 - side * ws[i + 1]; var b1 := p1 + side * ws[i + 1]
			for q in [[a0, vs[i]], [b0, vs[i]], [b1, vs[i + 1]], [a0, vs[i]], [b1, vs[i + 1]], [a1, vs[i + 1]]]:
				st.set_normal(n); st.set_uv(Vector2(0.5, q[1])); st.add_vertex(q[0])
	return st.commit()

## city_streamer.gd calls this when a chunk is built: bin its grass triangles into cells.
func add_chunk(root: Node3D, tris: PackedVector3Array, block := PackedVector3Array()) -> void:
	if not enabled or tris.size() < 3: return
	_chunks[root] = _bin(tris)
	# blockers go into every cell their bounding box touches (a walk can cross a cell edge)
	var bc := {}
	for i in range(0, block.size() - 2, 3):
		var a := block[i]; var b := block[i + 1]; var c := block[i + 2]
		var x0 := floori(minf(a.x, minf(b.x, c.x)) / CELL); var x1 := floori(maxf(a.x, maxf(b.x, c.x)) / CELL)
		var z0 := floori(minf(a.z, minf(b.z, c.z)) / CELL); var z1 := floori(maxf(a.z, maxf(b.z, c.z)) / CELL)
		if x1 - x0 > 6 or z1 - z0 > 6: continue
		for kx in range(x0, x1 + 1):
			for kz in range(z0, z1 + 1):
				var key := Vector2i(kx, kz)
				if not bc.has(key): bc[key] = PackedVector3Array()
				var arr: PackedVector3Array = bc[key]
				arr.append(a); arr.append(b); arr.append(c); bc[key] = arr
	_blocks[root] = bc

func _bin(tris: PackedVector3Array) -> Dictionary:
	var cells := {}
	for i in range(0, tris.size() - 2, 3):
		var c := (tris[i] + tris[i + 1] + tris[i + 2]) / 3.0
		var key := Vector2i(floori(c.x / CELL), floori(c.z / CELL))
		if not cells.has(key): cells[key] = PackedVector3Array()
		var arr: PackedVector3Array = cells[key]
		arr.append(tris[i]); arr.append(tris[i + 1]); arr.append(tris[i + 2])
		cells[key] = arr
	return cells

static func _inside(p: Vector3, blk: PackedVector3Array) -> bool:
	for i in range(0, blk.size() - 2, 3):
		var a := Vector2(blk[i].x, blk[i].z); var b := Vector2(blk[i + 1].x, blk[i + 1].z); var c := Vector2(blk[i + 2].x, blk[i + 2].z)
		var q := Vector2(p.x, p.z)
		var d1 := (q - b).cross(a - b); var d2 := (q - c).cross(b - c); var d3 := (q - a).cross(c - a)
		if not (((d1 < 0) or (d2 < 0) or (d3 < 0)) and ((d1 > 0) or (d2 > 0) or (d3 > 0))): return true
	return false

func _process(dt: float) -> void:
	if not enabled or main == null: return
	_t -= dt
	if _t > 0.0: return
	_t = 0.25
	var cam := get_viewport().get_camera_3d()
	if cam == null: return
	var cp := cam.global_position
	var keep := {}
	for root in _chunks.keys():
		if not is_instance_valid(root):
			_chunks.erase(root); _blocks.erase(root); continue
		var r3: Node3D = root
		var ro := r3.global_position
		# skip whole chunks that are far away
		var csz := 200.0
		var cc := ro + Vector3(csz * 0.5, 0.0, -csz * 0.5)
		if Vector2(cc.x - cp.x, cc.z - cp.z).length() > RADIUS + csz * 0.75: continue
		var cells: Dictionary = _chunks[root]
		for key in cells:
			var centre := ro + Vector3((key.x + 0.5) * CELL, 0.0, (key.y + 0.5) * CELL)
			var d := Vector2(centre.x - cp.x, centre.z - cp.z).length()
			if d > RADIUS + CELL: continue
			var id := "%d|%d|%d" % [root.get_instance_id(), key.x, key.y]
			keep[id] = true
			if not _live.has(id):
				var mmi := _build_cell(r3, cells[key], key, d, _blocks.get(root, {}).get(key, PackedVector3Array()))
				if mmi: _live[id] = mmi
	for id in _live.keys():
		if not keep.has(id):
			var n = _live[id]
			if is_instance_valid(n): n.queue_free()
			_live.erase(id)

func _build_cell(root: Node3D, tris: PackedVector3Array, key: Vector2i, dist: float, blk: PackedVector3Array) -> MultiMeshInstance3D:
	var areas := PackedFloat32Array(); var total := 0.0
	for i in range(0, tris.size() - 2, 3):
		var a := (tris[i + 1] - tris[i]).cross(tris[i + 2] - tris[i]).length() * 0.5
		total += a; areas.append(total)
	if total < 0.5: return null
	var dens := lerpf(NEAR_DENSITY, FAR_DENSITY, clampf((dist - 15.0) / (RADIUS - 15.0), 0.0, 1.0))
	var n := mini(int(total * dens), MAX_PER_CELL)
	if n <= 0: return null
	var rng := RandomNumberGenerator.new(); rng.seed = hash(Vector3i(key.x, key.y, root.get_instance_id() & 0xffff))
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D; mm.use_custom_data = true
	mm.mesh = _mesh
	var xf: Array[Transform3D] = []; var cd: Array[Color] = []
	for i in n:
		var x := rng.randf() * total
		var lo := 0; var hi := areas.size() - 1
		while lo < hi:
			var mid := (lo + hi) >> 1
			if areas[mid] < x: lo = mid + 1
			else: hi = mid
		var t0 := tris[lo * 3]; var t1 := tris[lo * 3 + 1]; var t2 := tris[lo * 3 + 2]
		var u := rng.randf(); var v := rng.randf()
		if u + v > 1.0: u = 1.0 - u; v = 1.0 - v
		var p := t0 + (t1 - t0) * u + (t2 - t0) * v
		var s := rng.randf_range(0.8, 1.25)
		var b := Basis(Vector3.UP, rng.randf() * TAU).scaled(Vector3(s, s * rng.randf_range(0.85, 1.2), s))
		# real yards: thinner, drier patches (worn spots, shade) instead of a perfect carpet
		var wp := p + root.global_position
		var patch := 0.5 + 0.5 * sin(wp.x * 0.23 + 1.7 * sin(wp.z * 0.17)) * cos(wp.z * 0.21 + 0.9 * sin(wp.x * 0.11))
		if rng.randf() > 0.5 + 0.5 * patch: continue
		var tone := clampf(rng.randf() * 0.8 + (1.0 - patch) * 0.45, 0.0, 1.0)
		if blk.size() > 0 and _inside(p, blk): continue      # no grass on front walks and driveways
		xf.append(Transform3D(b, p + Vector3(0, 0.005, 0))); cd.append(Color(tone, 0, 0, 0))
	if xf.is_empty(): return null
	mm.instance_count = xf.size()
	for i in xf.size():
		mm.set_instance_transform(i, xf[i]); mm.set_instance_custom_data(i, cd[i])
	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm; mmi.material_override = _mat
	mmi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	root.add_child(mmi)
	return mmi

## Number of grass clumps currently shown (tests, perf overlay).
func clump_count() -> int:
	var c := 0
	for id in _live:
		var n = _live[id]
		if is_instance_valid(n): c += (n as MultiMeshInstance3D).multimesh.instance_count
	return c
