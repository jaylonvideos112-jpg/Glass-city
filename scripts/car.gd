extends VehicleBody3D
## Player-drivable car. Size and performance come from a roster entry in source_data/vehicles.json (`spec`, set by
## vehicles.gd before the car enters the tree); the body mesh is the same low-poly shape the AI traffic uses.
## Inputs (throttle/steer/handbrake) are set by main.gd or the demo autopilot.
## Damage (Bible section 8): hard hits lower `health` (0-1000), which cuts power and top speed and adds smoke;
## at 0 the engine dies. Repairs at auto shops (vehicles.gd).

@export var body_color := Color(0.65, 0.1, 0.1)
@export var model_name := "Halden Fairway"
var spec: Dictionary = {}          # roster entry
var spec_id := "halden_fairway"
var body_mesh: ArrayMesh = null    # from traffic.vehicle_mesh(); null = simple boxes
var health := 1000.0
var stolen := false
var owned_index := -1              # index in vehicles.gd owned list, or -1
var upgrades := {"engine": 0, "brakes": 0, "suspension": 0}
var _prev_v := Vector3.ZERO
var _smoke: CPUParticles3D = null
var last_hit := 0.0                # size of the last damaging hit (for tests/HUD)

var MAX_ENGINE := 5200.0
var MAX_BRAKE := 60.0
var MAX_STEER := 0.55
var TOP_SPEED := 52.0   # m/s (~116 mph)
var GRIP := 2.6

var throttle := 0.0   # -1..1
var steer_in := 0.0   # -1..1 (positive = left)
var handbrake := false
var driven := false
var lights_on := false            # set by time_of_day.gd (night or dark weather)
var _heads: Array[SpotLight3D] = []
var _hl_mat: StandardMaterial3D
var _tl_mat: StandardMaterial3D
var wheels: Array[VehicleWheel3D] = []
static var surface_grip := 1.0    # set each frame by main.gd from time_of_day.road_grip() (wet/snowy roads)

func apply_spec() -> void:
	if spec.is_empty(): return
	MAX_ENGINE = float(spec["engine"]) * (1.0 + 0.12 * int(upgrades.get("engine", 0)))
	TOP_SPEED = float(spec["top_mps"]) * (1.0 + 0.05 * int(upgrades.get("engine", 0)))
	MAX_BRAKE = 60.0 * (1.0 + 0.2 * int(upgrades.get("brakes", 0)))
	MAX_STEER = float(spec["steer"])
	GRIP = float(spec["grip"]) * (1.0 + 0.06 * int(upgrades.get("suspension", 0)))
	model_name = "%s %s" % [spec["make"], spec["model"]]

func _ready() -> void:
	apply_spec()
	var L: float = float(spec["size"][0]) if not spec.is_empty() else 4.5
	var W: float = float(spec["size"][1]) if not spec.is_empty() else 1.86
	var H: float = float(spec["size"][2]) if not spec.is_empty() else 1.45
	mass = float(spec.get("mass", 1350.0))
	center_of_mass_mode = RigidBody3D.CENTER_OF_MASS_MODE_CUSTOM
	center_of_mass = Vector3(0, -0.25, 0)
	angular_damp = 0.6
	collision_mask = 1 | 2      # also bump into AI traffic (layer 2)
	var cs := CollisionShape3D.new()
	var bs := BoxShape3D.new()
	bs.size = Vector3(W, H * 0.48, L)
	cs.shape = bs
	cs.position = Vector3(0, 0.3 + H * 0.24, 0)
	add_child(cs)
	var cab := CollisionShape3D.new()
	var cbs := BoxShape3D.new()
	cbs.size = Vector3(W * 0.86, H * 0.4, L * 0.5)
	cab.shape = cbs
	cab.position = Vector3(0, 0.3 + H * 0.68, 0.1)
	add_child(cab)
	_build_model()
	var wx: float = W * 0.5 - 0.12; var wz: float = L * 0.31
	var wr: float = 0.36 if H < 1.7 else 0.42
	for p in [Vector3(-wx, 0.38, -wz), Vector3(wx, 0.38, -wz), Vector3(-wx, 0.38, wz), Vector3(wx, 0.38, wz)]:
		var w := VehicleWheel3D.new()
		w.position = p
		w.wheel_radius = wr
		w.wheel_rest_length = 0.22
		w.suspension_travel = 0.2
		w.suspension_stiffness = 55.0
		w.suspension_max_force = 30000.0 * mass / 1350.0
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
		tire.mesh = preload("res://scripts/wheel_mesh.gd").make(wr, 0.25)
		w.add_child(tire)

func _mat(c: Color, metal := 0.0, rough := 0.5) -> StandardMaterial3D:
	var m := StandardMaterial3D.new(); m.albedo_color = c; m.metallic = metal; m.roughness = rough; return m

func _box(size: Vector3, pos: Vector3, m: Material) -> void:
	var mi := MeshInstance3D.new(); var b := BoxMesh.new(); b.size = size; mi.mesh = b
	mi.position = pos; mi.material_override = m; add_child(mi)

func _build_model() -> void:
	if body_mesh != null:
		# the traffic-style body (one mesh: paint + glass + lights) + our own light rig and badge
		var mi := MeshInstance3D.new(); mi.mesh = body_mesh; mi.name = "Body"
		var wr0: float = 0.36 if float(spec["size"][2]) < 1.7 else 0.42
		mi.position.y = 0.38 - 0.22 - wr0 + 0.05     # the mesh's ground (y=0) where the wheels touch down (sits a bit on its springs)
		add_child(mi)
		var L: float = float(spec["size"][0]); var H: float = float(spec["size"][2])
		_hl_mat = _mat(Color(1, 0.97, 0.85)); _hl_mat.emission_enabled = true; _hl_mat.emission = Color(1, 0.95, 0.8)
		_tl_mat = _mat(Color(0.8, 0.05, 0.05)); _tl_mat.emission_enabled = true; _tl_mat.emission = Color(0.9, 0, 0)
		if body_mesh.get_surface_count() >= 3:     # our own light materials, so our brake lights work
			mi.set_surface_override_material(1, _hl_mat); mi.set_surface_override_material(2, _tl_mat)
		for s in [-0.6, 0.6]:
			var sp := SpotLight3D.new()
			sp.position = Vector3(s, 0.75, -L * 0.5 - 0.1); sp.rotation_degrees = Vector3(-7, 0, 0)
			sp.spot_range = 38.0; sp.spot_angle = 26.0; sp.spot_attenuation = 1.2
			sp.light_color = Color(1.0, 0.95, 0.85); sp.light_energy = 0.0; sp.shadow_enabled = false; sp.visible = false
			add_child(sp); _heads.append(sp)
		_smoke = CPUParticles3D.new(); _smoke.emitting = false; _smoke.amount = 24; _smoke.lifetime = 1.6
		_smoke.position = Vector3(0, H * 0.5, -L * 0.42); _smoke.direction = Vector3(0, 1, 0); _smoke.initial_velocity_min = 1.0; _smoke.initial_velocity_max = 2.5
		_smoke.gravity = Vector3(0, 1.0, 0); _smoke.scale_amount_min = 0.5; _smoke.scale_amount_max = 1.4
		var sm := SphereMesh.new(); sm.radius = 0.4; sm.height = 0.8
		var smat := StandardMaterial3D.new(); smat.albedo_color = Color(0.55, 0.55, 0.55, 0.5); smat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		smat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED; sm.material = smat; _smoke.mesh = sm
		add_child(_smoke)
		return
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

## a sudden change of velocity (not braking) is a crash: damage grows with the size of the hit
func _check_damage() -> void:
	var dv: float = (linear_velocity - _prev_v).length()
	_prev_v = linear_velocity
	if dv > 4.0 and not freeze:
		var dmg: float = (dv - 4.0) * 55.0
		health = maxf(0.0, health - dmg)
		last_hit = dv
	if _smoke: _smoke.emitting = health < 350.0 and visible
	if _smoke and health <= 0.0: (_smoke.mesh.material as StandardMaterial3D).albedo_color = Color(0.1, 0.1, 0.1, 0.7)

func damage(amount: float) -> void:
	health = maxf(0.0, health - amount)

func _physics_process(_dt: float) -> void:
	_check_damage()
	var fwd_speed := -linear_velocity.dot(global_transform.basis.z)  # +forward (-Z)
	if not driven:
		engine_force = 0.0
		brake = 8.0
		steering = 0.0
		_update_lights()
		return
	var s := speed_mps()
	var hf: float = clampf(health / 1000.0, 0.0, 1.0)
	var perf: float = 0.0 if health <= 0.0 else lerpf(0.45, 1.0, hf)     # damaged engines are weaker
	# steering gets tighter at low speed, gentler at high speed
	var steer_limit: float = lerp(MAX_STEER, 0.14, clamp(s / 40.0, 0.0, 1.0))
	steering = move_toward(steering, steer_in * steer_limit, 0.05)
	brake = 0.0
	if throttle > 0.05:
		if fwd_speed < -1.0:
			brake = MAX_BRAKE * throttle
			engine_force = 0.0
		else:
			var taper: float = clamp(1.0 - s / (TOP_SPEED * lerpf(0.6, 1.0, hf)), 0.0, 1.0)
			# VehicleBody3D: negative engine_force drives toward -Z (our forward)
			engine_force = -MAX_ENGINE * throttle * (0.35 + 0.65 * taper) * perf
	elif throttle < -0.05:
		if fwd_speed > 1.0:
			brake = MAX_BRAKE * -throttle
			engine_force = 0.0
		else:
			engine_force = MAX_ENGINE * 0.5 * -throttle * perf
	else:
		engine_force = 0.0
		brake = 1.5
	for w in wheels:
		w.wheel_friction_slip = (GRIP * 0.5 if (handbrake and not w.use_as_steering) else GRIP) * surface_grip
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
