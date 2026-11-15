extends CharacterBody3D
## On-foot third-person character. Camera is handled by main.gd's camera rig.

const WALK := 4.2
const SPRINT := 8.5
const JUMP := 5.2
const GRAVITY := 18.0

var cam_yaw := 0.0        # set by camera rig
var input_dir := Vector2.ZERO   # x = strafe, y = forward (can be driven by demo)
var sprint := false
var want_jump := false
var model: Node3D
var anim_t := 0.0

func _ready() -> void:
	var cs := CollisionShape3D.new()
	var cap := CapsuleShape3D.new()
	cap.radius = 0.35
	cap.height = 1.8
	cs.shape = cap
	cs.position.y = 0.9
	add_child(cs)
	model = Node3D.new()
	add_child(model)
	_build_model()

func _part(mesh: Mesh, color: Color, pos: Vector3, parent: Node3D = null) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	var m := StandardMaterial3D.new()
	m.albedo_color = color
	mi.material_override = m
	mi.position = pos
	(parent if parent else model).add_child(mi)
	return mi

func _box(s: Vector3) -> BoxMesh:
	var b := BoxMesh.new(); b.size = s; return b

func _build_model() -> void:
	# low-poly guy: hoodie, jeans, sneakers
	_part(_box(Vector3(0.5, 0.62, 0.28)), Color(0.15, 0.2, 0.32), Vector3(0, 1.22, 0))   # torso
	var head := SphereMesh.new(); head.radius = 0.15; head.height = 0.32; head.radial_segments = 8; head.rings = 4
	_part(head, Color(0.45, 0.32, 0.24), Vector3(0, 1.7, 0))
	_part(_box(Vector3(0.33, 0.12, 0.33)), Color(0.1, 0.1, 0.1), Vector3(0, 1.84, -0.02))  # cap
	for side in [-1, 1]:
		var leg_pivot := Node3D.new(); leg_pivot.position = Vector3(0.12 * side, 0.92, 0); leg_pivot.name = "leg%d" % side
		model.add_child(leg_pivot)
		_part(_box(Vector3(0.18, 0.8, 0.2)), Color(0.2, 0.25, 0.4), Vector3(0, -0.42, 0), leg_pivot)
		_part(_box(Vector3(0.2, 0.1, 0.32)), Color(0.9, 0.9, 0.9), Vector3(0, -0.85, -0.05), leg_pivot)
		var arm_pivot := Node3D.new(); arm_pivot.position = Vector3(0.33 * side, 1.5, 0); arm_pivot.name = "arm%d" % side
		model.add_child(arm_pivot)
		_part(_box(Vector3(0.14, 0.62, 0.16)), Color(0.15, 0.2, 0.32), Vector3(0, -0.3, 0), arm_pivot)

func _physics_process(dt: float) -> void:
	if not is_physics_processing():
		return
	var fwd := Vector3(-sin(cam_yaw), 0, -cos(cam_yaw))
	var right := Vector3(cos(cam_yaw), 0, -sin(cam_yaw))
	var move := (right * input_dir.x + fwd * input_dir.y)
	if move.length() > 1.0:
		move = move.normalized()
	var spd := SPRINT if sprint else WALK
	var target := move * spd
	var accel := 12.0 if is_on_floor() else 3.0
	velocity.x = move_toward(velocity.x, target.x, accel * spd * dt)
	velocity.z = move_toward(velocity.z, target.z, accel * spd * dt)
	if is_on_floor():
		if want_jump:
			velocity.y = JUMP
	else:
		velocity.y -= GRAVITY * dt
	want_jump = false
	move_and_slide()
	# face movement direction + simple walk cycle
	var hv := Vector2(velocity.x, velocity.z)
	if hv.length() > 0.3:
		var yaw := atan2(-velocity.x, -velocity.z)
		model.rotation.y = lerp_angle(model.rotation.y, yaw, 1.0 - exp(-12.0 * dt))
		anim_t += dt * hv.length() * 1.6
	else:
		anim_t = lerp(anim_t, round(anim_t / PI) * PI, 0.2)
	var sw := sin(anim_t) * 0.6
	for side in [-1, 1]:
		model.get_node("leg%d" % side).rotation.x = sw * side
		model.get_node("arm%d" % side).rotation.x = -sw * side * 0.8
