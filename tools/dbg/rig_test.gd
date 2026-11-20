extends SceneTree
func _init() -> void:
	var r: RigChar = RigChar.create("m2", {"skin": Color(0.4, 0.3, 0.2)})
	root.add_child(r)
	await process_frame
	var hb := r.skel.find_bone("hand_r"); var tb := r.skel.find_bone("thigh_l")
	for sp in [0.0, 1.4, 3.6, 6.0]:
		var p0: Vector3; var spread := 0.0
		for i in 40:
			r.update(1.0 / 30.0, sp, true, 0.0)
			await process_frame
			var p := r.skel.get_bone_global_pose(tb).basis.y
			if i == 10: p0 = p
			if i > 10: spread = maxf(spread, p.angle_to(p0))
		print("speed ", sp, " thigh swing deg ", rad_to_deg(spread))
	r.set_act(1.0, 0.5)
	for i in 20:
		r.update(1.0 / 30.0, 0.0, true, 0.0); await process_frame
	print("punch hand z ", r.skel.get_bone_global_pose(hb).origin)
	print("anims ", r.player.get_animation_list())
	quit()
