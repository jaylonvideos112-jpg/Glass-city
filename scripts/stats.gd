extends Node
## Player stats, saved as world-state section "stats" (scripts/world_state.gd).
## Distances on foot and driven, top speed, game days played, bars visited (by name), emergencies seen.
## New gameplay (money, wanted level, missions) should add its counters here or register its own section.

var main: Node
var walked_m := 0.0
var driven_m := 0.0
var top_speed_mps := 0.0
var days_played := 0.0
var bars_visited := {}       # bar name -> visits
var emergencies_seen := 0
var _last := Vector3.INF

func _ready() -> void:
	if main.services: main.services.tr.scene_cleared.connect(func(_c): emergencies_seen += 1)

func on_bar_entered(name: String) -> void:
	bars_visited[name] = int(bars_visited.get(name, 0)) + 1

func _physics_process(dt: float) -> void:
	if main.cam_override: return          # demos/screenshots don't count
	var p: Vector3 = main.focus_world()
	if _last != Vector3.INF:
		var d := Vector2(p.x - _last.x, p.z - _last.z).length()
		if d < 60.0:                       # skip teleports / respawns
			if main.current_car:
				driven_m += d
				top_speed_mps = maxf(top_speed_mps, main.current_car.speed_mps())
			else: walked_m += d
	_last = p
	if main.tod: days_played += dt * main.tod.time_scale / float(main.tod.sec_per_day)

func get_save_data() -> Dictionary:
	return {"walked_m": walked_m, "driven_m": driven_m, "top_speed_mps": top_speed_mps, "days_played": days_played,
		"bars_visited": bars_visited, "emergencies_seen": emergencies_seen}

func apply_save_data(d: Dictionary) -> void:
	walked_m = float(d.get("walked_m", 0.0)); driven_m = float(d.get("driven_m", 0.0))
	top_speed_mps = float(d.get("top_speed_mps", 0.0)); days_played = float(d.get("days_played", 0.0))
	bars_visited = d.get("bars_visited", {}); emergencies_seen = int(d.get("emergencies_seen", 0))

func summary() -> String:
	return "Walked %.1f km, drove %.1f km, top speed %d mph, %d bars visited, %.1f days" % [walked_m / 1000.0, driven_m / 1000.0,
		int(top_speed_mps * 2.237), bars_visited.size(), days_played]
