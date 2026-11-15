extends Node
## Basic jobs (Bible section 9): blue-collar and retail jobs at real workplaces (source_data/workplaces.json, made-up
## names), defined in source_data/jobs.json. One job at a time.
##   * Apply in person (E at a workplace's sign) or on the job board (J; 1-6 apply to the nearest openings, 0 quits).
##   * Shifts run on game hours. Clock in with E at the workplace sign (up to 30 min early). While clocked in you
##     earn the hourly rate and get tasks: marked spots to go to and press E (stock shelves, load trucks, serve a
##     table, serve the next customer, or drive a parcel to an address) - each pays a bonus.
##   * The paycheck goes to your phone wallet at the end of the shift. Missing a shift by an hour is a strike;
##     2 strikes and you're fired.
## Saved as world-state section "job".

var main: Node
var J: Dictionary
var places: Array = []
var job := {}                  # {place: id, kind: String} or {}
var clocked_in := false
var shift_day := -1            # game day number of the shift being worked / checked
var earned_shift := 0.0
var tasks_done := 0
var strikes := 0
var total_earned := 0
var task := {}                 # {pos: Vector3 world, label: String}
var _task_gap := 0.0
var _signs := {}               # place id -> Node3D
var _sign_t := 0.0
var _beam: MeshInstance3D
var board_open := false
var board: Array = []          # openings shown on the board
var _board_label: Label
var rng := RandomNumberGenerator.new()

func _ready() -> void:
	J = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/jobs.json"))
	places = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/workplaces.json"))["places"]
	rng.seed = 77
	_beam = MeshInstance3D.new()
	var cm := CylinderMesh.new(); cm.top_radius = 0.6; cm.bottom_radius = 0.6; cm.height = 40.0
	_beam.mesh = cm
	var m := StandardMaterial3D.new(); m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.albedo_color = Color(1.0, 0.8, 0.2, 0.35); m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	_beam.material_override = m; _beam.visible = false; _beam.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	main.world.add_child(_beam)
	_board_label = main.hud.overlay_label()

func place(id: int) -> Dictionary:
	return places[id] if id >= 0 and id < places.size() else {}

func def_for(kind: String) -> Dictionary:
	return J["jobs"].get(kind, {})

func place_pos(p: Dictionary) -> Vector3:
	return Vector3(float(p["x"]), 0, float(p["z"]))

func hour() -> float:
	return fposmod(main.tod.total_hours, 24.0)

func day() -> int:
	return int(floor(main.tod.total_hours / 24.0))

## is the current game time inside (or just before) today's shift?
func in_shift_window(early := 0.0) -> bool:
	if job.is_empty(): return false
	var sh: Array = def_for(job["kind"])["shift"]
	var h := hour()
	return h >= float(sh[0]) - early and h < float(sh[1])

# ------------------------------------------------------------------ hiring
func hire(place_id: int) -> bool:
	var p := place(place_id)
	if p.is_empty() or def_for(p["kind"]).is_empty(): return false
	job = {"place": place_id, "kind": p["kind"]}
	clocked_in = false; strikes = 0; task = {}; shift_day = -1
	var d := def_for(p["kind"])
	if main.hud: main.hud.flash("Hired: %s at %s, %d:00-%d:00, $%d/h" % [d["title"], p["name"], d["shift"][0], d["shift"][1], d["pay"]])
	return true

func quit_job() -> void:
	if job.is_empty(): return
	if clocked_in: _end_shift()
	job = {}; task = {}; _beam.visible = false
	if main.hud: main.hud.flash("You quit your job")

func openings_near(p: Vector3, n: int) -> Array:
	var arr: Array = []
	for pl in places:
		if def_for(pl["kind"]).is_empty(): continue
		arr.append([Vector2(float(pl["x"]) - p.x, float(pl["z"]) - p.z).length(), pl["id"]])
	arr.sort_custom(func(a, b): return a[0] < b[0])
	return arr.slice(0, n)

# ------------------------------------------------------------------ shift
func clock_in() -> bool:
	if job.is_empty() or clocked_in or not in_shift_window(float(J["clock_in_early_h"])): return false
	clocked_in = true; shift_day = day(); earned_shift = 0.0; tasks_done = 0; _task_gap = 2.0
	if main.hud: main.hud.flash("Clocked in - %s" % def_for(job["kind"])["title"])
	return true

func _end_shift() -> void:
	clocked_in = false; task = {}; _beam.visible = false
	var pay := int(round(earned_shift))
	if pay > 0 and main.money: main.money.earn(pay, "Paycheck: " + def_for(job["kind"])["title"], true)
	total_earned += pay
	if main.hud: main.hud.flash("Shift over - paycheck $%d to %s (%d tasks)" % [pay, main.money.app_name if main.money else "wallet", tasks_done])

func _process(dt: float) -> void:
	if main.tod == null: return
	_sign_t -= dt
	if _sign_t <= 0.0:
		_sign_t = 2.0
		_update_signs()
	if job.is_empty(): return
	var d := def_for(job["kind"])
	var sh: Array = d["shift"]
	var h := hour()
	if clocked_in:
		var game_h: float = dt * main.tod.time_scale * 24.0 / float(main.tod.sec_per_day)
		var p := place_pos(place(job["place"]))
		var pw: Vector3 = main.focus_world()
		var at_work: bool = Vector2(p.x - pw.x, p.z - pw.z).length() < float(J["work_radius_m"]) or d["activity"] == "deliver"
		if at_work: earned_shift += float(d["pay"]) * game_h
		if h >= float(sh[1]) or h < float(sh[0]) - float(J["clock_in_early_h"]) - 0.01:
			_end_shift()
			return
		_update_task(dt)
	else:
		# a missed shift: an hour late and not clocked in
		if h >= float(sh[0]) + float(J["late_strike_h"]) and h < float(sh[1]) and shift_day != day():
			shift_day = day()
			strikes += 1
			if strikes >= int(J["strikes_to_fire"]):
				var pn: String = place(job["place"])["name"]
				job = {}
				if main.hud: main.hud.flash("You were fired from %s for missing shifts" % pn)
			elif main.hud: main.hud.flash("You missed your shift (strike %d)" % strikes)

# ------------------------------------------------------------------ tasks
func _update_task(dt: float) -> void:
	var d := def_for(job["kind"])
	if task.is_empty():
		_task_gap -= dt
		if _task_gap <= 0.0: _new_task(d)
		return
	_beam.visible = true
	var tp: Vector3 = task["pos"]
	_beam.global_position = Vector3(tp.x, tp.y + 20.0, tp.z) - main.world_offset

func _new_task(d: Dictionary) -> void:
	var p := place_pos(place(job["place"]))
	var act: String = d["activity"]
	var tp := p
	var label := ""
	match act:
		"deliver":
			var lo: float = float(J["deliver_m"][0]); var hi: float = float(J["deliver_m"][1])
			var best := Vector3.INF
			for i in 40:
				var a := rng.randf() * TAU; var r := rng.randf_range(lo, hi)
				var q := p + Vector3(cos(a) * r, 0, sin(a) * r)
				var s := _curb(q)
				if not s.is_empty() and (s["pos"] - q).length() < 60.0: best = s["pos"]; break
			if best == Vector3.INF: best = p + Vector3(lo, 0, 0)
			tp = best; label = "Deliver the parcel"
		"register":
			tp = p; label = "Serve the next customer"
		_:
			var a2 := rng.randf() * TAU
			tp = p + Vector3(cos(a2), 0, sin(a2)) * rng.randf_range(6.0, 22.0)
			label = {"stock": "Restock this aisle", "labor": "Move this load", "serve": "Take this table's order"}.get(act, "Do this task")
	if main.services: tp.y = main.services._ground_y(tp)
	task = {"pos": tp, "label": label}

func near_task(local_pos: Vector3) -> bool:
	if task.is_empty(): return false
	var tp: Vector3 = task["pos"] - main.world_offset
	return Vector2(tp.x - local_pos.x, tp.z - local_pos.z).length() < 3.0

func complete_task() -> void:
	var d := def_for(job["kind"])
	earned_shift += float(d["bonus"])
	tasks_done += 1
	if main.hud: main.hud.flash("%s  +$%d" % ["Delivered" if d["activity"] == "deliver" else "Done", d["bonus"]])
	task = {}; _beam.visible = false
	_task_gap = float(J["task_gap_s"])

# ------------------------------------------------------------------ signs at workplaces
func _curb(p: Vector3) -> Dictionary:
	var tr = main.traffic
	if tr == null or tr.edges.is_empty(): return {}
	var best := -1; var bd := 1e9; var bq := Vector3.ZERO
	for k in tr.edges.size():
		var e: Dictionary = tr.edges[k]
		if e["cls"] > 6: continue
		var a: Vector3 = tr.npos[e["a"]]
		if Vector2(a.x - p.x, a.z - p.z).length() > float(e["len"]) + 150.0: continue
		var q := Geometry3D.get_closest_point_to_segment(p, a, tr.npos[e["b"]])
		var dd := Vector2(q.x - p.x, q.z - p.z).length()
		if dd < bd: bd = dd; best = k; bq = q
	if best < 0 or bd > 150.0: return {}
	var e2: Dictionary = tr.edges[best]
	var to := Vector3(p.x - bq.x, 0, p.z - bq.z).normalized()
	if to == Vector3.ZERO: to = Vector3(-e2["dir"].z, 0, e2["dir"].x)
	return {"pos": bq + to * (float(e2.get("w", 8.0)) * 0.5 + 3.0), "face": -to}

func _update_signs() -> void:
	if main.traffic == null or main.traffic.edges.is_empty(): return
	var f: Vector3 = main.focus_world()
	var want := {}
	for pl in places:
		if def_for(pl["kind"]).is_empty(): continue
		if Vector2(float(pl["x"]) - f.x, float(pl["z"]) - f.z).length() < 220.0: want[int(pl["id"])] = true
	if not job.is_empty(): want[int(job["place"])] = true
	for id in _signs.keys():
		if not want.has(id):
			if is_instance_valid(_signs[id]): _signs[id].queue_free()
			_signs.erase(id)
	var added := 0
	for id in want:
		if _signs.has(id) or added >= 6: continue
		var pl := place(id)
		var s := _curb(place_pos(pl))
		if s.is_empty(): continue
		added += 1
		var root := Node3D.new(); root.name = "Work_%d" % id
		main.world.add_child(root)
		var sp: Vector3 = s["pos"]
		sp.y = main.services._ground_y(sp) if main.services else 0.0
		root.global_position = sp - main.world_offset
		root.look_at(root.global_position + (s["face"] as Vector3), Vector3.UP)
		var post := MeshInstance3D.new(); var pm := BoxMesh.new(); pm.size = Vector3(0.1, 2.2, 0.1); post.mesh = pm; post.position.y = 1.1
		root.add_child(post)
		var board_m := MeshInstance3D.new(); var bm := BoxMesh.new(); bm.size = Vector3(2.5, 0.85, 0.06); board_m.mesh = bm; board_m.position.y = 2.2
		var mat := StandardMaterial3D.new(); mat.albedo_color = Color(0.95, 0.95, 0.9); board_m.material_override = mat
		root.add_child(board_m)
		var d := def_for(pl["kind"])
		var lab := Label3D.new(); lab.font_size = 34; lab.pixel_size = 0.0042; lab.modulate = Color(0.1, 0.1, 0.12); lab.width = 560.0; lab.autowrap_mode = TextServer.AUTOWRAP_OFF
		lab.text = "%s\nNOW HIRING: %s\n$%d/h · %d:00-%d:00" % [pl["name"], d["title"], d["pay"], d["shift"][0], d["shift"][1]]
		lab.position = Vector3(0, 2.2, -0.04); lab.rotation.y = PI; root.add_child(lab)
		root.set_meta("place", id)
		_signs[id] = root

func sign_near(local_pos: Vector3, max_d := 2.6) -> int:
	for id in _signs:
		var n: Node3D = _signs[id]
		if is_instance_valid(n) and Vector2(n.global_position.x - local_pos.x, n.global_position.z - local_pos.z).length() < max_d: return id
	return -1

# ------------------------------------------------------------------ interaction
func prompt(local_pos: Vector3) -> String:
	if near_task(local_pos): return "Press E: %s" % task["label"]
	var id := sign_near(local_pos)
	if id < 0: return ""
	var pl := place(id)
	if not job.is_empty() and int(job["place"]) == id:
		if clocked_in: return "%s - you're on shift" % pl["name"]
		if in_shift_window(float(J["clock_in_early_h"])): return "Press E to clock in at %s" % pl["name"]
		var sh: Array = def_for(job["kind"])["shift"]
		return "%s - your shift is %d:00-%d:00" % [pl["name"], sh[0], sh[1]]
	return "Press E to apply: %s at %s" % [def_for(pl["kind"])["title"], pl["name"]]

func try_interact(local_pos: Vector3) -> bool:
	if near_task(local_pos):
		complete_task(); return true
	var id := sign_near(local_pos)
	if id < 0: return false
	if not job.is_empty() and int(job["place"]) == id:
		if not clocked_in and not clock_in() and main.hud: main.hud.flash("It's not time for your shift")
		return true
	if not job.is_empty() and clocked_in:
		if main.hud: main.hud.flash("Finish your shift first")
		return true
	hire(id)
	return true

func _unhandled_input(e: InputEvent) -> void:
	if not (e is InputEventKey and e.pressed and not e.echo): return
	if e.physical_keycode == KEY_J:
		board_open = not board_open
		_refresh_board()
		get_viewport().set_input_as_handled()
	elif board_open and e.physical_keycode >= KEY_0 and e.physical_keycode <= KEY_9:
		var n: int = e.physical_keycode - KEY_0
		if n == 0: quit_job()
		elif n <= board.size():
			if clocked_in: main.hud.flash("Finish your shift first")
			else: hire(board[n - 1])
		board_open = false; _refresh_board()
		get_viewport().set_input_as_handled()

func _refresh_board() -> void:
	_board_label.visible = board_open
	if not board_open: return
	var pw: Vector3 = main.focus_world()
	board = []
	var lines := ["JOB BOARD (phone)  ·  number = apply  ·  0 = quit job  ·  J = close"]
	if not job.is_empty():
		var d := def_for(job["kind"])
		lines.append("Your job: %s at %s, %d:00-%d:00, $%d/h  (strikes %d)" % [d["title"], place(job["place"])["name"], d["shift"][0], d["shift"][1], d["pay"], strikes])
	var i := 1
	for o in openings_near(pw, int(J["board_size"])):
		var pl := place(o[1]); var d2 := def_for(pl["kind"])
		board.append(o[1])
		lines.append("%d. %s - %s  $%d/h  %d:00-%d:00  (%.1f km)" % [i, d2["title"], pl["name"], d2["pay"], d2["shift"][0], d2["shift"][1], o[0] / 1000.0])
		i += 1
	_board_label.text = "\n".join(lines)

func status_line() -> String:
	if job.is_empty(): return ""
	var d := def_for(job["kind"])
	if clocked_in: return "On shift: %s  ·  earned $%d  ·  %d tasks" % [d["title"], int(earned_shift), tasks_done]
	return "%s at %s  ·  shift %d:00-%d:00" % [d["title"], place(job["place"])["name"], d["shift"][0], d["shift"][1]]

func get_save_data() -> Dictionary:
	return {"job": job, "strikes": strikes, "total_earned": total_earned, "shift_day": shift_day}

func apply_save_data(dd: Dictionary) -> void:
	job = dd.get("job", {}); strikes = int(dd.get("strikes", 0)); total_earned = int(dd.get("total_earned", 0))
	shift_day = int(dd.get("shift_day", -1)); clocked_in = false; task = {}
	if job.has("place"): job["place"] = int(job["place"])
