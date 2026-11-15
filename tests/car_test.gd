extends SceneTree
var car
var t := 0.0
func _initialize():
	var root := Node3D.new()
	get_root().add_child(root)
	var body := StaticBody3D.new()
	var cs := CollisionShape3D.new()
	var b := BoxShape3D.new(); b.size = Vector3(2000, 1, 2000)
	cs.shape = b; cs.position.y = -0.5
	body.add_child(cs); root.add_child(body)
	car = load("res://scripts/car.gd").new()
	root.add_child(car)
	car.global_position = Vector3(0, 1.0, 0)
	car.driven = true
func _physics_process(dt):
	t += dt
	if t < 1.0:
		car.throttle = 0.0
	elif t < 6.0:
		car.throttle = 1.0; car.steer_in = 0.0
	elif t < 9.0:
		car.throttle = 0.5; car.steer_in = 1.0
	else:
		car.throttle = -1.0; car.steer_in = 0.0
	if int(t * 120) % 60 == 0:
		var fwd = -car.global_transform.basis.z
		print("t=%.1f pos=%s y=%.2f spd=%.1f fwd·v=%.1f yaw=%.2f up=%.2f" % [t, str(car.global_position.snapped(Vector3(0.1,0.1,0.1))), car.global_position.y, car.speed_mps(), fwd.dot(car.linear_velocity), car.global_rotation.y, car.global_transform.basis.y.y])
	if t > 12.0:
		quit()
	return false
