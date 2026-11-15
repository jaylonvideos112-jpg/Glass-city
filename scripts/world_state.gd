extends Node
## Persistent world-state framework (Bible stage 3). Any system can register a section:
##     main.world_state.register("traffic", self)   # self implements get_save_data() -> Dictionary
##                                                  #              and apply_save_data(d: Dictionary)
## One versioned JSON file holds every section. Saved on quit, every `autosave_s` real seconds, and on demand.
## Loading applies sections in registration order; unknown or missing sections are skipped, so old saves keep working
## when new systems are added (bump VERSION and add a migration in _migrate() when a section's format changes).
## Built-in sections: "clock" (time, weather, wet/snow ground), "player" (position, view, car being driven),
## "vehicles" (the player's cars: model, colour, where they were left).

const VERSION := 2
const SAVE_PATH := "user://world_state.json"
var main: Node
var sections: Array = []      # [[id, object], ...]
var autosave_s := 120.0
var _t := 0.0
var enabled := true           # --no-save turns off autosave and save-on-quit (tests, benchmarks, demos)

func _ready() -> void:
	enabled = true
	for a in OS.get_cmdline_user_args():
		if a == "--no-save" or a.begins_with("--test") or a.begins_with("--benchmark") or a.begins_with("--demo"): enabled = false
	get_tree().set_auto_accept_quit(true)

func register(id: String, obj: Object) -> void:
	for s in sections:
		if s[0] == id: s[1] = obj; return
	sections.append([id, obj])

func snapshot() -> Dictionary:
	var out := {"version": VERSION, "saved_at": Time.get_datetime_string_from_system(), "sections": {}}
	for s in sections:
		if is_instance_valid(s[1]) and s[1].has_method("get_save_data"):
			out["sections"][s[0]] = s[1].get_save_data()
	return out

func save(path := SAVE_PATH) -> bool:
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f == null: return false
	f.store_string(JSON.stringify(snapshot(), " "))
	f.close()
	return true

func load_file(path := SAVE_PATH, only: Array = []) -> bool:
	if not FileAccess.file_exists(path): return false
	var d = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not (d is Dictionary): return false
	return restore(_migrate(d), only)

## apply saved sections (all, or just the ids in `only`)
func restore(d: Dictionary, only: Array = []) -> bool:
	var secs: Dictionary = d.get("sections", {})
	for s in sections:
		if not only.is_empty() and not only.has(s[0]): continue
		if secs.has(s[0]) and is_instance_valid(s[1]) and s[1].has_method("apply_save_data"):
			s[1].apply_save_data(secs[s[0]])
	return true

## older formats -> current
func _migrate(d: Dictionary) -> Dictionary:
	if not d.has("version"):      # v1: time_of_day.gd wrote its own flat file
		return {"version": VERSION, "sections": {"clock": d}}
	return d

func _process(dt: float) -> void:
	if not enabled: return
	_t += dt
	if _t >= autosave_s:
		_t = 0.0
		save()

func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_CLOSE_REQUEST and enabled:
		save()
