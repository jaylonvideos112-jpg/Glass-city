extends RefCounted
## Weapon models built in code (placeholder art until the Unreal pass, but with real proportions): slides, frames,
## angled grips, trigger guards, sights, rails, barrels, pump forends, curved magazines, stocks, a turned bat, a
## clip-point knife and a grenade with its spoon and pin. Parts are merged into one mesh per material (finish
## metal, black polymer, wood, bright steel, glass/lens). Front is -Z, grip hand at the origin. Cached per look.

static var _cache := {}
static var _mats := {}

static func build(id: String, finish := "#1a1b1e", mods: Array = []) -> MeshInstance3D:
	var key := "%s|%s|%s" % [id, finish, ",".join(mods)]
	var mi := MeshInstance3D.new(); mi.name = "Weapon"
	if _cache.has(key):
		mi.mesh = _cache[key]; return mi
	var modelled := _from_models(id, finish, mods)       # Blender-built (tools/blender/guns.py)
	if modelled:
		_cache[key] = modelled; mi.mesh = modelled; return mi
	var parts := {}        # material key -> SurfaceTool
	var P := func(mat: String) -> SurfaceTool:
		if not parts.has(mat):
			var st := SurfaceTool.new(); st.begin(Mesh.PRIMITIVE_TRIANGLES); parts[mat] = st
		return parts[mat]
	match id:
		"pistol":
			_box(P.call("fin"), Vector3(0.031, 0.034, 0.19), Vector3(0, 0.032, -0.06))                   # slide
			for i in 6: _box(P.call("poly"), Vector3(0.033, 0.024, 0.004), Vector3(0, 0.034, 0.012 + i * 0.007))   # serrations
			_box(P.call("poly"), Vector3(0.029, 0.022, 0.16), Vector3(0, 0.006, -0.05))                  # frame
			_box(P.call("poly"), Vector3(0.008, 0.008, 0.05), Vector3(0, -0.006, -0.11))                 # rail under the barrel
			_box(P.call("poly"), Vector3(0.03, 0.105, 0.046), Vector3(0, -0.055, 0.035), Vector3(0.28, 0, 0))   # grip
			_guard(P.call("poly"), Vector3(0, -0.012, -0.03), 0.028)
			_cyl(P.call("steel"), 0.0055, 0.012, Vector3(0, 0.035, -0.157), Vector3(PI * 0.5, 0, 0))    # muzzle
			_box(P.call("steel"), Vector3(0.004, 0.008, 0.006), Vector3(0, 0.053, -0.145))              # front sight
			_box(P.call("steel"), Vector3(0.022, 0.008, 0.008), Vector3(0, 0.053, 0.028))               # rear sight
			_box(P.call("poly"), Vector3(0.032, 0.008, 0.05), Vector3(0, -0.11, 0.048), Vector3(0.28, 0, 0))   # mag base
		"shotgun":
			_box(P.call("fin"), Vector3(0.042, 0.06, 0.24), Vector3(0, 0.018, -0.02))                   # receiver
			_cyl(P.call("fin"), 0.011, 0.5, Vector3(0, 0.035, -0.39), Vector3(PI * 0.5, 0, 0))          # barrel
			_cyl(P.call("fin"), 0.0105, 0.38, Vector3(0, 0.006, -0.33), Vector3(PI * 0.5, 0, 0))        # mag tube
			_cyl(P.call("poly"), 0.021, 0.17, Vector3(0, 0.008, -0.26), Vector3(PI * 0.5, 0, 0), 10)    # pump
			for i in 5: _cyl(P.call("poly"), 0.0225, 0.008, Vector3(0, 0.008, -0.2 - i * 0.03), Vector3(PI * 0.5, 0, 0), 10)
			_box(P.call("steel"), Vector3(0.006, 0.006, 0.006), Vector3(0, 0.05, -0.63))                # bead sight
			_box(P.call("poly"), Vector3(0.034, 0.1, 0.05), Vector3(0, -0.045, 0.1), Vector3(0.35, 0, 0))   # grip
			_guard(P.call("poly"), Vector3(0, -0.012, 0.03), 0.032)
			_wedge(P.call("wood"), Vector3(0, 0.0, 0.11), 0.33, 0.06, 0.13, 0.045)                       # stock
			_box(P.call("poly"), Vector3(0.046, 0.135, 0.02), Vector3(0, -0.035, 0.445))                 # butt pad
		"rifle":
			_box(P.call("fin"), Vector3(0.034, 0.046, 0.25), Vector3(0, 0.03, -0.03))                   # upper
			for i in 12: _box(P.call("fin"), Vector3(0.024, 0.006, 0.008), Vector3(0, 0.056, -0.14 + i * 0.019))   # top rail
			_box(P.call("fin"), Vector3(0.03, 0.04, 0.17), Vector3(0, -0.005, 0.0))                     # lower
			_cyl(P.call("poly"), 0.024, 0.22, Vector3(0, 0.026, -0.265), Vector3(PI * 0.5, 0, 0), 8)    # handguard
			for i in 6: _box(P.call("poly"), Vector3(0.05, 0.008, 0.012), Vector3(0, 0.026, -0.18 - i * 0.032))   # vents
			_cyl(P.call("steel"), 0.0085, 0.14, Vector3(0, 0.026, -0.44), Vector3(PI * 0.5, 0, 0))      # barrel
			_cyl(P.call("fin"), 0.013, 0.05, Vector3(0, 0.026, -0.53), Vector3(PI * 0.5, 0, 0), 6)      # muzzle brake
			_box(P.call("fin"), Vector3(0.008, 0.035, 0.012), Vector3(0, 0.06, -0.36))                 # front sight post
			_box(P.call("fin"), Vector3(0.024, 0.03, 0.03), Vector3(0, 0.07, 0.06))                    # rear sight
			_box(P.call("poly"), Vector3(0.024, 0.07, 0.036), Vector3(0, -0.05, -0.06), Vector3(-0.12, 0, 0))   # magazine (curved)
			_box(P.call("poly"), Vector3(0.024, 0.06, 0.036), Vector3(0, -0.105, -0.072), Vector3(-0.3, 0, 0))
			_box(P.call("poly"), Vector3(0.03, 0.095, 0.04), Vector3(0, -0.06, 0.07), Vector3(0.38, 0, 0))   # pistol grip
			_guard(P.call("poly"), Vector3(0, -0.03, 0.015), 0.03)
			_cyl(P.call("poly"), 0.014, 0.17, Vector3(0, 0.015, 0.2), Vector3(PI * 0.5, 0, 0))         # buffer tube
			_wedge(P.call("poly_hand"), Vector3(0, 0.0, 0.2), 0.16, 0.05, 0.11, 0.04)                   # stock (hand-built mesh: own surface)
		"bat":
			var prof := [[0.0, 0.019], [0.012, 0.019], [0.02, 0.012], [0.25, 0.014], [0.45, 0.02], [0.6, 0.028], [0.82, 0.034], [0.85, 0.03], [0.86, 0.0]]
			_lathe(P.call("wood"), prof, Vector3(0, 0, 0.12), 14)
			for i in 5: _cyl(P.call("poly"), 0.0155, 0.012, Vector3(0, 0, 0.09 - i * 0.022), Vector3(PI * 0.5, 0, 0), 10)   # grip tape
		"knife":
			_box(P.call("poly"), Vector3(0.018, 0.026, 0.11), Vector3(0, 0, 0.03))                      # handle
			_box(P.call("steel"), Vector3(0.02, 0.03, 0.008), Vector3(0, 0, -0.026))                    # bolster
			_blade(P.call("steel_hand"), Vector3(0, 0.002, -0.03), 0.13, 0.026)
		"grenade":
			_lathe(P.call("fin"), [[0.0, 0.0], [0.006, 0.02], [0.02, 0.03], [0.045, 0.033], [0.07, 0.029], [0.085, 0.017], [0.09, 0.0]], Vector3(0, -0.045, 0), 12, true)
			_box(P.call("steel"), Vector3(0.012, 0.075, 0.006), Vector3(0, 0.0, -0.035), Vector3(0.12, 0, 0))   # spoon
			_cyl(P.call("steel"), 0.012, 0.003, Vector3(0.018, 0.05, 0), Vector3(0, 0, PI * 0.5), 10)   # pin ring
	# attachments
	for m in mods:
		match m:
			"scope":
				_cyl(P.call("poly"), 0.017, 0.15, Vector3(0, 0.09 if id == "rifle" else 0.072, -0.03), Vector3(PI * 0.5, 0, 0), 12)
				_cyl(P.call("poly"), 0.021, 0.035, Vector3(0, 0.09 if id == "rifle" else 0.072, -0.11), Vector3(PI * 0.5, 0, 0), 12)
				_cyl(P.call("lens"), 0.0185, 0.002, Vector3(0, 0.09 if id == "rifle" else 0.072, -0.128), Vector3(PI * 0.5, 0, 0), 12)
				_box(P.call("poly"), Vector3(0.014, 0.025, 0.02), Vector3(0, 0.07 if id == "rifle" else 0.055, -0.03))
			"suppressor":
				var z0: float = {"pistol": -0.2, "rifle": -0.62, "shotgun": -0.7}.get(id, -0.3)
				var y0: float = {"pistol": 0.035, "rifle": 0.026, "shotgun": 0.035}.get(id, 0.03)
				_cyl(P.call("poly"), 0.017 if id != "pistol" else 0.014, 0.17, Vector3(0, y0, z0), Vector3(PI * 0.5, 0, 0), 12)
			"ext_mag":
				if id == "pistol": _box(P.call("poly"), Vector3(0.028, 0.06, 0.04), Vector3(0, -0.13, 0.055), Vector3(0.28, 0, 0))
				else: _box(P.call("poly"), Vector3(0.024, 0.08, 0.034), Vector3(0, -0.18, -0.12), Vector3(-0.5, 0, 0))
			"grip": _box(P.call("poly"), Vector3(0.02, 0.07, 0.024), Vector3(0, -0.03, -0.27 if id == "rifle" else -0.26))
			"flashlight":
				_cyl(P.call("poly"), 0.011, 0.07, Vector3(0.03, 0.01, -0.22 if id != "pistol" else -0.11), Vector3(PI * 0.5, 0, 0), 10)
				_cyl(P.call("lens"), 0.0095, 0.002, Vector3(0.03, 0.01, -0.256 if id != "pistol" else -0.146), Vector3(PI * 0.5, 0, 0), 10)
	var am := ArrayMesh.new()
	for k in parts:
		var st: SurfaceTool = parts[k]
		st.generate_normals()
		st.commit(am)
		am.surface_set_material(am.get_surface_count() - 1, _mat(k, finish))
	_cache[key] = am
	mi.mesh = am
	return mi

const ModelLib := preload("res://scripts/model_lib.gd")

## The weapon + its attachments from assets/models (gun_<id>.glb, att_<mod>_<id>.glb), materials re-bound by name
## (fin/poly/wood/steel/lens) so the store's finishes still apply. null when the base model isn't there.
static func _from_models(id: String, finish: String, mods: Array) -> ArrayMesh:
	var base := ModelLib.mesh("gun_" + id)
	if base == null: return null
	var am := ArrayMesh.new()
	var srcs: Array = [base]
	for m in mods:
		var a := ModelLib.mesh("att_%s_%s" % [m, id])
		if a: srcs.append(a)
	for src in srcs:
		for i in src.get_surface_count():
			var mat: Material = src.surface_get_material(i)
			var k: String = mat.resource_name if mat else "poly"
			am.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, src.surface_get_arrays(i))
			am.surface_set_material(am.get_surface_count() - 1, _mat(k if k in ["fin", "poly", "wood", "steel", "lens"] else "poly", finish))
	return am

static func _mat(k_in: String, finish: String) -> StandardMaterial3D:
	var k := k_in
	k = k.trim_suffix("_hand")          # hand-built surfaces share the look of their base material
	var key := k + "|" + (finish if k == "fin" else "")
	if _mats.has(key): return _mats[key]
	var m := StandardMaterial3D.new()
	match k:
		"fin": m.albedo_color = Color(finish); m.metallic = 0.75; m.roughness = 0.34
		"poly": m.albedo_color = Color(0.055, 0.057, 0.062); m.roughness = 0.72
		"wood": m.albedo_color = Color(0.43, 0.24, 0.11); m.roughness = 0.45; m.metallic_specular = 0.6
		"steel": m.albedo_color = Color(0.72, 0.73, 0.75); m.metallic = 0.95; m.roughness = 0.2
		"lens": m.albedo_color = Color(0.1, 0.2, 0.35); m.metallic = 0.6; m.roughness = 0.03; m.emission_enabled = true; m.emission = Color(0.05, 0.1, 0.2)
	_mats[key] = m
	return m

# ---- primitives (flat shaded, merged by SurfaceTool)
static func _xf(pos: Vector3, rot: Vector3) -> Transform3D:
	return Transform3D(Basis.from_euler(rot), pos)

static func _box(st: SurfaceTool, size: Vector3, pos: Vector3, rot := Vector3.ZERO) -> void:
	var bm := BoxMesh.new(); bm.size = size
	st.append_from(bm, 0, _xf(pos, rot))

static func _cyl(st: SurfaceTool, r: float, h: float, pos: Vector3, rot := Vector3.ZERO, seg := 12) -> void:
	var cm := CylinderMesh.new(); cm.top_radius = r; cm.bottom_radius = r; cm.height = h; cm.radial_segments = seg; cm.rings = 1
	st.append_from(cm, 0, _xf(pos, rot))

## a closed loop under the frame
static func _guard(st: SurfaceTool, c: Vector3, w: float) -> void:
	_box(st, Vector3(0.006, 0.004, w * 1.5), c + Vector3(0, -0.026, 0))
	_box(st, Vector3(0.006, 0.026, 0.004), c + Vector3(0, -0.013, -w * 0.75))

## a butt stock: one tapered block from the receiver (h0 tall) back to the butt (h1 tall), comb level, toe dropping
static func _wedge(st: SurfaceTool, at: Vector3, length: float, h0: float, h1: float, w: float) -> void:
	var hw := w * 0.5
	var top0 := at.y + h0 * 0.5; var bot0 := at.y - h0 * 0.5
	var top1 := at.y + h0 * 0.5 - 0.012; var bot1 := top1 - h1
	var z0 := at.z; var z1 := at.z + length
	var v := [Vector3(-hw, bot0, z0), Vector3(hw, bot0, z0), Vector3(hw, top0, z0), Vector3(-hw, top0, z0),
		Vector3(-hw * 0.92, bot1, z1), Vector3(hw * 0.92, bot1, z1), Vector3(hw * 0.92, top1, z1), Vector3(-hw * 0.92, top1, z1)]
	var faces := [[0, 1, 2, 3], [5, 4, 7, 6], [1, 5, 6, 2], [4, 0, 3, 7], [3, 2, 6, 7], [4, 5, 1, 0]]
	var ctr := Vector3.ZERO
	for p in v: ctr += p
	ctr /= 8.0
	for f in faces:
		var a: Vector3 = v[f[0]]; var b: Vector3 = v[f[1]]; var c: Vector3 = v[f[2]]
		var fc: Vector3 = (a + b + c + v[f[3]]) * 0.25
		var n := (b - a).cross(c - a)
		# Godot's front faces wind clockwise seen from outside: flip the quad if its normal points inward
		var order := [0, 2, 1, 0, 3, 2] if n.dot(fc - ctr) > 0.0 else [0, 1, 2, 0, 2, 3]
		for j in order:
			st.set_uv(Vector2.ZERO); st.add_vertex(v[f[j]])

## a surface of revolution around Z: profile [[z, r], ...] (closed ends if `around_y`, around Y instead)
static func _lathe(st: SurfaceTool, prof: Array, at: Vector3, seg: int, around_y := false) -> void:
	for i in prof.size() - 1:
		var z0: float = prof[i][0]; var r0: float = prof[i][1]; var z1: float = prof[i + 1][0]; var r1: float = prof[i + 1][1]
		for k in seg:
			var a0 := TAU * k / seg; var a1 := TAU * (k + 1) / seg
			var p := [Vector3(cos(a0) * r0, sin(a0) * r0, -z0), Vector3(cos(a0) * r1, sin(a0) * r1, -z1),
				Vector3(cos(a1) * r1, sin(a1) * r1, -z1), Vector3(cos(a1) * r0, sin(a1) * r0, -z0)]
			if around_y:
				for j in 4: p[j] = Vector3(p[j].x, -p[j].z, p[j].y)
			for j in [0, 2, 1, 0, 3, 2]:
				st.set_uv(Vector2.ZERO); st.add_vertex(p[j] + at)

## clip-point blade: flat spine on top, edge curving up to the tip
static func _blade(st: SurfaceTool, at: Vector3, length: float, h: float) -> void:
	var t := 0.0025
	var top := [Vector3(0, h * 0.5, 0), Vector3(0, h * 0.5, -length * 0.7), Vector3(0, h * 0.1, -length)]
	var bot := [Vector3(0, -h * 0.5, 0), Vector3(0, -h * 0.4, -length * 0.6), Vector3(0, h * 0.1, -length)]
	for side in [-1.0, 1.0]:
		var o := Vector3(side * t, 0, 0)
		for i in 2:
			var q := [top[i] + o * (1.0 if i == 0 else 0.6), top[i + 1] + o * 0.2, bot[i + 1] + o * 0.2, bot[i] + o * (1.0 if i == 0 else 0.6)]
			var idx := [0, 1, 2, 0, 2, 3] if side > 0 else [0, 2, 1, 0, 3, 2]
			for j in idx:
				st.set_uv(Vector2.ZERO); st.add_vertex(q[j] + at)
