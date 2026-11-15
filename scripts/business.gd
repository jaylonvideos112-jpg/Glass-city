extends Node
## Business ownership (Bible section 9): buy nearly any business on the map (the workplaces in
## source_data/workplaces.json). Simple, passive income: no staff or stock to manage.
##   * Price depends on the kind of business, its size and where it is (downtown costs more) - business.json.
##   * Income accrues every game day; it goes to your phone wallet automatically, or (with auto-deposit off, key
##     N at the sign) piles up at the business for you to collect in person.
##   * Buy / collect with B at the business's sign. Saved as world-state section "business".

var main: Node
var B: Dictionary
var owned := {}           # place id -> {"stored": float, "since_day": int}
var auto_deposit := true
var _last_day := -1
var income_total := 0

func _ready() -> void:
	B = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/business.json"))
	auto_deposit = bool(B.get("auto_deposit_default", true))

func price(id: int) -> int:
	var p: Dictionary = main.jobs.place(id)
	if p.is_empty(): return 0
	var base: float = float(B["base_price"].get(p["kind"], 80000))
	var size_f: float = clampf(sqrt(float(p.get("size", 8)) / 8.0), 0.75, 2.0)
	var dist: float = Vector2(float(p["x"]), float(p["z"])).length()
	var loc_f: float = lerpf(float(B["downtown_factor"]), 1.0, clampf(dist / float(B["downtown_falloff_m"]), 0.0, 1.0))
	return int(round(base * size_f * loc_f / 500.0)) * 500

## income per game day (before the day's random swing)
func daily_income(id: int) -> int:
	return int(round(price(id) * float(B["daily_yield"])))

func buy(id: int) -> bool:
	if owned.has(id) or main.money == null: return false
	var pr := price(id)
	if not main.money.spend(pr, "Bought " + main.jobs.place(id)["name"]):
		if main.hud: main.hud.flash("You need $%d to buy this" % pr)
		return false
	owned[id] = {"stored": 0.0, "since_day": main.jobs.day()}
	if main.hud: main.hud.flash("You bought %s for $%d - about $%d a day" % [main.jobs.place(id)["name"], pr, daily_income(id)])
	return true

func collect(id: int) -> int:
	if not owned.has(id): return 0
	var amt := int(owned[id]["stored"])
	owned[id]["stored"] = 0.0
	if amt > 0 and main.money: main.money.earn(amt, "Collected from " + main.jobs.place(id)["name"], false)
	if main.hud: main.hud.flash("Collected $%d" % amt if amt > 0 else "Nothing to collect yet")
	return amt

## pay out one game day of income for every owned business
func pay_day() -> int:
	var tot := 0
	for id in owned:
		var swing: float = 1.0 + randf_range(-float(B["daily_swing"]), float(B["daily_swing"]))
		var amt: int = int(round(daily_income(id) * swing))
		tot += amt
		if auto_deposit: main.money.earn(amt, "Income: " + main.jobs.place(id)["name"], true)
		else: owned[id]["stored"] = float(owned[id]["stored"]) + amt
	income_total += tot
	if tot > 0 and main.hud: main.hud.flash("Business income: $%d %s" % [tot, "to " + main.money.app_name if auto_deposit else "waiting at your businesses"])
	return tot

func _process(_dt: float) -> void:
	if main.tod == null or main.jobs == null: return
	var d: int = main.jobs.day()
	if _last_day < 0: _last_day = d
	if d > _last_day:
		for i in mini(d - _last_day, 7): pay_day()
		_last_day = d

func prompt(local_pos: Vector3) -> String:
	var id: int = main.jobs.sign_near(local_pos)
	if id < 0: return ""
	if owned.has(id):
		return "Your business  ·  B: collect $%d  ·  N: auto-deposit %s" % [int(owned[id]["stored"]), "ON" if auto_deposit else "OFF"]
	return "B: buy this business for $%d (about $%d/day)" % [price(id), daily_income(id)]

func try_key(local_pos: Vector3, key: int) -> bool:
	var id: int = main.jobs.sign_near(local_pos)
	if id < 0: return false
	if key == KEY_B:
		if owned.has(id): collect(id)
		else: buy(id)
		return true
	if key == KEY_N and owned.has(id):
		auto_deposit = not auto_deposit
		if main.hud: main.hud.flash("Auto-deposit %s" % ("on" if auto_deposit else "off"))
		return true
	return false

func _unhandled_input(e: InputEvent) -> void:
	if e is InputEventKey and e.pressed and not e.echo and (e.physical_keycode == KEY_B or e.physical_keycode == KEY_N):
		if main.current_car == null and try_key(main.player.global_position, e.physical_keycode):
			get_viewport().set_input_as_handled()

func get_save_data() -> Dictionary:
	var o := {}
	for id in owned: o[str(id)] = owned[id]
	return {"owned": o, "auto_deposit": auto_deposit, "last_day": _last_day, "income_total": income_total}

func apply_save_data(d: Dictionary) -> void:
	owned = {}
	for k in d.get("owned", {}): owned[int(k)] = d["owned"][k]
	auto_deposit = bool(d.get("auto_deposit", true)); _last_day = int(d.get("last_day", -1)); income_total = int(d.get("income_total", 0))
