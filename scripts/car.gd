extends VehicleBody3D
## Low-poly sedan. Inputs (throttle/steer/handbrake) are set by main.gd or the demo autopilot.

@export var body_color := Color(0.65, 0.1, 0.1)
@export var model_name := "Vapid Stallion"   # parody badge

const MAX_ENGINE := 5200.0
const MAX_BRAKE := 60.0
const MAX_STEER := 0.55
const TOP_SPEED := 52.0   # m/s (~116 mph)

var throttle := 0.0   # -1..1
var steer_in := 0.0   # -1..1 (positive = left)
var handbrake := false
var driven := false
var lights_on := false            # set by time_of_day.gd (night or dark weather)
var _heads: Array[SpotLight3D] = []
var _hl_mat: StandardMaterial3D
var _tl_mat: StandardMaterial3D
var wheels: Array[VehicleWheel3D] = []

func _ready() -> void:
	mass = 1350.0
	center_of_mass_mode = RigidBody3D.CENTER_OF_MASS_MODE_CUSTOM
	center_of_mass = Vector3(0, -0.25, 0)
	angular_damp = 0.6
	var cs := CollisionShape3D.new()
	var bs := BoxShape3D.new()
	bs.size = Vector3(1.86, 0.7, 4.5)
	cs.shape = bs
	cs.position = Vector3(0, 0.55, 0)
	add_child(cs)
	var cab := CollisionShape3D.new()
	var cbs := BoxShape3D.new()
	cbs.size = Vector3(1.6, 0.55, 2.3)
	cab.shape = cbs
	cab.position = Vector3(0, 1.15, 0.15)
	add_child(cab)
	_build_model()
	for p in [Vector3(-0.82, 0.38, -1.38), Vector3(0.82, 0.38, -1.38), Vector3(-0.82, 0.38, 1.38), Vector3(0.82, 0.38, 1.38)]:
		var w := VehicleWheel3D.new()
		w.position = p
		w.wheel_radius = 0.36
		w.wheel_rest_length = 0.22
		w.suspension_travel = 0.2
		w.suspension_stiffness = 55.0
		w.suspension_max_force = 30000.0
		w.damping_compression = 2.2
		w.damping_relaxation = 3.0
		w.wheel_friction_slip = 2.6
		w.wheel_roll_influence = 0.15
		var front: bool = p.z < 0
		w.use_as_steering = front
		w.use_as_traction = not front
		add_child(w)
		wheels.append(w)
		var tire := MeshInstance3D.new()
		var cyl := CylinderMesh.new()
		cyl.top_radius = 0.36; cyl.bottom_radius = 0.36; cyl.height = 0.26; cyl.radial_segments = 10; cyl.rings = 1
		tire.mesh = cyl
		tire.rotation.z = PI / 2
		var tm := StandardMaterial3D.new(); tm.albedo_color = Color(0.08, 0.08, 0.08)
		tire.material_override = tm
		w.add_child(tire)
		var hub := MeshInstance3D.new()
		var hc := CylinderMesh.new()
		hc.top_radius = 0.2; hc.bottom_radius = 0.2; hc.height = 0.28; hc.radial_segments = 6; hc.rings = 1
		hub.mesh = hc
		hub.rotation.z = PI / 2
		var hm := StandardMaterial3D.new(); hm.albedo_color = Color(0.7, 0.7, 0.72); hm.metallic = 0.8; hm.roughness = 0.3
		hub.material_override = hm
		w.add_child(hub)

func _mat(c: Color, metal := 0.0, rough := 0.5) -> StandardMaterial3D:
	var m := StandardMaterial3D.new(); m.albedo_color = c; m.metallic = metal; m.roughness = rough; return m

func _box(size: Vector3, pos: Vector3, m: Material) -> void:
	var mi := MeshInstance3D.new(); var b := BoxMesh.new(); b.size = size; mi.mesh = b
	mi.position = pos; mi.material_override = m; add_child(mi)

func _build_model() -> void:
	var paint := _mat(body_color, 0.4, 0.35)
	var glass := _mat(Color(0.1, 0.13, 0.17), 0.3, 0.1)
	var dark := _mat(Color(0.06, 0.06, 0.06))
	_box(Vector3(1.86, 0.55, 4.5), Vector3(0, 0.62, 0), paint)            # lower body
	_box(Vector3(1.6, 0.52, 2.2), Vector3(0, 1.15, 0.2), glass)            # greenhouse
	_box(Vector3(1.62, 0.08, 2.0), Vector3(0, 1.44, 0.25), paint)          # roof
	_box(Vector3(1.9, 0.2, 0.3), Vector3(0, 0.45, -2.25), dark)            # front bumper
	_box(Vector3(1.9, 0.2, 0.3), Vector3(0, 0.45, 2.25), dark)             # rear bumper
	var hl := _mat(Color(1, 0.97, 0.85)); hl.emission_enabled = true; hl.emission = Color(1, 0.95, 0.8); hl.emission_energy_multiplier = 0.3
	var tl := _mat(Color(0.8, 0.05, 0.05)); tl.emission_enabled = true; tl.emission = Color(0.9, 0.0, 0.0); tl.emission_energy_multiplier = 0.3
	_hl_mat = hl; _tl_mat = tl
	for s in [-0.65, 0.65]:
		var sp := SpotLight3D.new()
		sp.position = Vector3(s, 0.75, -2.35)
		sp.rotation_degrees = Vector3(-7, 0, 0)
		sp.spot_range = 38.0; sp.spot_angle = 26.0; sp.spot_attenuation = 1.2
		sp.light_color = Color(1.0, 0.95, 0.85); sp.light_energy = 0.0
		sp.shadow_enabled = false
		sp.visible = false
		add_child(sp); _heads.append(sp)
	for s in [-0.65, 0.65]:
		_box(Vector3(0.35, 0.14, 0.05), Vector3(s, 0.75, -2.26), hl)
		_box(Vector3(0.35, 0.14, 0.05), Vector3(s, 0.75, 2.26), tl)
	var badge := Label3D.new()
	badge.text = model_name
	badge.font_size = 24; badge.pixel_size = 0.004
	badge.position = Vector3(0, 0.62, 2.27)
	add_child(badge)

func speed_mps() -> float:
	return linear_velocity.length()

func _physics_process(_dt: float) -> void:
	var fwd_speed := -linear_velocity.dot(global_transform.basis.z)  # +forward (-Z)
	if not driven:
		engine_force = 0.0
		brake = 8.0
		steering = 0.0
		_update_lights()
		return
	var s := speed_mps()
	# steering gets tighter at low speed, gentler at high speed
	var steer_limit: float = lerp(MAX_STEER, 0.14, clamp(s / 40.0, 0.0, 1.0))
	steering = move_toward(steering, steer_in * steer_limit, 0.05)
	brake = 0.0
	if throttle > 0.05:
		if fwd_speed < -1.0:
			brake = MAX_BRAKE * throttle
			engine_force = 0.0
		else:
			var taper: float = clamp(1.0 - s / TOP_SPEED, 0.0, 1.0)
			# VehicleBody3D: negative engine_force drives toward -Z (our forward)
			engine_force = -MAX_ENGINE * throttle * (0.35 + 0.65 * taper)
	elif throttle < -0.05:
		if fwd_speed > 1.0:
			brake = MAX_BRAKE * -throttle
			engine_force = 0.0
		else:
			engine_force = MAX_ENGINE * 0.5 * -throttle
	else:
		engine_force = 0.0
		brake = 1.5
	for w in wheels:
		w.wheel_friction_slip = 1.3 if (handbrake and not w.use_as_steering) else 2.6
	_update_lights()
	if handbrake:
		brake = max(brake, 30.0)

func _update_lights() -> void:
	var braking := brake > 2.0 and driven
	for sp in _heads:
		sp.visible = lights_on and driven
		sp.light_energy = 6.0 if lights_on else 0.0
	_hl_mat.emission_energy_multiplier = 3.0 if lights_on else 0.3
	_tl_mat.emission_energy_multiplier = (4.0 if braking else (1.6 if lights_on else 0.3))

func reset_upright() -> void:
	var yaw := global_rotation.y
	global_transform = Transform3D(Basis(Vector3.UP, yaw), global_position + Vector3(0, 1.5, 0))
	linear_velocity = Vector3.ZERO
	angular_velocity = Vector3.ZERO
