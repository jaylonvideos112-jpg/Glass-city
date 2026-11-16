extends CharacterBody3D
## On-foot third-person character. Camera is handled by main.gd's camera rig.

const WALK := 4.2
const SPRINT := 8.5
const JUMP := 5.2
const GRAVITY := 18.0

var cam_yaw := 0.0        # set by camera rig
var input_dir := Vector2.ZERO   # x = strafe, y = forward (can be driven by demo)
var sprint := false
var needs: Node = null          # needs.gd (stamina limits sprinting, fitness speeds it up)
var want_jump := false
var model: Node3D
var anim_t := 0.0
var move_mult := 1.0            # combat.gd slows you while you swing or guard
var crouch_mult := 1.0          # weapons.gd: crouched in cover
var aim_mult := 1.0             # weapons.gd: aiming
var cover_n := Vector3.ZERO     # weapons.gd: in cover, the wall's outward normal (you slide along it, not into it)
var _fall_v := 0.0              # fastest downward speed since leaving the ground
signal hurt(amount: float, cause: String)

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

const Humans := preload("res://scripts/humans.gd")
var _body: MeshInstance3D
var seated_mesh: ArrayMesh      # same person without legs, for the driver's seat

## the protagonist: dark bomber jacket over a grey tee, dark jeans, white sneakers, short hair and a beard
func _build_model() -> void:
	var look := {"h": 1.04, "w": 1.08, "skin": Color(0.42, 0.29, 0.21), "hair": Color(0.08, 0.06, 0.05),
		"top": Color(0.55, 0.56, 0.58), "top2": Color(0.12, 0.15, 0.22), "bottom": Color(0.14, 0.18, 0.28),
		"shoe": Color(0.93, 0.93, 0.92), "sleeves": 2, "legs": 0, "hair_style": 0, "beard": true}
	var mesh := Humans.build(look)
	var mat := ShaderMaterial.new(); mat.shader = load("res://shaders/pedestrian.gdshader")
	mesh.surface_set_material(0, mat)
	look["seated"] = true
	seated_mesh = Humans.build(look); seated_mesh.surface_set_material(0, mat)
	_body = MeshInstance3D.new(); _body.mesh = mesh; _body.name = "Body"
	model.add_child(_body)

func _physics_process(dt: float) -> void:
	if not is_physics_processing():
		return
	var fwd := Vector3(-sin(cam_yaw), 0, -cos(cam_yaw))
	var right := Vector3(cos(cam_yaw), 0, -sin(cam_yaw))
	var move := (right * input_dir.x + fwd * input_dir.y)
	if move.length() > 1.0:
		move = move.normalized()
	if cover_n != Vector3.ZERO:
		move -= cover_n * move.dot(cover_n)            # along the wall only
		move *= 0.6
	var can_run: bool = needs == null or needs.can_sprint()
	var spd: float = (SPRINT * (needs.sprint_mult() if needs else 1.0)) if (sprint and can_run) else WALK
	var target := move * spd * move_mult * crouch_mult * aim_mult
	var accel := 12.0 if is_on_floor() else 3.0
	velocity.x = move_toward(velocity.x, target.x, accel * spd * dt)
	velocity.z = move_toward(velocity.z, target.z, accel * spd * dt)
	if is_on_floor():
		if want_jump:
			velocity.y = JUMP
	else:
		velocity.y -= GRAVITY * dt
	want_jump = false
	if not is_on_floor(): _fall_v = minf(_fall_v, velocity.y)
	move_and_slide()
	if is_on_floor() and _fall_v < -9.0:          # a hard landing hurts (about a one-storey drop and up)
		hurt.emit((-_fall_v - 9.0) * 7.0, "fall")
	if is_on_floor(): _fall_v = 0.0
	# face movement direction + simple walk cycle
	var hv := Vector2(velocity.x, velocity.z)
	if hv.length() > 0.3:
		var yaw := atan2(-velocity.x, -velocity.z)
		model.rotation.y = lerp_angle(model.rotation.y, yaw, 1.0 - exp(-12.0 * dt))
		anim_t += dt * hv.length() * 1.6
	else:
		anim_t = lerp(anim_t, round(anim_t / PI) * PI, 0.2)
	_body.set_instance_shader_parameter("phase", anim_t)
	_body.set_instance_shader_parameter("swing", clampf(hv.length() / 4.0, 0.0, 1.3))
