extends Node
## Activities (Bible section 3/9): eating out, groceries and cooking at home, gyms, bowling, watching the
## Glass City Swamp Hens, going to the movies, and fishing. T is the activity key at each place's sign.
##   * Restaurants / fast food (the workplaces of those kinds): T eats a meal.
##   * Grocery / convenience stores: T buys groceries (meals to cook at home) - also snacks.
##   * Your home: T cooks a meal from your groceries (or your fish).
##   * Gyms: T works out (an hour; fitness up). Bowling alleys: T bowls a game (Space to roll, timing matters).
##   * Ballparks: T buys a ticket when the Swamp Hens play (evenings), watch the game (3 h).
##   * Cinemas: T watches a movie (2 h). Fishing spots: T casts; when the bobber dips, press Space.
## Places: source_data/activities.json (make_activities.py). Settings: life.json.

var main: Node
var L: Dictionary
var places: Array = []
var _signs := {}
var _sign_t := 0.0
var rng := RandomNumberGenerator.new()
var games_seen := 0
var movies_seen := 0
var bowling_best := 0
# fishing
var fishing := {}          # {state: "wait"|"bite", t, spot}
# bowling
var bowling := {}          # {frames: [[a,b]], roll, meter, standing}
var _overlay: Label

func _ready() -> void:
	L = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/life.json"))
	places = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/activities.json"))["places"]
	L["sports"]["game_days"] = L["sports"]["game_days"].map(func(x): return int(x))   # JSON numbers are floats
	rng.seed = 2468
	_overlay = Label.new(); _overlay.position = Vector2(30, 160); _overlay.visible = false
	_overlay.add_theme_font_size_override("font_size", 24)
	_overlay.add_theme_color_override("font_outline_color", Color.BLACK); _overlay.add_theme_constant_override("outline_size", 7)
	if main.hud: main.hud.add_child(_overlay)

func pass_time(hours: float) -> void:
	main.tod.total_hours += hours
	main.tod.apply_now()

func place(id: int) -> Dictionary:
	return places[id] if id >= 0 and id < places.size() else {}

# ------------------------------------------------------------------ food
func eat_out(kind: String) -> bool:
	var f: Dictionary = L["food"][kind]
	if not main.money.spend(int(f["price"]), "Meal"): main.hud.flash("A meal here is $%d" % int(f["price"])); return false
	main.needs.eat(kind)
	pass_time(float(f["hours"]))
	main.hud.flash("You had %s  -$%d" % [f["label"], int(f["price"])])
	return true

func buy_groceries() -> bool:
	var G: Dictionary = L["groceries"]
	if not main.money.spend(int(G["price"]), "Groceries"): main.hud.flash("Groceries cost $%d" % int(G["price"])); return false
	main.inventory.add("food", "Groceries (1 meal)", int(G["meals"]))
	main.inventory.add("food", "Snack", 1)
	main.hud.flash("Bought groceries: %d home meals and a snack  -$%d" % [int(G["meals"]), int(G["price"])])
	return true

func cook_at_home() -> bool:
	var inv = main.inventory
	if inv.take("food", "Fish fillet"):
		main.needs.eat("fish_meal"); pass_time(0.6); main.hud.flash("You cooked the fish you caught"); return true
	if inv.take("food", "Groceries (1 meal)"):
		main.needs.eat("home_meal"); pass_time(0.7); main.hud.flash("You cooked dinner at home"); return true
	main.hud.flash("No groceries - buy some at a grocery store")
	return false

# ------------------------------------------------------------------ gym, games, movies
func workout() -> bool:
	var G: Dictionary = L["gym"]
	if not main.money.spend(int(G["price"]), "Gym"): main.hud.flash("A gym day pass is $%d" % int(G["price"])); return false
	main.needs.exercise(float(G["kcal"]), float(G["fitness"]))
	pass_time(float(G["hours"]))
	main.hud.flash("Good workout. Fitness %d" % int(main.needs.fitness))
	return true

## is there a Swamp Hens game on right now (or starting within the hour)?
func game_on() -> bool:
	var S: Dictionary = L["sports"]
	var h: float = fposmod(main.tod.total_hours, 24.0)
	var wd: int = int(floor(main.tod.total_hours / 24.0)) % 7
	return S["game_days"].has(wd) and h >= float(S["game_hours"][0]) - 1.0 and h < float(S["game_hours"][1])

func watch_game() -> bool:
	var S: Dictionary = L["sports"]
	if not game_on(): main.hud.flash("No %s game right now - evenings, most days" % S["team"]); return false
	if not main.money.spend(int(S["ticket"]), "Ticket"): main.hud.flash("A ticket is $%d" % int(S["ticket"])); return false
	var opp: String = S["opponents"][rng.randi() % S["opponents"].size()]
	var us := rng.randi_range(0, 9); var them := rng.randi_range(0, 8)
	if us == them: us += 1
	pass_time(float(S["hours"]))
	games_seen += 1
	main.hud.flash("%s %d - %s %d. %s" % [S["team"], us, opp, them, "They won!" if us > them else "Tough loss."])
	return true

func watch_movie() -> bool:
	var C: Dictionary = L["cinema"]
	if not main.money.spend(int(C["price"]), "Movie"): main.hud.flash("A ticket is $%d" % int(C["price"])); return false
	var m: String = C["movies"][rng.randi() % C["movies"].size()]
	pass_time(float(C["hours"]))
	movies_seen += 1
	main.hud.flash("You watched \"%s\"" % m)
	return true

# ------------------------------------------------------------------ fishing
func start_fishing(spot: int) -> void:
	var F: Dictionary = L["fishing"]
	fishing = {"state": "wait", "t": rng.randf_range(float(F["wait_s"][0]), float(F["wait_s"][1])), "spot": spot}
	_overlay.visible = true; _overlay.text = "Fishing... wait for a bite (T to stop)"

func _catch() -> Dictionary:
	var sp: Array = L["fishing"]["species"]
	var tot := 0.0
	for s in sp: tot += float(s["w"])
	var r := rng.randf() * tot
	for s in sp:
		r -= float(s["w"])
		if r <= 0.0: return {"name": s["name"], "kg": snappedf(rng.randf_range(float(s["kg"][0]), float(s["kg"][1])), 0.1)}
	return {"name": sp[0]["name"], "kg": 1.0}

## Space while fishing: hooks the fish if it's biting. Returns the catch or {}.
func reel() -> Dictionary:
	if fishing.is_empty(): return {}
	if fishing["state"] != "bite":
		main.hud.flash("Too early - nothing on the line"); fishing["t"] = rng.randf_range(3.0, 8.0); return {}
	var c := _catch()
	var inv = main.inventory
	inv.add("food", "Fish fillet", 1)
	if c["kg"] > float(inv.fish_log.get(c["name"], 0.0)): inv.fish_log[c["name"]] = c["kg"]
	main.hud.flash("You caught a %s (%.1f kg)!" % [c["name"], c["kg"]])
	start_fishing(int(fishing["spot"]))
	return c

func stop_fishing() -> void:
	fishing = {}; _overlay.visible = false

# ------------------------------------------------------------------ bowling (10 frames, timing)
func start_bowling() -> bool:
	var B: Dictionary = L["bowling"]
	if not main.money.spend(int(B["price"]), "Bowling"): main.hud.flash("A game is $%d" % int(B["price"])); return false
	bowling = {"frames": [], "cur": [], "meter": 0.0, "standing": 10}
	_overlay.visible = true
	return true

## one roll: how close the swinging aim is to the middle decides how many pins fall
func roll(aim: float) -> int:
	var acc: float = 1.0 - absf(aim - 0.5) * 2.0          # 1 = perfect
	var standing: int = bowling["standing"]
	var down: int = clampi(int(round(standing * pow(acc, 1.3) * rng.randf_range(0.85, 1.05))), 0, standing)
	if acc > 0.93 and standing == 10 and rng.randf() < 0.75: down = 10
	bowling["cur"].append(down)
	bowling["standing"] = standing - down
	var cur: Array = bowling["cur"]
	var last_frame: bool = bowling["frames"].size() == 9
	var done := false
	if not last_frame: done = cur.size() == 2 or down == 10 and cur.size() == 1
	else:
		done = cur.size() == 3 or (cur.size() == 2 and cur[0] + cur[1] < 10)
		if bowling["standing"] == 0 and not done: bowling["standing"] = 10
	if done:
		bowling["frames"].append(cur); bowling["cur"] = []; bowling["standing"] = 10
	return down

static func score_frames(frames: Array) -> int:
	var rolls: Array = []
	for f in frames: rolls.append_array(f)
	var total := 0; var i := 0
	for fr in range(mini(frames.size(), 10)):
		if i >= rolls.size(): break
		if rolls[i] == 10:
			total += 10 + (rolls[i + 1] if i + 1 < rolls.size() else 0) + (rolls[i + 2] if i + 2 < rolls.size() else 0); i += 1
		elif i + 1 < rolls.size() and rolls[i] + rolls[i + 1] == 10:
			total += 10 + (rolls[i + 2] if i + 2 < rolls.size() else 0); i += 2
		else:
			total += rolls[i] + (rolls[i + 1] if i + 1 < rolls.size() else 0); i += 2
	return total

func _bowling_text() -> String:
	var fr: Array = bowling["frames"]
	var parts := fr.map(func(f): return "/".join(f.map(func(x): return "X" if x == 10 else str(x))))
	var m: float = bowling["meter"]
	var bar := ""
	for k in 21: bar += "|" if absi(k - int(m * 20)) == 0 else ("+" if k == 10 else "-")
	return "BOWLING  frame %d/10  ·  score %d\n%s\n[%s]   Space = roll (aim for the middle)" % [mini(fr.size() + 1, 10), score_frames(fr), "  ".join(parts), bar]

# ------------------------------------------------------------------ per frame
func _process(dt: float) -> void:
	_sign_t -= dt
	if _sign_t <= 0.0:
		_sign_t = 2.0
		_update_signs()
	if not fishing.is_empty():
		fishing["t"] = float(fishing["t"]) - dt
		if fishing["state"] == "wait" and fishing["t"] <= 0.0:
			fishing["state"] = "bite"; fishing["t"] = float(L["fishing"]["bite_window_s"])
			_overlay.text = "BITE!  Press Space!"
		elif fishing["state"] == "bite" and fishing["t"] <= 0.0:
			fishing["state"] = "wait"; fishing["t"] = rng.randf_range(4.0, 10.0)
			_overlay.text = "It got away... wait for another bite"
		if main.current_car != null: stop_fishing()
	if not bowling.is_empty():
		bowling["meter"] = 0.5 + 0.5 * sin(Time.get_ticks_msec() / 260.0)
		_overlay.text = _bowling_text()
		if bowling["frames"].size() >= 10:
			var sc := score_frames(bowling["frames"])
			bowling_best = maxi(bowling_best, sc)
			main.hud.flash("Bowling: you scored %d" % sc)
			bowling = {}; _overlay.visible = false

func _unhandled_input(e: InputEvent) -> void:
	if not (e is InputEventKey and e.pressed and not e.echo): return
	if e.physical_keycode == KEY_SPACE:
		if not bowling.is_empty(): roll(bowling["meter"]); get_viewport().set_input_as_handled(); return
		if not fishing.is_empty(): reel(); get_viewport().set_input_as_handled(); return
	if e.physical_keycode == KEY_T and main.current_car == null:
		if try_activity(main.player.global_position): get_viewport().set_input_as_handled()

## what T does here (and the HUD prompt for it)
func _here(local_pos: Vector3) -> Dictionary:
	var id := sign_near(local_pos)
	if id >= 0:
		var p := place(id)
		match p["kind"]:
			"gym": return {"do": "gym", "text": "%s  ·  T: work out ($%d, 1 h)" % [p["name"], int(L["gym"]["price"])]}
			"bowling": return {"do": "bowling", "text": "%s  ·  T: bowl a game ($%d)" % [p["name"], int(L["bowling"]["price"])]}
			"stadium": return {"do": "game", "text": "%s  ·  T: %s game ($%d)%s" % [p["name"], L["sports"]["team"], int(L["sports"]["ticket"]), "" if game_on() else " - no game now"]}
			"cinema": return {"do": "movie", "text": "%s  ·  T: watch a movie ($%d)" % [p["name"], int(L["cinema"]["price"])]}
			"fishing": return {"do": "fish", "text": "Fishing spot  ·  T: %s" % ("stop fishing" if not fishing.is_empty() else "cast a line")}
	if main.jobs:
		var wid: int = main.jobs.sign_near(local_pos)
		if wid >= 0:
			var k: String = main.jobs.place(wid)["kind"]
			if k in ["fast_food", "restaurant"]: return {"do": k, "text": "T: eat here ($%d)" % int(L["food"][k]["price"])}
			if k in ["grocery", "convenience"]: return {"do": "groceries", "text": "T: buy groceries ($%d)" % int(L["groceries"]["price"])}
	if main.homes:
		var hid: int = main.homes.sign_near(local_pos)
		if hid >= 0 and not main.homes.home.is_empty() and int(main.homes.home["id"]) == hid:
			return {"do": "cook", "text": "T: cook a meal (%d groceries)" % main.inventory.count("food", "Groceries (1 meal)")}
	return {}

func prompt(local_pos: Vector3) -> String:
	return _here(local_pos).get("text", "")

func try_activity(local_pos: Vector3) -> bool:
	var h := _here(local_pos)
	match h.get("do", ""):
		"gym": workout()
		"bowling": start_bowling()
		"game": watch_game()
		"movie": watch_movie()
		"fish":
			if fishing.is_empty(): start_fishing(sign_near(local_pos))
			else: stop_fishing()
		"fast_food", "restaurant": eat_out(h["do"])
		"groceries": buy_groceries()
		"cook": cook_at_home()
		_: return false
	return true

# ------------------------------------------------------------------ signs
func _update_signs() -> void:
	if main.jobs == null or main.traffic == null or main.traffic.edges.is_empty(): return
	var f: Vector3 = main.focus_world()
	var want := {}
	for p in places:
		if Vector2(float(p["x"]) - f.x, float(p["z"]) - f.z).length() < 260.0: want[int(p["id"])] = true
	for id in _signs.keys():
		if not want.has(id):
			if is_instance_valid(_signs[id]): _signs[id].queue_free()
			_signs.erase(id)
	for id in want:
		if _signs.has(id): continue
		var p := place(id)
		var pos := Vector3(float(p["x"]), 0, float(p["z"]))
		var face := Vector3(0, 0, 1)
		if p["kind"] != "fishing":
			var s: Dictionary = main.jobs._curb(pos)
			if s.is_empty(): continue
			pos = s["pos"]; face = s["face"]
		pos.y = main.services._ground_y(pos) if main.services else 0.0
		var root := Node3D.new(); main.world.add_child(root)
		root.global_position = pos - main.world_offset
		root.look_at(root.global_position + face, Vector3.UP)
		var post := MeshInstance3D.new(); var pm := BoxMesh.new(); pm.size = Vector3(0.1, 2.4, 0.1); post.mesh = pm; post.position.y = 1.2
		root.add_child(post)
		var col: Color = {"gym": Color(0.2, 0.2, 0.25), "bowling": Color(0.55, 0.1, 0.5), "stadium": Color(0.1, 0.4, 0.15), "cinema": Color(0.5, 0.05, 0.05), "fishing": Color(0.1, 0.4, 0.6)}[p["kind"]]
		var bd := MeshInstance3D.new(); var bm := BoxMesh.new(); bm.size = Vector3(2.0, 0.7, 0.06); bd.mesh = bm; bd.position.y = 2.4
		var mat := StandardMaterial3D.new(); mat.albedo_color = col; bd.material_override = mat; root.add_child(bd)
		var lab := Label3D.new(); lab.text = p["name"] + ({"gym": "\nGYM · DAY PASSES", "bowling": "\nBOWLING", "stadium": "\nHOME OF THE SWAMP HENS", "cinema": "\nNOW SHOWING", "fishing": "\nPUBLIC FISHING"}[p["kind"]])
		lab.font_size = 32; lab.pixel_size = 0.0045; lab.position = Vector3(0, 2.4, -0.04); lab.rotation.y = PI; root.add_child(lab)
		_signs[id] = root

func sign_near(local_pos: Vector3, max_d := 3.0) -> int:
	for id in _signs:
		var n: Node3D = _signs[id]
		if is_instance_valid(n) and Vector2(n.global_position.x - local_pos.x, n.global_position.z - local_pos.z).length() < max_d: return id
	return -1

func get_save_data() -> Dictionary:
	return {"games_seen": games_seen, "movies_seen": movies_seen, "bowling_best": bowling_best}

func apply_save_data(d: Dictionary) -> void:
	games_seen = int(d.get("games_seen", 0)); movies_seen = int(d.get("movies_seen", 0)); bowling_best = int(d.get("bowling_best", 0))
