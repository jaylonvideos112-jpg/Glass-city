extends RefCounted
## Loads Blender-exported .glb models (assets/models/) as single ArrayMeshes for MultiMesh use.
## Every MeshInstance3D in the scene is baked into one mesh with its node transform; each source surface stays a
## surface with its own material. Optional `swap` maps a material name to a replacement material (e.g. the
## street-light "bulb" glass to the day/night-driven emissive). Returns null when the file is missing.

static var _cache := {}

static func mesh(name: String, swap := {}, yaw := 0.0) -> ArrayMesh:
	var key := name + str(swap.keys()) + str(yaw)
	if _cache.has(key): return _cache[key]
	var path := "res://assets/models/%s.glb" % name
	if not ResourceLoader.exists(path): return null
	var ps: PackedScene = load(path)
	var root := ps.instantiate()
	var out := ArrayMesh.new()
	var rot := Transform3D(Basis(Vector3.UP, yaw), Vector3.ZERO)
	_collect(root, rot, out, swap)
	root.free()
	# textured see-through cards (leaves, shrubs) are alpha-tested, two-sided: sorted blending would flicker
	for si in out.get_surface_count():
		var m := out.surface_get_material(si) as BaseMaterial3D
		if m and m.albedo_texture != null and m.transparency == BaseMaterial3D.TRANSPARENCY_ALPHA:
			m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR; m.alpha_scissor_threshold = 0.4
			m.cull_mode = BaseMaterial3D.CULL_DISABLED
	_cache[key] = out
	return out

static func _collect(n: Node, parent_xf: Transform3D, out: ArrayMesh, swap: Dictionary) -> void:
	var xf := parent_xf
	if n is Node3D: xf = parent_xf * (n as Node3D).transform
	if n is MeshInstance3D and (n as MeshInstance3D).mesh:
		var m: Mesh = (n as MeshInstance3D).mesh
		for s in m.get_surface_count():
			var st := SurfaceTool.new()
			st.create_from(m, s)
			var arr := st.commit_to_arrays()
			var v: PackedVector3Array = arr[Mesh.ARRAY_VERTEX]
			for i in v.size(): v[i] = xf * v[i]
			arr[Mesh.ARRAY_VERTEX] = v
			if arr[Mesh.ARRAY_NORMAL] != null:
				var nn: PackedVector3Array = arr[Mesh.ARRAY_NORMAL]
				for i in nn.size(): nn[i] = (xf.basis * nn[i]).normalized()
				arr[Mesh.ARRAY_NORMAL] = nn
			if arr[Mesh.ARRAY_TANGENT] != null:
				var tg: PackedFloat32Array = arr[Mesh.ARRAY_TANGENT]
				for i in tg.size() / 4:
					var t := (xf.basis * Vector3(tg[i * 4], tg[i * 4 + 1], tg[i * 4 + 2])).normalized()
					tg[i * 4] = t.x; tg[i * 4 + 1] = t.y; tg[i * 4 + 2] = t.z
				arr[Mesh.ARRAY_TANGENT] = tg
			out.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arr)
			var mat: Material = (n as MeshInstance3D).get_active_material(s)
			if mat == null: mat = m.surface_get_material(s)
			if mat and swap.has(mat.resource_name): mat = swap[mat.resource_name]
			out.surface_set_material(out.get_surface_count() - 1, mat)
	for c in n.get_children(): _collect(c, xf, out, swap)
