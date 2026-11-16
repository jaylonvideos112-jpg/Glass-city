extends Node
## Hand-to-hand combat (Bible section 14) - arcade controls, but opponents that fight like people, not GTA's
## "take turns throwing the same punch".
##
## YOU   Left click punch (tap: jab, cross, hook)   Right click kick   Middle click / Z  tackle (take them down)
##       Q hold guard (blocks most strikes; tap Q just before a hit = PARRY: they stagger, your next hit counts x1.5)
##       Ctrl dodge (brief i-frames)   Space when pinned: struggle free   Space when knocked down: get up faster
##       Hit someone who's down: ground punches (extra damage)
## THEM  every fighter has a STYLE (data: life.json combat.styles) that sets their moves, speed, guard and nerve:
##       boxer (jabs, hooks, blocks, slips), brawler (wild hooks, shoves, tackles), kicker (front kicks, sweeps),
##       grappler (tackles you to the ground and pins you, ground punches), dirty (sweeps, shoves, kicks you while down)
##       Moves are TELEGRAPHED (a windup pose) so you can block or dodge on reaction.
##       They circle, keep range, block or sidestep when you wind up, counter after a block, knock you down with
##       heavy hits, tackle you from a few metres away, and kick you while you're down.
##       They ADAPT: guard a lot and they grab you (a guard doesn't stop a tackle); spam punches and they block and
##       counter; dodge a lot and they sweep.
##       Friends nearby may jump in (only two press you at once, the rest circle). Beaten down with low nerve, they
##       run or put their hands up.
## A witnessed assault is a crime (police.json "assault"). People hit by cars use pedestrians.knock_down too.

var main: Node
var C: Dictionary
var rng := RandomNumberGenerator.new()

# ---- player
var act := {}            # current move: {kind, t, dur, hit, combo}
var combo := 0
var _combo_t := 0.0
var guard := false
var _guard_pressed_t := 99.0      # seconds since Q went down (parry window)
var _dodge_t := 0.0
var _dodge_v := Vector3.ZERO
var target = null
var hits_landed := 0
var kos := 0
var parries := 0
var counter_bonus := 0.0          # >0: next hit is a counter (x1.5)
var pstate := ""                  # "", "stagger", "down", "pinned"
var pstate_t := 0.0
var pinned_by = null
var escape := 0.0                 # 0..1 struggle meter while pinned
var times_taken_down := 0
# habits over the last ~20 s (the AI reads these)
var habit := {"guard": 0.0, "attack": 0.0, "dodge": 0.0}

const DEFAULTS := {"punch_dmg": [16, 22, 30], "kick_dmg": 34, "punch_s": 0.32, "kick_s": 0.55, "tackle_s": 0.7,
	"reach_m": 1.35, "kick_reach_m": 1.6, "lock_m": 3.6, "combo_window_s": 0.55, "stamina_punch": 3.0,
	"stamina_kick": 6.0, "stamina_tackle": 12.0, "ped_hp": [70, 140], "fight_back": 0.4, "block_keep": 0.2,
	"parry_window_s": 0.25, "dodge_m": 3.5, "dodge_s": 0.28, "max_attackers": 2, "join_chance": 0.3,
	"styles": {
		"boxer": {"w": 3, "hp": 1.1, "speed": 1.15, "guard": 0.55, "evade": 0.35, "nerve": 0.7,
			"moves": {"jab": 5, "hook": 3, "shove": 1}},
		"brawler": {"w": 4, "hp": 1.25, "speed": 0.9, "guard": 0.2, "evade": 0.1, "nerve": 0.8,
			"moves": {"hook": 5, "jab": 2, "shove": 2, "tackle": 1}},
		"kicker": {"w": 2, "hp": 0.95, "speed": 1.1, "guard": 0.35, "evade": 0.4, "nerve": 0.6,
			"moves": {"kick": 5, "sweep": 2, "jab": 2}},
		"grappler": {"w": 2, "hp": 1.3, "speed": 1.0, "guard": 0.3, "evade": 0.15, "nerve": 0.85,
			"moves": {"tackle": 5, "jab": 2, "shove": 1}},
		"dirty": {"w": 2, "hp": 1.0, "speed": 1.05, "guard": 0.25, "evade": 0.3, "nerve": 0.5,
			"moves": {"sweep": 3, "kick": 2, "shove": 2, "hook": 2}}},
	# move: windup s, strike s, recover s, reach m, damage, effect (stagger/down/push/takedown), pose
	"moves": {
		"jab":    {"wind": 0.18, "strike": 0.18, "rec": 0.25, "reach": 1.3, "dmg": 4, "fx": "", "pose": 2},
		"hook":   {"wind": 0.38, "strike": 0.22, "rec": 0.45, "reach": 1.25, "dmg": 9, "fx": "stagger", "pose": 6},
		"kick":   {"wind": 0.4, "strike": 0.25, "rec": 0.5, "reach": 1.75, "dmg": 9, "fx": "push", "pose": 3},
		"sweep":  {"wind": 0.45, "strike": 0.25, "rec": 0.6, "reach": 1.5, "dmg": 4, "fx": "down", "pose": 8},
		"shove":  {"wind": 0.25, "strike": 0.2, "rec": 0.35, "reach": 1.3, "dmg": 2, "fx": "push", "pose": 9},
		"tackle": {"wind": 0.45, "strike": 0.45, "rec": 0.9, "reach": 1.1, "dmg": 6, "fx": "takedown", "pose": 7, "lunge_m": 3.6},
		"stomp":  {"wind": 0.3, "strike": 0.2, "rec": 0.5, "reach": 1.4, "dmg": 7, "fx": "", "pose": 3},
		"gnp":    {"wind": 0.25, "strike": 0.2, "rec": 0.35, "reach": 1.2, "dmg": 6, "fx": "", "pose": 10}}}

func _ready() -> void:
	rng.randomize()
	var L = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/life.json"))
	C = DEFAULTS.duplicate(true)
	if L is Dictionary and L.has("combat"): C.merge(L["combat"], true)

func busy() -> bool:
	return not act.is_empty() or pstate != ""

# ------------------------------------------------------------------ input
func _unhandled_input(e: InputEvent) -> void:
	if pstate in ["pinned", "down"] and e is InputEventKey and e.pressed and not e.echo and e.physical_keycode == KEY_SPACE:
		struggle(); get_viewport().set_input_as_handled(); return
	if not _can_fight(): return
	if e is InputEventMouseButton and e.pressed and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		if e.button_index == MOUSE_BUTTON_LEFT: attack("punch"); get_viewport().set_input_as_handled()
		elif e.button_index == MOUSE_BUTTON_RIGHT: attack("kick"); get_viewport().set_input_as_handled()
		elif e.button_index == MOUSE_BUTTON_MIDDLE: attack("tackle"); get_viewport().set_input_as_handled()
	if e is InputEventKey and not e.echo:
		if e.physical_keycode == KEY_Q: set_guard(e.pressed)
		elif e.physical_keycode == KEY_Z and e.pressed: attack("tackle")
		elif e.physical_keycode == KEY_CTRL and e.pressed: dodge()

func _can_fight() -> bool:
	return main.input_enabled and main.current_car == null and not main.dying and pstate == "" \
		and not (main.bars and main.bars.inside) and not (main.get("phone") and main.phone.open)

func set_guard(on: bool) -> void:
	if on and not guard: _guard_pressed_t = 0.0
	guard = on

# ------------------------------------------------------------------ player moves
func attack(kind: String) -> bool:
	if main.current_car or main.dying or pstate != "": return false
	if not act.is_empty():
		if kind == "punch" and act["kind"] == "punch" and act["t"] > act["dur"] * 0.55: act["queued"] = true
		return false
	var nd = main.needs
	var tired: bool = nd != null and nd.stamina < 5.0
	if nd: nd.stamina = maxf(0.0, nd.stamina - float(C["stamina_" + kind]))
	var dur: float = float(C[kind + "_s"]) * (1.5 if tired else 1.0)
	act = {"kind": kind, "t": 0.0, "dur": dur, "hit": false, "combo": combo if kind == "punch" else 0}
	combo = (combo + 1) % 3 if kind == "punch" else 0
	_combo_t = 0.0
	guard = false
	habit["attack"] += 1.0
	target = _pick_target(true)
	# opponents who see the windup may block or slip it
	if target != null and target["state"] == "fight": _react_to_windup(target)
	return true

func dodge() -> void:
	if _dodge_t > 0.0 or main.current_car or pstate != "": return
	var pl = main.player
	var dir := Vector3(pl.input_dir.x, 0, -pl.input_dir.y)
	if dir.length() < 0.2: dir = Vector3(0, 0, 1)
	dir = Basis(Vector3.UP, main.cam_yaw) * dir.normalized()
	_dodge_v = dir * float(C["dodge_m"]) / float(C["dodge_s"])
	_dodge_t = float(C["dodge_s"])
	act = {}
	habit["dodge"] += 1.0

## mash Space: out from under a pin (stronger with fitness), or up off the ground sooner
func struggle() -> void:
	var fit: float = main.needs.fitness if main.needs else 30.0
	if pstate == "pinned":
		escape += 0.07 + fit * 0.0008
		if escape >= 1.0: _break_pin()
	elif pstate == "down":
		pstate_t -= 0.18

func _break_pin() -> void:
	var p = pinned_by
	pinned_by = null; escape = 0.0
	_set_pstate("", 0.0)
	if main.hud: main.hud.flash("You broke free!")
	if p != null and main.peds.peds.has(p):
		p["ai"]["mode"] = "recover"; p["ai"]["t"] = 1.0; p["y_off"] = 0.0
		var away: Vector3 = p["pos"] - (main.player.global_position + main.world_offset); away.y = 0
		p["pos"] = p["pos"] + away.normalized() * 1.2

func _set_pstate(s: String, t: float) -> void:
	pstate = s; pstate_t = t
	var pl = main.player
	if s == "":
		pl.model.rotation.x = 0.0; pl.model.position = Vector3.ZERO
		act = {}
	elif s in ["down", "pinned"]:
		pl.model.rotation.x = PI * 0.5          # flat on your back
		pl.model.position = Vector3(0, 0.22, 0)
		act = {}; guard = false

func _physics_process(dt: float) -> void:
	var pl = main.player
	if pl == null: return
	_combo_t += dt; _guard_pressed_t += dt
	for k in habit: habit[k] = maxf(0.0, habit[k] - dt * 0.05 * maxf(habit[k], 1.0))
	if guard: habit["guard"] += dt * 0.5
	if _combo_t > float(C["combo_window_s"]) and act.is_empty(): combo = 0
	counter_bonus = maxf(0.0, counter_bonus - dt)
	# player states set by opponents
	if pstate != "":
		pstate_t -= dt
		pl.move_mult = 0.0
		pl.velocity.x = 0.0; pl.velocity.z = 0.0
		if pstate == "pinned":
			escape = maxf(0.0, escape - dt * 0.12)          # they bear down if you stop struggling
			if pinned_by == null or not main.peds.peds.has(pinned_by) or pinned_by["state"] != "fight" or pstate_t <= 0.0:
				_break_pin()
		elif pstate_t <= 0.0:
			_set_pstate("", 0.0)
		_pose_player(0.0, 0.0)
		return
	if _dodge_t > 0.0:
		_dodge_t -= dt
		pl.velocity.x = _dodge_v.x; pl.velocity.z = _dodge_v.z
	if target != null and (not main.peds.peds.has(target) or target["state"] in ["fly", "injured"]
			or (target["pos"] - main.focus_world()).length() > float(C["lock_m"]) + 1.5):
		target = null
	if target == null and _can_fight() and _anyone_close(): target = _pick_target(false)
	if target != null and (not act.is_empty() or guard):
		var to: Vector3 = target["pos"] - (pl.global_position + main.world_offset)
		pl.model.rotation.y = lerp_angle(pl.model.rotation.y, atan2(-to.x, -to.z), 1.0 - exp(-18.0 * dt))
	pl.move_mult = 0.25 if (not act.is_empty() or guard) else 1.0
	var shown := 0.0; var shown_t := 0.0
	if not act.is_empty():
		act["t"] += dt
		var f: float = act["t"] / act["dur"]
		match act["kind"]:
			"punch": shown = 6.0 if int(act["combo"]) == 2 else (1.0 + float(act["combo"] % 2))
			"kick": shown = 3.0
			"tackle":
				shown = 7.0
				if f > 0.25 and f < 0.6 and target != null:     # the lunge
					var to2: Vector3 = target["pos"] - (pl.global_position + main.world_offset); to2.y = 0
					if to2.length() > 0.9: pl.velocity.x = to2.normalized().x * 9.0; pl.velocity.z = to2.normalized().z * 9.0
		shown_t = f
		if not act["hit"] and f >= (0.55 if act["kind"] == "tackle" else 0.45):
			act["hit"] = true
			_resolve_hit()
		if f >= 1.0:
			var q: bool = act.get("queued", false)
			act = {}
			if q: attack("punch")
	elif guard:
		shown = 4.0; shown_t = 0.5
	_pose_player(shown, shown_t)

func _pose_player(a: float, t: float) -> void:
	var body: MeshInstance3D = main.player.get("_body")
	if body:
		body.set_instance_shader_parameter("act", a)
		body.set_instance_shader_parameter("act_t", t)

func _anyone_close() -> bool:
	var f: Vector3 = main.focus_world()
	for p in main.peds.peds:
		if (p["pos"] - f).length() < float(C["lock_m"]): return true
	return false

## nearest person in front; when attacking, someone on the ground right at your feet counts too (ground punches)
func _pick_target(attacking: bool):
	if main.peds == null: return null
	var pl = main.player
	var me: Vector3 = pl.global_position + main.world_offset
	var face := Vector3(-sin(pl.model.rotation.y), 0, -cos(pl.model.rotation.y))
	var camf := Vector3(-sin(main.cam_yaw), 0, -cos(main.cam_yaw))
	var best = null; var bs := 1e9
	for p in main.peds.peds:
		var downed: bool = p["state"] in ["down", "injured"]
		if p["state"] == "fly" or (downed and not attacking): continue
		var to: Vector3 = p["pos"] - me; to.y = 0
		var d := to.length()
		if d > (1.7 if downed else float(C["lock_m"])) or d < 0.05: continue
		var dirn := to / d
		var ang: float = minf(face.angle_to(dirn), camf.angle_to(dirn))
		if ang > deg_to_rad(80.0): continue
		var score := d + ang * 1.5 + (1.0 if downed else 0.0) - (1.5 if p["state"] == "fight" else 0.0)
		if score < bs: bs = score; best = p
	return best

func _resolve_hit() -> void:
	var t = target if target != null else _pick_target(true)
	if t == null: return
	var me: Vector3 = main.player.global_position + main.world_offset
	var to: Vector3 = t["pos"] - me; to.y = 0
	var kind: String = act["kind"]
	var reach: float = float(C["kick_reach_m"] if kind == "kick" else C["reach_m"])
	if kind == "tackle": reach = 1.3
	if to.length() > reach + 0.4: return
	var ai: Dictionary = t.get("ai", {})
	# their guard / slip
	if ai.get("mode", "") == "evade" and kind != "tackle":
		return                                         # slipped it
	var blocked: bool = ai.get("mode", "") == "block" and kind != "tackle"
	var dmg: float
	match kind:
		"kick": dmg = float(C["kick_dmg"])
		"tackle": dmg = 10.0
		_: dmg = float(C["punch_dmg"][int(act["combo"])])
	if t["state"] in ["down", "injured"]: dmg *= 1.3                    # ground punches
	if counter_bonus > 0.0: dmg *= 1.5; counter_bonus = 0.0
	if blocked:
		dmg *= 0.25
		if rng.randf() < 0.5: ai["counter"] = true                    # they'll punish you for that
	hits_landed += 1
	var heavy: bool = kind == "kick" or kind == "tackle" or int(act["combo"]) == 2
	hit_ped(t, dmg, to.normalized(), heavy and not blocked, kind == "tackle")

# ------------------------------------------------------------------ people
func ped_hp(p: Dictionary) -> float:
	if not p.has("hp"):
		var st := _style_of(p)
		var r: Array = C["ped_hp"]
		p["hp"] = rng.randf_range(float(r[0]), float(r[1])) * float(C["styles"][st]["hp"]); p["hp_max"] = p["hp"]
	return p["hp"]

func _style_of(p: Dictionary) -> String:
	if not p.has("style"):
		var tot := 0.0
		for s in C["styles"]: tot += float(C["styles"][s]["w"])
		var x := rng.randf() * tot
		for s in C["styles"]:
			x -= float(C["styles"][s]["w"])
			if x <= 0.0: p["style"] = s; break
		if not p.has("style"): p["style"] = "brawler"
	return p["style"]

## the player hit this person
func hit_ped(p: Dictionary, dmg: float, dir: Vector3, heavy: bool, takedown := false) -> void:
	ped_hp(p)
	p["hp"] = float(p["hp"]) - dmg
	p["react_t"] = 0.35
	var ai: Dictionary = p.get("ai", {})
	if ai.get("mode", "") in ["wind", "strike"] and heavy:
		ai["mode"] = "recover"; ai["t"] = 0.5                         # you interrupted their move
	if p["state"] in ["down", "injured"]:
		p["down_t"] = maxf(float(p.get("down_t", 0.0)), 2.5)
		if float(p["hp"]) < -40.0: p["state"] = "injured"
	elif float(p["hp"]) <= 0.0 or takedown:
		if float(p["hp"]) <= 0.0: kos += 1
		main.peds.knock_down(p, dir * (3.0 if takedown else (4.0 if not heavy else 6.5)))
		if float(p["hp"]) > 0.0: p["get_up_fight"] = true            # tackled: they'll get up swinging
		if target == p and float(p["hp"]) <= 0.0: target = null
	elif heavy and rng.randf() < 0.3:
		main.peds.knock_down(p, dir * 4.0); p["get_up_fight"] = true
	elif p["state"] != "fight":
		var nerve: float = float(C["styles"][_style_of(p)]["nerve"])
		if rng.randf() < float(C["fight_back"]) * (0.6 + nerve) or p.get("fighter", false): start_fight(p)
		else: main.peds._flee(p, main.player.global_position + main.world_offset)
	else:
		ai["morale"] = float(ai.get("morale", 1.0)) - dmg / maxf(float(p["hp_max"]), 1.0) * (1.4 - float(C["styles"][_style_of(p)]["nerve"]))
	if main.police: main.police.report("assault", p["pos"])
	_call_friends(p)
	for o in main.peds.peds:
		if o != p and o["state"] in ["walk", "wait", "cross"] and (o["pos"] - p["pos"]).length() < 14.0 and not o.get("joining", false):
			main.peds._flee(o, p["pos"])

## a few people nearby take their side and join in
func _call_friends(p: Dictionary) -> void:
	if p.get("called", false): return
	p["called"] = true
	for o in main.peds.peds:
		if o == p or not (o["state"] in ["walk", "wait", "cross"]): continue
		if (o["pos"] - p["pos"]).length() < 12.0 and rng.randf() < float(C["join_chance"]):
			o["joining"] = true; o["called"] = true
			start_fight(o)

func start_fight(p: Dictionary) -> void:
	ped_hp(p); _style_of(p)
	p["state"] = "fight"; p["fight_t"] = 0.0
	p["ai"] = {"mode": "approach", "t": rng.randf_range(0.2, 0.6), "move": "", "circle": 1.0 if rng.randf() < 0.5 else -1.0,
		"morale": 1.0, "counter": false}

func _attackers() -> int:
	var n := 0
	for p in main.peds.peds:
		if p["state"] == "fight" and p.get("ai", {}).get("mode", "") in ["wind", "strike", "pin"]: n += 1
	return n

## opponents who see you wind up: block, or slip to the side (style decides how often)
func _react_to_windup(p: Dictionary) -> void:
	var ai: Dictionary = p["ai"]
	if not (ai["mode"] in ["approach", "circle"]): return       # mid-move or recovering = an opening
	var st: Dictionary = C["styles"][_style_of(p)]
	# they block more if you've been throwing a lot
	var spam: float = clampf(habit["attack"] / 12.0, 0.0, 0.35)
	var r := rng.randf()
	if r < float(st["evade"]):
		ai["mode"] = "evade"; ai["t"] = 0.35; ai["side"] = 1.0 if rng.randf() < 0.5 else -1.0
	elif r < float(st["evade"]) + float(st["guard"]) + spam:
		ai["mode"] = "block"; ai["t"] = 0.45; ai["counter"] = rng.randf() < 0.5 + spam

## pick a move: style weights, nudged by how you've been fighting
func _choose_move(p: Dictionary, d: float) -> String:
	var st: Dictionary = C["styles"][_style_of(p)]
	var w: Dictionary = st["moves"].duplicate()
	if habit["guard"] > 2.0: w["tackle"] = float(w.get("tackle", 0.0)) + 3.0; w["shove"] = float(w.get("shove", 0.0)) + 2.0
	if habit["dodge"] > 2.0: w["sweep"] = float(w.get("sweep", 0.0)) + 2.5
	if habit["attack"] > 6.0: w["jab"] = float(w.get("jab", 0.0)) + 2.0          # quick counters into a slugger
	if pstate == "down": return "stomp" if rng.randf() < 0.6 else "gnp"
	if d > 2.2: w = {"tackle": w.get("tackle", 0.0)} if float(w.get("tackle", 0.0)) > 0.0 else {}
	var tot := 0.0
	for k in w: tot += float(w[k])
	if tot <= 0.0: return ""
	var x := rng.randf() * tot
	for k in w:
		x -= float(w[k])
		if x <= 0.0: return k
	return w.keys()[0]

## pedestrians.gd calls this every frame for anyone in the "fight" state
func step_fighter(p: Dictionary, dt: float) -> void:
	var me: Vector3 = main.player.global_position + main.world_offset
	var to: Vector3 = me - p["pos"]; to.y = 0
	var d := to.length()
	var dirn: Vector3 = to / maxf(d, 0.01)
	var ai: Dictionary = p["ai"]
	var st: Dictionary = C["styles"][_style_of(p)]
	var spd: float = float(p["speed"]) * float(st["speed"])
	p["fight_t"] = float(p.get("fight_t", 0.0)) + dt
	if main.current_car != null or main.dying or d > 28.0 or p["fight_t"] > 90.0:
		_end_fight(p); return
	# nerve: beaten and scared -> run, or hands up
	var beaten: bool = float(ai.get("morale", 1.0)) < 0.25 or (float(p["hp"]) < float(p["hp_max"]) * 0.2 and rng.randf() < dt * (1.2 - float(st["nerve"])))
	if beaten:
		if rng.randf() < 0.5:
			p["state"] = "surrender"; p["surrender_t"] = 8.0
		else:
			main.peds._flee(p, me)
		if pinned_by == p: _break_pin()
		return
	if float(p.get("react_t", 0.0)) > 0.0 and ai["mode"] != "pin": return
	p["yaw"] = lerp_angle(p["yaw"], atan2(-to.x, -to.z), clampf(dt * 10.0, 0.0, 1.0))
	ai["t"] = float(ai["t"]) - dt
	match ai["mode"]:
		"approach", "circle":
			# keep ~1.6 m, circle while waiting for an opening; only two attack at once
			var want := 1.5
			var side := dirn.cross(Vector3.UP) * float(ai["circle"])
			var mv := Vector3.ZERO
			if d > want + 0.4: mv = dirn
			elif d < want - 0.5: mv = -dirn * 0.6
			mv += side * 0.5
			p["pos"] = p["pos"] + mv.normalized() * spd * 1.6 * dt if mv.length() > 0.05 else p["pos"]
			p["phase"] = fmod(p["phase"] + dt * spd * 8.0, TAU)
			if rng.randf() < dt * 0.4: ai["circle"] = -float(ai["circle"])
			if ai["t"] <= 0.0:
				if _attackers() < int(C["max_attackers"]) or pinned_by == p:
					var mvk := _choose_move(p, d)
					var m: Dictionary = C["moves"].get(mvk, {})
					if not m.is_empty() and (d < float(m["reach"]) + 0.5 or mvk == "tackle" and d < float(m.get("lunge_m", 3.5)) + 0.5):
						ai["mode"] = "wind"; ai["move"] = mvk; ai["t"] = float(m["wind"]) * (1.0 / float(st["speed"]))
						if ai.get("counter", false): ai["t"] *= 0.4; ai["counter"] = false
					else:
						ai["t"] = rng.randf_range(0.2, 0.5)
				else:
					ai["t"] = rng.randf_range(0.4, 1.0)
		"wind":
			if ai["t"] <= 0.0:
				var m2: Dictionary = C["moves"][ai["move"]]
				ai["mode"] = "strike"; ai["t"] = float(m2["strike"]); ai["hit"] = false
		"strike":
			var m3: Dictionary = C["moves"][ai["move"]]
			if ai["move"] == "tackle" and d > 0.9:       # the lunge
				p["pos"] = p["pos"] + dirn * minf(d - 0.8, 10.0 * dt)
			if not ai["hit"] and ai["t"] <= float(m3["strike"]) * 0.5:
				ai["hit"] = true
				_ped_strike(p, ai["move"], d)
			if ai["t"] <= 0.0 and ai["mode"] == "strike":
				ai["mode"] = "recover"; ai["t"] = float(m3["rec"]) * rng.randf_range(1.0, 1.6)
		"recover":
			if ai["t"] <= 0.0: ai["mode"] = "circle"; ai["t"] = rng.randf_range(0.5, 1.5) / float(st["speed"])
		"block":
			if ai["t"] <= 0.0: ai["mode"] = "circle"; ai["t"] = 0.15 if ai.get("counter", false) else 0.5
		"evade":
			var side2 := dirn.cross(Vector3.UP) * float(ai.get("side", 1.0))
			p["pos"] = p["pos"] + side2 * 5.0 * dt
			if ai["t"] <= 0.0: ai["mode"] = "circle"; ai["t"] = 0.1; ai["counter"] = true
		"pin":
			# on top of you: ground punches every ~0.9 s until you struggle free
			# kneel astride your chest (you lie on your back, head away from where you faced)
			var fwd := Vector3(-sin(main.player.model.rotation.y), 0, -cos(main.player.model.rotation.y))
			p["pos"] = me - fwd * 0.95 + fwd.cross(Vector3.UP) * 0.3
			var tc: Vector3 = (me - fwd * 0.95) - p["pos"]
			p["yaw"] = atan2(-tc.x, -tc.z)
			p["y_off"] = -0.45
			if ai["t"] <= 0.0:
				ai["t"] = rng.randf_range(0.7, 1.1); ai["gnp_t"] = 0.0
				main.hurt(rng.randf_range(4.0, 7.0), "fight")
			ai["gnp_t"] = float(ai.get("gnp_t", 0.0)) + dt

func _ped_strike(p: Dictionary, mv: String, d: float) -> void:
	var m: Dictionary = C["moves"][mv]
	if d > float(m["reach"]) + 0.3: return                  # whiffed
	if _dodge_t > 0.0: return                                # you dodged it
	var dmg: float = float(m["dmg"]) * rng.randf_range(0.85, 1.15)
	var fx: String = m["fx"]
	if pstate == "down":
		main.hurt(dmg, "fight"); return
	# guard: a tap of Q right before the hit is a parry
	if guard and fx != "takedown":
		if _guard_pressed_t < float(C["parry_window_s"]):
			parries += 1
			counter_bonus = 1.2
			p["ai"]["mode"] = "recover"; p["ai"]["t"] = 0.9; p["react_t"] = 0.4
			if main.hud: main.hud.flash("PARRY - counter!")
			return
		dmg *= float(C["block_keep"])
		if fx == "down" and rng.randf() < 0.5: fx = ""      # a solid stance can hold off a sweep
		elif fx != "down": fx = ""
	main.hurt(dmg, "fight")
	var pl = main.player
	var away: Vector3 = (pl.global_position + main.world_offset) - p["pos"]; away.y = 0; away = away.normalized()
	match fx:
		"stagger":
			if rng.randf() < 0.5: _set_pstate("stagger", 0.45); pl.velocity += away * 2.5
		"push":
			pl.velocity += away * 6.0 + Vector3(0, 1.5, 0)
			if rng.randf() < 0.2: _set_pstate("down", 1.8); times_taken_down += 1
		"down":
			_set_pstate("down", 2.0); times_taken_down += 1
		"takedown":
			_set_pstate("pinned", 9.0); times_taken_down += 1
			pinned_by = p; escape = 0.0
			p["ai"]["mode"] = "pin"; p["ai"]["t"] = 0.8
			if main.hud: main.hud.flash("Taken down - mash SPACE to break free")

func _end_fight(p: Dictionary) -> void:
	if pinned_by == p: _break_pin()
	p["state"] = "walk"; p["y_off"] = 0.0
	p.erase("ai")

## what the shader should show for this person this frame: [act, act_t]
func ped_pose(p: Dictionary) -> Array:
	if p["state"] == "surrender": return [11.0, 0.5]
	if float(p.get("react_t", 0.0)) > 0.0: return [5.0, 1.0 - float(p["react_t"]) / 0.35]
	if p["state"] != "fight" or not p.has("ai"): return [0.0, 0.0]
	var ai: Dictionary = p["ai"]
	match ai["mode"]:
		"wind":
			var m: Dictionary = C["moves"][ai["move"]]
			return [12.0 if ai["move"] in ["jab", "hook"] else float(m["pose"]), 0.25 * (1.0 - float(ai["t"]) / maxf(float(m["wind"]), 0.01))]
		"strike":
			var m2: Dictionary = C["moves"][ai["move"]]
			return [float(m2["pose"]), 1.0 - float(ai["t"]) / maxf(float(m2["strike"]), 0.01) * 0.6]
		"block": return [4.0, 0.5]
		"evade": return [13.0, 0.5]
		"pin": return [10.0, fmod(float(ai.get("gnp_t", 0.0)) * 2.5, 1.0)]
	return [4.0, 0.5]

## any fighter with "surrender" gives up for a while, then walks off
func step_surrender(p: Dictionary, dt: float) -> void:
	p["surrender_t"] = float(p["surrender_t"]) - dt
	if p["surrender_t"] <= 0.0: main.peds._flee(p, main.player.global_position + main.world_offset)

func get_save_data() -> Dictionary:
	return {"hits": hits_landed, "kos": kos, "parries": parries, "taken_down": times_taken_down}

func apply_save_data(d: Dictionary) -> void:
	hits_landed = int(d.get("hits", 0)); kos = int(d.get("kos", 0)); parries = int(d.get("parries", 0))
	times_taken_down = int(d.get("taken_down", 0))
