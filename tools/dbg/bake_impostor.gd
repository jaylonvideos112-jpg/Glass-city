extends SceneTree
## Bake a billboard impostor of a high-poly model (e.g. a Poly Haven tree): renders it with a transparent
## background from the side, orthographic, and saves an RGBA PNG. usage:
## godot --path . --script tools/dbg/bake_impostor.gd -- <gltf path> <out.png> [size] [yaw_deg]
func _init() -> void:
	var a := OS.get_cmdline_user_args()
	var src: String = a[0]; var out: String = a[1]
	var px: int = int(a[2]) if a.size() > 2 else 1024
	var yaw: float = deg_to_rad(float(a[3])) if a.size() > 3 else 0.0
	var doc := GLTFDocument.new(); var st := GLTFState.new()
	if doc.append_from_file(src, st) != OK: push_error("load failed"); quit(1); return
	var scene: Node3D = doc.generate_scene(st)
	var vp := SubViewport.new(); vp.size = Vector2i(px, px); vp.transparent_bg = true
	vp.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	vp.own_world_3d = true
	root.add_child(vp)
	vp.add_child(scene)
	scene.rotation.y = yaw
	# bounds
	var aabb := AABB(); var first := true
	for mi in scene.find_children("*", "MeshInstance3D", true, false):
		var bb: AABB = (mi as MeshInstance3D).global_transform * (mi as MeshInstance3D).get_aabb()
		aabb = bb if first else aabb.merge(bb); first = false
	print("aabb ", aabb)
	var env := Environment.new(); env.background_mode = Environment.BG_CLEAR_COLOR
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR; env.ambient_light_color = Color(0.75, 0.8, 0.85); env.ambient_light_energy = 0.9
	var we := WorldEnvironment.new(); we.environment = env; vp.add_child(we)
	var sun := DirectionalLight3D.new(); sun.rotation_degrees = Vector3(-50, 35, 0); sun.light_energy = 1.1; vp.add_child(sun)
	var cam := Camera3D.new(); cam.projection = Camera3D.PROJECTION_ORTHOGONAL
	var span: float = maxf(aabb.size.y, maxf(aabb.size.x, aabb.size.z)) * 1.6
	cam.size = span
	var c := aabb.get_center()
	cam.position = Vector3(0.0, c.y, 50.0); cam.near = 1.0; cam.far = 200.0
	vp.add_child(cam); cam.current = true
	for i in 8: await process_frame
	await RenderingServer.frame_post_draw
	var img := vp.get_texture().get_image()
	img.save_png(out)
	print("saved ", out, " span ", span, " h ", aabb.size.y, " base_y ", aabb.position.y, " center_x ", c.x)
	quit()
