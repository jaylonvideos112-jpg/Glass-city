extends RefCounted
## Overhead wires between utility poles (tools/blender/util_poles.py, placed by build_city.py utility_line()).
## Each chunk prop ["wire", x0, z0, x1, z1] (chunk-local pole bases) becomes five sagging cables:
## three primaries off the cross-arm insulators, the secondary triplex and a phone/cable line, each a thin
## 3-sided tube hanging in a catenary-like curve. One mesh per chunk, dark rubber/metal material, no collision.
## The attachment offsets must match util_poles.py.

const Terrain := preload("res://scripts/terrain.gd")
const ATTACH := [[-1.0, 10.12, 0.012, 0.32], [-0.4, 10.12, 0.012, 0.32], [1.0, 10.12, 0.012, 0.32],
	[0.2, 8.0, 0.022, 0.55], [0.18, 6.4, 0.016, 0.7]]      # [x across, height, radius, sag per 38 m]
const SEGS := 10

static var _mat: StandardMaterial3D

static func material() -> StandardMaterial3D:
	if _mat == null:
		_mat = StandardMaterial3D.new()
		_mat.albedo_color = Color(0.07, 0.07, 0.075)
		_mat.roughness = 0.55
		_mat.metallic = 0.2
		_mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	return _mat

## wires: chunk props; origin: the chunk's absolute world origin (for terrain heights). Returns null if empty.
static func build(wires: Array, origin: Vector3) -> MeshInstance3D:
	if wires.is_empty(): return null
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	for w in wires:
		var a := Vector3(w[1], 0, w[2]); var b := Vector3(w[3], 0, w[4])
		var hk := String(w[0]).split(":")        # "wire:<base y0>:<base y1>" (chunk ground, = the poles' bases)
		if hk.size() == 3: a.y = float(hk[1]); b.y = float(hk[2])
		else: a.y = Terrain.height(a + origin); b.y = Terrain.height(b + origin)
		var dir := b - a; dir.y = 0
		var L := dir.length()
		if L < 1.0: continue
		dir /= L
		var across := Vector3(-dir.z, 0, dir.x)      # pole local X for a pole whose run is along dir
		for at in ATTACH:
			var p0: Vector3 = a + across * at[0] + Vector3(0, at[1], 0)
			var p1: Vector3 = b + across * at[0] + Vector3(0, at[1], 0)
			var sag: float = at[3] * pow(L / 38.0, 2.0) * 1.0
			_cable(st, p0, p1, sag, at[2])
	st.generate_normals()
	var mi := MeshInstance3D.new()
	mi.mesh = st.commit()
	mi.material_override = material()
	mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
	mi.visibility_range_end = 320.0
	return mi

static func _cable(st: SurfaceTool, p0: Vector3, p1: Vector3, sag: float, r: float) -> void:
	var pts: Array[Vector3] = []
	for i in SEGS + 1:
		var t := float(i) / SEGS
		pts.append(p0.lerp(p1, t) - Vector3(0, sag * 4.0 * t * (1.0 - t), 0))
	var d := (p1 - p0).normalized()
	var u := Vector3.UP
	var s := d.cross(u).normalized()
	var ring := [u * r, (-u * 0.5 + s * 0.866) * r, (-u * 0.5 - s * 0.866) * r]
	for i in SEGS:
		for k in 3:
			var k2 := (k + 1) % 3
			var a0: Vector3 = pts[i] + ring[k]; var a1: Vector3 = pts[i] + ring[k2]
			var b0: Vector3 = pts[i + 1] + ring[k]; var b1: Vector3 = pts[i + 1] + ring[k2]
			st.add_vertex(a0); st.add_vertex(b0); st.add_vertex(a1)
			st.add_vertex(a1); st.add_vertex(b0); st.add_vertex(b1)
