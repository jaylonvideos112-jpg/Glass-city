extends Node
## Hand-made building replicas (tools/blender/replica.py): placed into the streamed chunk that holds their anchor.
## Materials are bound by name to the game's tiling PBR textures; window glass lights up at night per window
## (UV2.x = a random id per window, compared with the time of day's occupancy).
const ModelLib := preload("res://scripts/model_lib.gd")
var main: Node
var by_chunk := {}          # Vector2i -> [ {key, pos} ]
var _mats := {}
var glass_mat: ShaderMaterial

func _ready() -> void:
	main = get_parent()
	var path := "res://data/replicas.json"
	if not FileAccess.file_exists(path): return
	var d = JSON.parse_string(FileAccess.get_file_as_string(path))
	var st = main.streamer
	for r in d.get("replicas", []):
		var pos := Vector3(float(r["anchor"][0]), float(r.get("y", 0.0)), float(r["anchor"][1]))
		var k: Vector2i = st.key_for_world(pos)
		if not by_chunk.has(k): by_chunk[k] = []
		by_chunk[k].append({"key": r["key"], "pos": pos})
	st.chunk_loaded.connect(_on_chunk)
	for k in st.loaded: _on_chunk(k)

func _on_chunk(k: Vector2i) -> void:
	if not by_chunk.has(k): return
	var st = main.streamer
	var root: Node3D = st.loaded[k]
	for r in by_chunk[k]:
		var mesh := _mesh(r["key"])
		if mesh == null: continue
		var mi := MeshInstance3D.new(); mi.mesh = mesh; mi.name = "replica_" + r["key"]
		mi.position = r["pos"] - st.chunk_world_origin(k)
		mi.visibility_range_end = 2600.0
		root.add_child(mi)
		var body := StaticBody3D.new(); body.collision_layer = 1
		var cs := CollisionShape3D.new(); cs.shape = mesh.create_trimesh_shape()
		body.add_child(cs); mi.add_child(body)

static var _cache := {}
func _mesh(key: String) -> ArrayMesh:
	if _cache.has(key): return _cache[key]
	var src := ModelLib.mesh("bld_" + key)
	if src == null: return null
	for i in src.get_surface_count():
		var m: Material = src.surface_get_material(i)
		src.surface_set_material(i, material(m.resource_name if m else ""))
	_cache[key] = src
	return src

## name -> [texture folder in textures/pbr (or ""), tint, roughness, metallic, metres per texture repeat]
const MAT := {
	"limestone": ["large_sandstone_blocks", Color(1.45, 1.4, 1.3), 0.85, 0.0, 3.0],
	"sandstone": ["large_sandstone_blocks", Color(0.95, 0.8, 0.65), 0.85, 0.0, 3.0],
	"brick_buff": ["brick_wall_003", Color(1.12, 1.07, 0.96), 0.85, 0.0, 1.4],
	"brick_tan": ["brick_wall_003", Color(1.0, 0.92, 0.8), 0.85, 0.0, 1.4],
	"brick_red": ["red_brick_03", Color(1, 1, 1), 0.85, 0.0, 2.0],
	"brick_orange": ["brick_wall_003", Color(1.18, 0.8, 0.58), 0.85, 0.0, 1.4],
	"brick_brown": ["brick_wall_001", Color(0.8, 0.7, 0.6), 0.85, 0.0, 2.0],
	"brick_tapestry": ["red_brick_03", Color(0.62, 0.43, 0.36), 0.88, 0.0, 1.45],   # dark red-brown tapestry brick (Waite, Scott)
	"siding_cream": ["hsid", Color(0.92, 0.86, 0.72), 0.75, 0.0, 2.4],
	"siding_blue": ["hsid", Color(0.68, 0.78, 0.84), 0.75, 0.0, 2.4],
	"siding_sage": ["hsid", Color(0.6, 0.62, 0.5), 0.75, 0.0, 2.4],
	"siding_white": ["hsid", Color(0.97, 0.96, 0.93), 0.75, 0.0, 2.4],
	"siding_grey": ["hsid", Color(0.66, 0.66, 0.64), 0.75, 0.0, 2.4],
	"siding_yellow": ["hsid", Color(0.95, 0.85, 0.55), 0.75, 0.0, 2.4],
	"stone_lime": ["hstn", Color(1.05, 1.0, 0.92), 0.9, 0.0, 2.2],
	"stucco": ["hstu", Color(1, 1, 1), 0.9, 0.0, 3.0],
	"terracotta_cream": ["white_sandstone_bricks", Color(1.28, 1.2, 1.0), 0.65, 0.0, 2.5],
	"terracotta": ["white_sandstone_bricks", Color(1.05, 0.9, 0.75), 0.7, 0.0, 2.5],
	"precast_white": ["concrete_wall_008", Color(1.3, 1.3, 1.28), 0.7, 0.0, 3.0],
	"precast": ["concrete_wall_008", Color(1.1, 1.08, 1.04), 0.8, 0.0, 3.0],
	"concrete": ["concrete_wall_008", Color(1, 1, 1), 0.85, 0.0, 3.0],
	"granite_dark": ["", Color(0.16, 0.15, 0.15), 0.35, 0.0, 1.0],
	"marble": ["white_stucco", Color(1.1, 1.1, 1.08), 0.4, 0.0, 3.0],
	"metal_dark": ["", Color(0.1, 0.11, 0.12), 0.35, 0.8, 1.0],
	"metal_light": ["", Color(0.6, 0.62, 0.64), 0.3, 0.85, 1.0],
	"frame_dark": ["", Color(0.07, 0.07, 0.07), 0.5, 0.3, 1.0],
	"frame_white": ["", Color(0.85, 0.85, 0.82), 0.5, 0.0, 1.0],
	"roof_flat": ["", Color(0.28, 0.28, 0.29), 0.95, 0.0, 1.0],
	"paint_cream": ["", Color(0.9, 0.85, 0.68), 0.75, 0.0, 1.0],
	"paint_green": ["", Color(0.12, 0.38, 0.27), 0.6, 0.0, 1.0],
	"paint_red": ["", Color(0.55, 0.1, 0.08), 0.6, 0.0, 1.0],
	"paint_yellow": ["", Color(0.86, 0.66, 0.22), 0.6, 0.0, 1.0],
	"neon_red": ["", Color(0.85, 0.22, 0.2), 0.45, 0.0, 1.0],
	"paint_white": ["white_stucco", Color(1.12, 1.1, 1.05), 0.7, 0.0, 3.0],
	"slate_red": ["box_profile_metal_sheet", Color(0.55, 0.22, 0.16), 0.7, 0.1, 1.5],
	"slate": ["box_profile_metal_sheet", Color(0.32, 0.33, 0.37), 0.75, 0.1, 1.5],
	"shingle": ["", Color(0.24, 0.22, 0.21), 0.9, 0.0, 1.0],
	"copper": ["", Color(0.35, 0.58, 0.5), 0.55, 0.35, 1.0],
	"tile_red": ["box_profile_metal_sheet", Color(0.62, 0.27, 0.17), 0.8, 0.0, 1.0],
	"lead": ["box_profile_metal_sheet", Color(0.48, 0.5, 0.52), 0.5, 0.45, 1.2],
}

func material(name: String) -> Material:
	if _mats.has(name): return _mats[name]
	var m: Material
	if name.begins_with("glass"):
		m = _glass(name)
	else:
		var d: Array = MAT.get(name, ["", Color(0.6, 0.6, 0.6), 0.8, 0.0, 1.0])
		var sm := StandardMaterial3D.new()
		sm.albedo_color = d[1]; sm.roughness = d[2]; sm.metallic = d[3]
		if d[0] != "":
			var base := "res://textures/pbr/%s" % d[0]
			for ext in ["_diff.jpg", "_diff.png", ".jpg", "/diff.jpg"]:
				if ResourceLoader.exists(base + ext): sm.albedo_texture = load(base + ext); break
			for ext in ["_nor.jpg", "_nor.png", "_nor_gl.jpg", "_nor_gl.png"]:
				if ResourceLoader.exists(base + ext): sm.normal_enabled = true; sm.normal_texture = load(base + ext); break
			sm.uv1_scale = Vector3(1.0 / d[4], 1.0 / d[4], 1.0)
			sm.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
		m = sm
	_mats[name] = m
	return m

func _glass(name: String) -> ShaderMaterial:
	var sm := ShaderMaterial.new()
	sm.shader = load("res://shaders/replica_glass.gdshader")
	var tints := {"glass_curtain": Color(0.1, 0.18, 0.26), "glass_teal": Color(0.12, 0.3, 0.32), "glass_dark": Color(0.03, 0.035, 0.04)}
	sm.set_shader_parameter("tint", tints.get(name, Color(0.05, 0.08, 0.11)))
	sm.set_shader_parameter("shop", 1.0 if name == "glass_shop" else 0.0)
	return sm

func set_night(night: float, occupancy: float) -> void:
	for k in _mats:
		var m = _mats[k]
		if m is ShaderMaterial:
			m.set_shader_parameter("night", night); m.set_shader_parameter("occupancy", occupancy)
