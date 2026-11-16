extends Node
## Hand-to-hand combat (Bible section 14: accessible, arcade-style, GTA V feel).
##   Left mouse  punch (tap for a 3-hit combo: jab, cross, hook)     Right mouse  kick (slower, knocks down)
##   Q (hold)    guard - blocks most of a punch                       Ctrl         dodge (quick side/back step)
## You lock on to the nearest person in front of you; you turn to face them as you swing. People you hit either
## fight back or run; bystanders scatter; a witnessed assault is a crime (police.json "assault").
## Pedestrians get "hp" here (fighting only; being hit by a car is pedestrians.knock_down).
## Settings: source_data/life.json "combat".

var main: Node
var C: Dictionary
var act := {}            # player's current move: {kind, t, dur, hit: bool, combo}
var combo := 0           # next punch in the combo (0 jab, 1 cross, 2 hook)
var _combo_t := 0.0      # time left to chain the next punch
var guard := false
var _dodge_t := 0.0
var _dodge_v := Vector3.ZERO
var target = null        # pedestrian dictionary we're locked on to, or null
var hits_landed := 0
var kos := 0
var rng := RandomNumberGenerator.new()

const DEFAULTS := {"punch_dmg": [16, 22, 30], "kick_dmg": 34, "punch_s": 0.32, "kick_s": 0.55, "reach_m": 1.35,
	"kick_reach_m": 1.6, "lock_m": 3.4, "combo_window_s": 0.55, "stamina_punch": 3.0, "stamina_kick": 6.0,
	"ped_hp": [70, 140], "fight_back": 0.35, "ped_dmg": [6, 11], "ped_swing_s": [0.9, 1.6], "block_keep": 0.2,
	"dodge_m": 3.5, "dodge_s": 0.28}

func _ready() -> void:
	rng.randomize()
	var L = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/life.json"))
	C = DEFAULTS.duplicate()
	if L is Dictionary and L.has("combat"): C.merge(L["combat"], true)

func busy() -> bool:
	return not act.is_empty()

# ------------------------------------------------------------------ input
func _unhandled_input(e: InputEvent) -> void:
	if not _can_fight(): return
	if e is InputEventMouseButton and e.pressed and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		if e.button_index == MOUSE_BUTTON_LEFT: attack("punch"); get_viewport().set_input_as_handled()
		elif e.button_index == MOUSE_BUTTON_RIGHT: attack("kick"); get_viewport().set_input_as_handled()
	if e is InputEventKey and not e.echo:
		if e.physical_keycode == KEY_Q: guard = e.pressed
		elif e.physical_keycode == KEY_CTRL and e.pressed: dodge()

func _can_fight() -> bool:
	return main.input_enabled and main.current_car == null and not main.dying and not (main.bars and main.bars.inside) \
		and not (main.get("phone") and main.phone.open)

# ------------------------------------------------------------------ player moves
func attack(kind: String) -> bool:
	if main.current_car or main.dying: return false
	if not act.is_empty():
		if kind == "punch" and act["kind"] == "punch" and act["t"] > act["dur"] * 0.55: act["queued"] = true   # buffer the next punch
		return false
	var nd = main.needs
	var tired: bool = nd != null and nd.stamina < 5.0
	if nd: nd.stamina = maxf(0.0, nd.stamina - float(C["stamina_" + kind]))
	var dur: float = float(C[kind + "_s"]) * (1.5 if tired else 1.0)
	var c := combo if kind == "punch" else 0
	act = {"kind": kind, "t": 0.0, "dur": dur, "hit": false, "combo": c}
	if kind == "punch":
		combo = (combo + 1) % 3
	else:
		combo = 0
	_combo_t = 0.0
	guard = false
	target = _pick_target()
	return true

func dodge() -> void:
	if _dodge_t > 0.0 or main.current_car: return
	var pl = main.player
	var dir := Vector3(pl.input_dir.x, 0, -pl.input_dir.y)
	if dir.length() < 0.2: dir = Vector3(0, 0, 1)               # no direction held: step back
	dir = Basis(Vector3.UP, main.cam_yaw) * dir.normalized()
	_dodge_v = dir * float(C["dodge_m"]) / float(C["dodge_s"])
	_dodge_t = float(C["dodge_s"])
	act = {}

func _physics_process(dt: float) -> void:
	var pl = main.player
	if pl == null: return
	_combo_t += dt
	if _combo_t > float(C["combo_window_s"]) and act.is_empty(): combo = 0
	if _dodge_t > 0.0:
		_dodge_t -= dt
		pl.velocity.x = _dodge_v.x; pl.velocity.z = _dodge_v.z
	if target != null and (not main.peds.peds.has(target) or target["state"] in ["fly", "down", "injured"]
			or (target["pos"] - main.focus_world()).length() > float(C["lock_m"]) + 1.5):
		target = null
	if target == null and _can_fight(): target = _pick_target() if _anyone_close() else null
	# face whoever we're fighting while swinging or guarding
	if target != null and (not act.is_empty() or guard):
		var to: Vector3 = target["pos"] - (pl.global_position + main.world_offset)
		pl.model.rotation.y = lerp_angle(pl.model.rotation.y, atan2(-to.x, -to.z), 1.0 - exp(-18.0 * dt))
	pl.move_mult = 0.25 if (not act.is_empty() or guard) else 1.0
	var shown := 0.0; var shown_t := 0.0
	if not act.is_empty():
		act["t"] += dt
		var f: float = act["t"] / act["dur"]
		shown = (1.0 + float(act["combo"] % 2)) if act["kind"] == "punch" else 3.0
		shown_t = f
		if not act["hit"] and f >= 0.45:
			act["hit"] = true
			_resolve_hit()
		if f >= 1.0:
			var q: bool = act.get("queued", false)
			act = {}
			if q: attack("punch")
	elif guard:
		shown = 4.0; shown_t = 0.5
	var body: MeshInstance3D = pl.get("_body")
	if body:
		body.set_instance_shader_parameter("act", shown)
		body.set_instance_shader_parameter("act_t", shown_t)

func _anyone_close() -> bool:
	var f: Vector3 = main.focus_world()
	for p in main.peds.peds:
		if (p["pos"] - f).length() < float(C["lock_m"]): return true
	return false

## nearest standing person in front (within the lock range, inside ~75 degrees of where you face)
func _pick_target():
	if main.peds == null: return null
	var pl = main.player
	var me: Vector3 = pl.global_position + main.world_offset
	var face := Vector3(-sin(pl.model.rotation.y), 0, -cos(pl.model.rotation.y))
	var camf := Vector3(-sin(main.cam_yaw), 0, -cos(main.cam_yaw))
	var best = null; var bs := 1e9
	for p in main.peds.peds:
		if p["state"] in ["fly", "down", "injured"]: continue
		var to: Vector3 = p["pos"] - me; to.y = 0
		var d := to.length()
		if d > float(C["lock_m"]) or d < 0.05: continue
		var dirn := to / d
		var ang: float = minf(face.angle_to(dirn), camf.angle_to(dirn))
		if ang > deg_to_rad(80.0): continue
		var score := d + ang * 1.5
		if score < bs: bs = score; best = p
	return best

func _resolve_hit() -> void:
	var t = target if target != null else _pick_target()
	if t == null: return
	var me: Vector3 = main.player.global_position + main.world_offset
	var to: Vector3 = t["pos"] - me; to.y = 0
	var reach: float = float(C["kick_reach_m"] if act["kind"] == "kick" else C["reach_m"])
	if to.length() > reach + 0.4: return
	var dmg: float
	if act["kind"] == "kick": dmg = float(C["kick_dmg"])
	else: dmg = float(C["punch_dmg"][int(act["combo"])])
	hits_landed += 1
	hit_ped(t, dmg, to.normalized(), act["kind"] == "kick" or int(act["combo"]) == 2)

# ------------------------------------------------------------------ people
func ped_hp(p: Dictionary) -> float:
	if not p.has("hp"):
		var r: Array = C["ped_hp"]
		p["hp"] = rng.randf_range(float(r[0]), float(r[1])); p["hp_max"] = p["hp"]
	return p["hp"]

## the player hit this person: damage, a flinch, knocked down at 0, then they fight back or run
func hit_ped(p: Dictionary, dmg: float, dir: Vector3, heavy: bool) -> void:
	ped_hp(p)
	p["hp"] = float(p["hp"]) - dmg
	p["react_t"] = 0.35
	if float(p["hp"]) <= 0.0:
		kos += 1
		main.peds.knock_down(p, dir * (4.0 if not heavy else 6.5))     # light enough to get back up later
		if target == p: target = null
	elif heavy and rng.randf() < 0.35:
		main.peds.knock_down(p, dir * 4.0)
	elif p["state"] != "fight" and p["state"] != "flee":
		if rng.randf() < float(C["fight_back"]) or p.get("fighter", false): start_fight(p)
		else: main.peds._flee(p, main.player.global_position + main.world_offset)
	# a witnessed assault is a crime; everyone nearby backs off
	if main.police: main.police.report("assault", p["pos"])
	for o in main.peds.peds:
		if o != p and o["state"] in ["walk", "wait", "cross"] and (o["pos"] - p["pos"]).length() < 14.0:
			main.peds._flee(o, p["pos"])

func start_fight(p: Dictionary) -> void:
	ped_hp(p)
	p["state"] = "fight"; p["swing_t"] = rng.randf_range(0.4, 0.9); p["fight_t"] = 0.0

## called by pedestrians.gd for anyone in the "fight" state: close in, square up, throw punches
func step_fighter(p: Dictionary, dt: float) -> void:
	var me: Vector3 = main.player.global_position + main.world_offset
	var to: Vector3 = me - p["pos"]; to.y = 0
	var d := to.length()
	p["fight_t"] = float(p.get("fight_t", 0.0)) + dt
	if main.current_car != null or main.dying or d > 25.0 or p["fight_t"] > 60.0:
		p["state"] = "walk"; return
	p["yaw"] = lerp_angle(p["yaw"], atan2(-to.x, -to.z), clampf(dt * 10.0, 0.0, 1.0))
	if d > 1.05 and float(p.get("react_t", 0.0)) <= 0.0 and p.get("swing", 0.0) <= 0.0:
		p["pos"] = p["pos"] + to / d * minf(d - 1.0, p["speed"] * 2.0 * dt)
		p["phase"] = fmod(p["phase"] + dt * p["speed"] * 10.0, TAU)
	p["swing_t"] = float(p["swing_t"]) - dt
	if p.get("swing", 0.0) > 0.0:
		p["swing"] = float(p["swing"]) + dt / 0.38
		if p["swing"] >= 0.45 and not p.get("swung", false):
			p["swung"] = true
			if d < 1.5 and _dodge_t <= 0.0:
				var r: Array = C["ped_dmg"]
				var dmg := rng.randf_range(float(r[0]), float(r[1]))
				if guard: dmg *= float(C["block_keep"])
				main.hurt(dmg, "fight")
		if p["swing"] >= 1.0: p["swing"] = 0.0
	elif p["swing_t"] <= 0.0 and d < 1.6:
		p["swing"] = 0.001; p["swung"] = false
		var r2: Array = C["ped_swing_s"]
		p["swing_t"] = rng.randf_range(float(r2[0]), float(r2[1]))

## what the shader should show for this person this frame: [act, act_t]
func ped_pose(p: Dictionary) -> Array:
	if float(p.get("react_t", 0.0)) > 0.0: return [5.0, 1.0 - float(p["react_t"]) / 0.35]
	if p["state"] == "fight":
		if float(p.get("swing", 0.0)) > 0.0: return [1.0, float(p["swing"])]
		return [4.0, 0.5]
	return [0.0, 0.0]

func get_save_data() -> Dictionary:
	return {"hits": hits_landed, "kos": kos}

func apply_save_data(d: Dictionary) -> void:
	hits_landed = int(d.get("hits", 0)); kos = int(d.get("kos", 0))
