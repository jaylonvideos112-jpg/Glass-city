extends Node
## Player needs (Bible section 3): health and stamina are the only formal attributes, plus moderate hunger and basic
## fitness. Weight changes slowly with what you eat versus what you burn - a simulation, not a body ideal.
##   hunger 100 = full, empties over ~30 game hours; at 0 you lose health slowly and stamina recovers slower.
##   stamina drains while sprinting; at 0 you can't sprint. Max stamina and sprint speed grow with fitness.
##   fitness rises with gym sessions and running, and slowly fades if you don't.
## Saved as world-state section "needs". Settings: source_data/life.json "needs".

var main: Node
var L: Dictionary
var N: Dictionary
var health := 100.0
var stamina := 100.0
var hunger := 80.0
var fitness := 30.0
var weight_kg := 86.0
var kcal_today := 0.0
var burn_today := 0.0
var km_run_today := 0.0
var _day := -1
var _last := Vector3.INF

func _ready() -> void:
	L = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/life.json"))
	N = L["needs"]
	var st: Dictionary = N["start"]
	health = st["health"]; hunger = st["hunger"]; fitness = st["fitness"]; weight_kg = st["weight_kg"]
	stamina = minf(float(st["stamina"]), max_stamina())

func max_stamina() -> float:
	return 70.0 + 0.3 * fitness

func sprint_mult() -> float:
	return 1.0 + 0.002 * (fitness - 30.0)

func game_hours(dt: float) -> float:
	return dt * main.tod.time_scale * 24.0 / float(main.tod.sec_per_day)

func eat(kind: String) -> Dictionary:
	var f: Dictionary = L["food"][kind]
	hunger = minf(100.0, hunger + float(f["hunger"]))
	kcal_today += float(f["kcal"])
	return f

func exercise(kcal: float, fit: float) -> void:
	burn_today += kcal
	fitness = minf(100.0, fitness + fit)
	stamina = max_stamina()

## end of a game day: weight moves by the day's calorie balance (7700 kcal per kg), fitness fades a little
func close_day() -> void:
	var burn: float = float(N["base_burn_kcal_day"]) * (weight_kg / 86.0) + burn_today
	weight_kg = clampf(weight_kg + (kcal_today - burn) / 7700.0, 55.0, 160.0)
	fitness = maxf(0.0, fitness - float(N["fitness_decay_per_day"]))
	kcal_today = 0.0; burn_today = 0.0; km_run_today = 0.0

func _process(dt: float) -> void:
	if main.tod == null or main.cam_override: return
	var gh := game_hours(dt)
	hunger = maxf(0.0, hunger - gh * 100.0 / float(N["hunger_hours_to_empty"]))
	if hunger <= 0.0: health = maxf(5.0, health - gh * float(N["starving_health_per_hour"]))
	elif hunger > 40.0: health = minf(100.0, health + gh * 3.0)
	var p = main.player
	var running: bool = main.current_car == null and p.sprint and Vector2(p.velocity.x, p.velocity.z).length() > 5.0
	stamina = minf(stamina, max_stamina())
	if running:
		stamina = maxf(0.0, stamina - dt * float(N["stamina_sprint_per_s"]))
	else:
		stamina = minf(max_stamina(), stamina + dt * float(N["stamina_regen_per_s"]) * (float(N["hungry_regen_factor"]) if hunger < 15.0 else 1.0))
	# distance on foot at a run counts toward fitness and calories
	var pw: Vector3 = main.focus_world()
	if _last != Vector3.INF and running:
		var d := Vector2(pw.x - _last.x, pw.z - _last.z).length()
		if d < 20.0:
			km_run_today += d / 1000.0
			burn_today += d / 1000.0 * float(N["run_kcal_per_km"])
			fitness = minf(100.0, fitness + d / 1000.0 * float(N["fitness_per_km_run"]))
	_last = pw
	var day := int(floor(main.tod.total_hours / 24.0))
	if _day < 0: _day = day
	if day > _day:
		for i in mini(day - _day, 7): close_day()
		_day = day

func can_sprint() -> bool:
	return stamina > 1.0

func status() -> String:
	return "Health %d · Stamina %d · Hunger %d · Fitness %d · %d lb" % [int(health), int(stamina), int(hunger), int(fitness), int(weight_kg * 2.2046)]

func get_save_data() -> Dictionary:
	return {"health": health, "stamina": stamina, "hunger": hunger, "fitness": fitness, "weight_kg": weight_kg, "day": _day}

func apply_save_data(d: Dictionary) -> void:
	health = float(d.get("health", health)); stamina = float(d.get("stamina", stamina)); hunger = float(d.get("hunger", hunger))
	fitness = float(d.get("fitness", fitness)); weight_kg = float(d.get("weight_kg", weight_kg)); _day = int(d.get("day", -1))
