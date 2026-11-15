extends CanvasLayer
## Performance overlay (F3) and benchmark mode (--benchmark[=out.json]).
## Budgets live in docs/PERF_BUDGETS.md; the overlay turns a number red when it is over budget.

# Budgets for the reference PC (GTX 1080 Ti class, 1080p, default settings). Keep in sync with docs/PERF_BUDGETS.md.
const BUDGET := {"frame_ms": 16.7, "draw_calls": 3000, "primitives": 6000000, "vram_mb": 6000, "ram_mb": 6000, "chunks": 400}

var main: Node
var label: Label
var _frames: PackedFloat32Array = PackedFloat32Array()
var _bench := false
var _bench_out := ""
var _bench_t := 0.0
var _bench_stats := {"draw_calls_max": 0, "primitives_max": 0, "chunks_max": 0, "vram_mb_max": 0.0, "ram_mb_max": 0.0}
var _seg_frames := {}
var _seg_dc := {}   # segment -> peak draw calls
var _scale := 1.0   # --bench-scale=0.2 shortens every segment (smoke-testing the benchmark itself)

# Benchmark route: [name, seconds, from_pos, to_pos, look_at] in world coordinates (x, y, z), origin = downtown.
const ROUTE := [
	["downtown_street", 12.0, Vector3(195, 2.0, 70), Vector3(40, 2.0, -120), Vector3(-60, 20, -260)],
	["riverfront_low", 10.0, Vector3(420, 25, 420), Vector3(-200, 25, 650), Vector3(150, 40, 0)],
	["skyline_orbit", 10.0, Vector3(-700, 160, 900), Vector3(700, 160, 900), Vector3(150, 60, 0)],
	["neighborhood_street", 12.0, Vector3(-3180, 9.0, 2950), Vector3(-3180, 9.0, 2500), Vector3(-3180, 6.0, 2000)],
	["aerial_high", 10.0, Vector3(-2500, 900, 3000), Vector3(2500, 900, 3000), Vector3(0, 0, -1000)],
]

func _ready() -> void:
	layer = 50
	label = Label.new()
	label.position = Vector2(12, 120)
	label.add_theme_font_size_override("font_size", 15)
	label.add_theme_color_override("font_outline_color", Color.BLACK)
	label.add_theme_constant_override("outline_size", 6)
	add_child(label)
	visible = false
	if not InputMap.has_action("toggle_perf"):
		InputMap.add_action("toggle_perf")
		var ev := InputEventKey.new(); ev.physical_keycode = KEY_F3
		InputMap.action_add_event("toggle_perf", ev)
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--benchmark"):
			_bench = true
			_bench_out = a.substr(12) if a.length() > 12 else ""
		if a == "--perf":
			visible = true
		if a.begins_with("--bench-scale="):
			_scale = float(a.substr(14))
	if _bench:
		visible = true
		main.cam_override = true
		main.input_enabled = false
		main.hud.visible = false

func _unhandled_input(e: InputEvent) -> void:
	if e.is_action_pressed("toggle_perf"):
		visible = not visible

func sample() -> Dictionary:
	return {
		"fps": Engine.get_frames_per_second(),
		"frame_ms": Performance.get_monitor(Performance.TIME_PROCESS) * 1000.0,
		"physics_ms": Performance.get_monitor(Performance.TIME_PHYSICS_PROCESS) * 1000.0,
		"draw_calls": int(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)),
		"primitives": int(Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME)),
		"objects": int(Performance.get_monitor(Performance.RENDER_TOTAL_OBJECTS_IN_FRAME)),
		"vram_mb": Performance.get_monitor(Performance.RENDER_VIDEO_MEM_USED) / 1048576.0,
		"ram_mb": Performance.get_monitor(Performance.MEMORY_STATIC) / 1048576.0,
		"nodes": int(Performance.get_monitor(Performance.OBJECT_NODE_COUNT)),
		"chunks": main.streamer.loaded.size() if main and main.streamer else 0,
	}

func _fmt(name: String, v: float, unit: String, budget_key := "") -> String:
	var over: bool = budget_key != "" and BUDGET.has(budget_key) and v > BUDGET[budget_key]
	var txt := str(int(v)) if (v > 100 or is_equal_approx(v, round(v))) else "%.1f" % v
	return "%s%s: %s%s" % ["! " if over else "", name, txt, unit]

func _process(dt: float) -> void:
	if _bench:
		_bench_step(dt)
	if not visible:
		return
	var s := sample()
	var real_ms := dt * 1000.0
	label.text = "\n".join([
		"GLASS CITY perf (F3)",
		"FPS: %d   frame: %.1f ms" % [s["fps"], real_ms],
		_fmt("draw calls", s["draw_calls"], "", "draw_calls"),
		_fmt("primitives", s["primitives"] / 1000.0, "k"),
		_fmt("VRAM", s["vram_mb"], " MB", "vram_mb"),
		_fmt("RAM", s["ram_mb"], " MB", "ram_mb"),
		_fmt("chunks", s["chunks"], "", "chunks"),
		"nodes: %d" % s["nodes"],
	])
	label.modulate = Color(1, 0.45, 0.4) if real_ms > BUDGET["frame_ms"] * 1.05 else Color(0.85, 1, 0.85)

# ------------------------------------------------------------------ benchmark
var _seg := -1
var _seg_t := 0.0
var _warm := 0.0

func _bench_step(dt: float) -> void:
	var cam: Camera3D = main.camera
	if _seg == -1 or _seg_t >= ROUTE[_seg][1] * _scale:
		_seg += 1
		_seg_t = 0.0
		_warm = 0.0
		if _seg >= ROUTE.size():
			_bench_finish()
			_bench = false
			return
		var r: Array = ROUTE[_seg]
		print("[benchmark] segment ", r[0])
		main.focus_override = (r[2] + r[3]) * 0.5 * Vector3(1, 0, 1)
		# with the far city (hlod.gd) the detail radius stays near street level; without it, widen for aerial views
		main.streamer.load_radius_m = clamp(r[2].y * 2.5, 700.0, 900.0 if main.streamer.hlod != null else 4000.0)
		main.streamer.load_now(main.focus_override)
		_seg_frames[r[0]] = PackedFloat32Array()
	var r2: Array = ROUTE[_seg]
	# let streaming settle for a moment before timing each segment
	if _warm < 1.5 or not main.streamer.is_idle() and _warm < 8.0:
		_warm += dt
		cam.global_position = r2[2] - main.world_offset
		cam.look_at(r2[4] - main.world_offset, Vector3.UP)
		return
	_seg_t += dt
	var f: float = _seg_t / (r2[1] * _scale)
	var p: Vector3 = r2[2].lerp(r2[3], f)
	main.focus_override = p * Vector3(1, 0, 1)
	cam.global_position = p - main.world_offset
	cam.look_at(r2[4] - main.world_offset, Vector3.UP)
	_frames.append(dt * 1000.0)
	_seg_frames[r2[0]].append(dt * 1000.0)
	var s := sample()
	_bench_stats["draw_calls_max"] = max(_bench_stats["draw_calls_max"], s["draw_calls"])
	_seg_dc[r2[0]] = max(_seg_dc.get(r2[0], 0), s["draw_calls"])
	_bench_stats["primitives_max"] = max(_bench_stats["primitives_max"], s["primitives"])
	_bench_stats["chunks_max"] = max(_bench_stats["chunks_max"], s["chunks"])
	_bench_stats["vram_mb_max"] = max(_bench_stats["vram_mb_max"], s["vram_mb"])
	_bench_stats["ram_mb_max"] = max(_bench_stats["ram_mb_max"], s["ram_mb"])

static func _summ(fr: PackedFloat32Array) -> Dictionary:
	if fr.is_empty(): return {}
	var a := Array(fr); a.sort()
	var tot := 0.0
	for v in a: tot += v
	var avg: float = tot / a.size()
	var p95: float = a[int(a.size() * 0.95) - 1] if a.size() > 20 else a[-1]
	var p99: float = a[int(a.size() * 0.99) - 1] if a.size() > 100 else a[-1]
	return {"frames": a.size(), "avg_ms": snappedf(avg, 0.01), "avg_fps": snappedf(1000.0 / avg, 0.1),
		"p95_ms": snappedf(p95, 0.01), "p99_ms": snappedf(p99, 0.01), "low1_fps": snappedf(1000.0 / p99, 0.1), "max_ms": snappedf(a[-1], 0.01)}

func _bench_finish() -> void:
	var segs := {}
	for k in _seg_frames:
		segs[k] = _summ(_seg_frames[k])
		segs[k]["draw_calls_max"] = _seg_dc.get(k, 0)
	var res := {
		"game": "GLASS CITY", "when": Time.get_datetime_string_from_system(),
		"gpu": RenderingServer.get_video_adapter_name(), "driver": RenderingServer.get_video_adapter_vendor(),
		"cpu": OS.get_processor_name(), "threads": OS.get_processor_count(),
		"resolution": "%dx%d" % [get_viewport().get_visible_rect().size.x, get_viewport().get_visible_rect().size.y],
		"overall": _summ(_frames), "segments": segs, "peaks": _bench_stats, "budget": BUDGET,
	}
	var o: Dictionary = res["overall"]
	res["pass"] = o.get("p95_ms", 999.0) <= BUDGET["frame_ms"] * 1.5 and _bench_stats["draw_calls_max"] <= BUDGET["draw_calls"] and _bench_stats["vram_mb_max"] <= BUDGET["vram_mb"]
	var path := _bench_out if _bench_out != "" else "user://benchmark.json"
	var f := FileAccess.open(path, FileAccess.WRITE)
	f.store_string(JSON.stringify(res, "  "))
	f.close()
	print("[benchmark] ", JSON.stringify(o))
	print("[benchmark] peaks ", JSON.stringify(_bench_stats))
	print("[benchmark] wrote ", ProjectSettings.globalize_path(path), "  pass=", res["pass"])
	get_tree().quit(0)
