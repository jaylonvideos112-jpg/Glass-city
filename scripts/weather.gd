extends Node3D
## Seasonal weather (Bible §6): a Markov chain of weather spells from source_data/climate.json, smooth blending
## between looks, and rain/snow particles that follow the camera. F7 cycles states for testing.

var main: Node
var W: Dictionary                 # climate.json "weather"
var state := "clear"
var hours_left := 6.0
var _from := {}                   # look being blended from
var _blend := 1.0                 # 0..1 progress to the current state's look
var rng := RandomNumberGenerator.new()
var rain: GPUParticles3D
var snow: GPUParticles3D
var _last_hours := -1.0
var _flash_t := 0.0

const LOOK_KEYS := ["cloud", "sun", "fog", "dark"]
const ORDER := ["clear", "partly", "overcast", "rain", "storm", "fog", "snow"]

func _ready() -> void:
	W = main.tod.C["weather"]
	rng.seed = 2026
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--weather="): state = a.substr(10)
	_from = _target()
	hours_left = _spell_hours(state)
	rain = _make_precip(false)
	snow = _make_precip(true)
	add_child(rain); add_child(snow)
	_update_precip()

func _target() -> Dictionary:
	var s: Dictionary = W["states"][state]
	var d := {}
	for k in LOOK_KEYS: d[k] = float(s[k])
	return d

## Current blended look: {cloud, sun, fog, dark} used by time_of_day.gd.
func look() -> Dictionary:
	var t := _target()
	var d := {}
	var b := smoothstep(0.0, 1.0, _blend)
	for k in LOOK_KEYS: d[k] = lerp(float(_from.get(k, t[k])), float(t[k]), b)
	return d

func _spell_hours(s: String) -> float:
	var h: Array = W["states"][s]["hours"]
	return rng.randf_range(h[0], h[1])

## Pick the next state from the season's odds (never a state with zero odds this season).
func next_state(season: String) -> String:
	var odds: Dictionary = W["next"][season]
	var tot := 0.0
	for k in odds: tot += float(odds[k])
	var r := rng.randf() * tot
	for k in odds:
		r -= float(odds[k])
		if r <= 0.0 and float(odds[k]) > 0.0: return k
	return "clear"

func set_state(s: String, hours := -1.0) -> void:
	if not W["states"].has(s): return
	_from = look()
	state = s
	_blend = 0.0
	hours_left = hours if hours >= 0.0 else _spell_hours(s)
	_update_precip()

func snap() -> void:
	_blend = 1.0
	_from = _target()

func _unhandled_input(e: InputEvent) -> void:
	if e.is_action_pressed("weather_next"):
		var s: String = ORDER[(ORDER.find(state) + 1) % ORDER.size()]
		set_state(s)
		main.hud.flash("Weather: " + label())

func label() -> String:
	return {"clear": "Clear", "partly": "Partly cloudy", "overcast": "Overcast", "rain": "Rain", "storm": "Thunderstorm",
		"fog": "Fog", "snow": "Snow"}.get(state, state)

func _process(dt: float) -> void:
	var tod = main.tod
	var h: float = tod.total_hours
	if _last_hours >= 0.0:
		var dh: float = h - _last_hours
		if dh < 0.0 or dh > 2.0: dh = 0.0   # clock was set/jumped (debug, sleep, load): don't burn the spell
		hours_left -= dh
		_blend = min(1.0, _blend + dh / 0.75)   # looks blend over ~45 game minutes
		if hours_left <= 0.0:
			var s := next_state(tod.season_name())
			# weather that cannot happen in this season ends immediately (e.g. snow left over when spring starts)
			set_state(s)
	_last_hours = h
	if float(W["next"][tod.season_name()].get(state, 0.0)) <= 0.0 and state != "clear":
		set_state("overcast")
	# precipitation follows the camera, hidden indoors
	var cam: Camera3D = main.camera
	if cam:
		global_position = cam.global_position + Vector3(0, 12, 0)
	var indoors: bool = main.bars != null and main.bars.inside
	rain.emitting = W["states"][state]["precip"] == "rain" and not indoors and _blend > 0.2
	snow.emitting = W["states"][state]["precip"] == "snow" and not indoors and _blend > 0.2
	# lightning in storms: brief sky flash
	if state == "storm" and not indoors:
		_flash_t -= dt
		if _flash_t <= 0.0:
			_flash_t = rng.randf_range(4.0, 14.0)
			_lightning()

func _lightning() -> void:
	var env: Environment = main.env
	var e0: float = env.ambient_light_energy
	env.ambient_light_energy = e0 + 2.5
	await get_tree().create_timer(0.08).timeout
	env.ambient_light_energy = e0 + 0.4
	await get_tree().create_timer(0.06).timeout
	env.ambient_light_energy = e0 + 1.8
	await get_tree().create_timer(0.1).timeout
	env.ambient_light_energy = e0

func _update_precip() -> void:
	if rain == null: return
	var rate: float = W["states"][state]["rate"]
	rain.amount_ratio = clamp(rate / 2.2, 0.15, 1.0)
	snow.amount_ratio = clamp(rate, 0.2, 1.0)

func _make_precip(is_snow: bool) -> GPUParticles3D:
	var p := GPUParticles3D.new()
	p.amount = 9000 if not is_snow else 6000
	p.lifetime = 1.2 if not is_snow else 6.0
	p.visibility_aabb = AABB(Vector3(-40, -30, -40), Vector3(80, 45, 80))
	p.emitting = false
	var pm := ParticleProcessMaterial.new()
	pm.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_BOX
	pm.emission_box_extents = Vector3(35, 2, 35)
	pm.direction = Vector3(0.08, -1, 0.03)
	pm.spread = 2.0 if not is_snow else 25.0
	pm.initial_velocity_min = 22.0 if not is_snow else 1.2
	pm.initial_velocity_max = 28.0 if not is_snow else 2.2
	pm.gravity = Vector3(0, -9.8, 0) if not is_snow else Vector3(0.3, -0.6, 0.1)
	if is_snow:
		pm.turbulence_enabled = true
		pm.turbulence_noise_strength = 0.6
	p.process_material = pm
	var mesh := QuadMesh.new()
	mesh.size = Vector2(0.015, 0.55) if not is_snow else Vector2(0.06, 0.06)
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.albedo_color = Color(0.75, 0.8, 0.88, 0.35) if not is_snow else Color(1, 1, 1, 0.9)
	m.billboard_mode = BaseMaterial3D.BILLBOARD_FIXED_Y if not is_snow else BaseMaterial3D.BILLBOARD_ENABLED
	m.billboard_keep_scale = true
	mesh.material = m
	p.draw_pass_1 = mesh
	return p
