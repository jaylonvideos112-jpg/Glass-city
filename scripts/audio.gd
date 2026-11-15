extends Node
## Procedural game audio: no sound files, everything is synthesised (placeholder quality until real recordings).
##   engine  - the car you drive: harmonic hum at engine rpm with a 5-gear model, louder with throttle; tyre hiss on wet roads
##   rain    - filtered noise, loudness follows the weather's precipitation rate (muffled indoors)
##   wind    - slow gusty low noise, stronger in storms and at height
##   city    - distant traffic hum, from the number of AI cars nearby and the hour
##   thunder - low rumble a moment after each lightning flash (weather.gd emits `lightning`)
## Levels live in source_data/audio.json. --mute silences everything (tests, benchmarks).

const RATE := 22050.0
var main: Node
var A: Dictionary
var _ch := {}                 # name -> {player, playback, state...}
var _rng := RandomNumberGenerator.new()
var muted := false
var _thunder_t := -1.0        # seconds until a rumble starts
var _thunder_left := 0.0      # rumble samples left
var _thunder_amp := 0.0
var levels := {}              # last target level per channel (read by tests)

func _ready() -> void:
	A = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/audio.json"))
	muted = OS.get_cmdline_user_args().has("--mute")
	for n in ["engine", "rain", "wind", "city", "thunder", "siren"]:
		var p := AudioStreamPlayer.new()
		var g := AudioStreamGenerator.new()
		g.mix_rate = RATE
		g.buffer_length = 0.15
		p.stream = g
		p.volume_db = linear_to_db(0.0001)
		add_child(p)
		p.play()
		_ch[n] = {"p": p, "pb": p.get_stream_playback(), "phase": 0.0, "lp": 0.0, "lp2": 0.0, "lvl": 0.0, "gust": 0.0}
	if main and main.weather and main.weather.has_signal("lightning"):
		main.weather.lightning.connect(_on_lightning)

func _on_lightning() -> void:
	_thunder_t = _rng.randf_range(0.6, 3.5)    # distance delay
	_thunder_amp = _rng.randf_range(0.5, 1.0)

## 0..1 target loudness of each channel for the current situation (pure; used by tests)
func targets() -> Dictionary:
	var t := {"engine": 0.0, "rain": 0.0, "wind": 0.0, "city": 0.0, "thunder": 0.0, "siren": 0.0}
	if main == null: return t
	var indoors: bool = main.bars != null and main.bars.inside
	var car = main.current_car
	if car != null:
		t["engine"] = 1.0
	if main.weather:
		var st: Dictionary = main.weather.W["states"][main.weather.state]
		if st.get("precip", "") == "rain":
			t["rain"] = clampf(float(st.get("rate", 1.0)) / 2.2, 0.25, 1.0)
		var storm := 1.0 if main.weather.state == "storm" else 0.0
		var h: float = main.camera.global_position.y if main.camera else 2.0
		t["wind"] = clampf(0.15 + 0.5 * storm + h / 400.0 + (0.2 if st.get("precip", "") == "snow" else 0.0), 0.0, 1.0)
	if main.get("traffic") and main.traffic and main.tod:
		var n: int = main.traffic.cars.size() if "cars" in main.traffic else 0
		t["city"] = clampf(0.1 + n / 60.0, 0.0, 1.0)
	if main.get("services") and main.services:
		var d: float = main.services.nearest_siren(main.camera.global_position + main.world_offset if main.camera else main.focus_world())
		t["siren"] = clampf(1.0 - d / 450.0, 0.0, 1.0)
	if indoors:
		t["siren"] *= 0.3
		t["rain"] *= 0.25; t["wind"] *= 0.1; t["city"] *= 0.15; t["engine"] = 0.0
	return t

func _process(dt: float) -> void:
	var tg := targets()
	levels = tg
	var V: Dictionary = A["volume"]
	for n in _ch:
		var c: Dictionary = _ch[n]
		var target: float = 0.0 if muted else float(tg.get(n, 0.0)) * float(V.get(n, 0.5)) * float(V["master"])
		if n == "thunder": target = 0.0 if muted else float(V["thunder"]) * float(V["master"])
		c["lvl"] = move_toward(c["lvl"], target, dt * 1.5)
		c["p"].volume_db = linear_to_db(maxf(c["lvl"], 0.0001))
	if _thunder_t >= 0.0:
		_thunder_t -= dt
		if _thunder_t < 0.0: _thunder_left = RATE * _rng.randf_range(2.5, 5.0)
	_fill_engine(_ch["engine"])
	_fill_noise(_ch["rain"], 0.55, 0.0)
	_fill_wind(_ch["wind"])
	_fill_noise(_ch["city"], 0.02, 0.006)
	_fill_thunder(_ch["thunder"])
	_fill_siren(_ch["siren"], dt)

func _frames(c: Dictionary) -> int:
	var pb: AudioStreamGeneratorPlayback = c["pb"]
	return pb.get_frames_available() if pb else 0

## engine: rpm from road speed through a simple gearbox
func engine_rpm(speed: float, throttle: float) -> float:
	var gears: Array = A["engine"]["gear_top_mps"]
	var lo := 0.0
	for g in gears:
		if speed < float(g):
			var f := (speed - lo) / maxf(float(g) - lo, 0.1)
			return lerpf(float(A["engine"]["idle_rpm"]) + 600.0 * absf(throttle), float(A["engine"]["shift_rpm"]), clampf(f, 0.0, 1.0))
		lo = float(g)
	return float(A["engine"]["shift_rpm"])

func _fill_engine(c: Dictionary) -> void:
	var n := _frames(c)
	if n <= 0: return
	var car = main.current_car if main else null
	var spd: float = car.speed_mps() if car != null else 0.0
	var thr: float = absf(car.throttle) if car != null else 0.0
	var rpm := engine_rpm(spd, thr)
	var f0 := rpm / 60.0 * 2.0          # 4-cylinder: 2 firing pulses per revolution
	var load_ := 0.35 + 0.65 * thr
	var wet: float = main.tod.wetness if main and main.tod else 0.0
	var hiss := clampf(spd / 25.0, 0.0, 1.0) * (0.04 + 0.25 * wet)
	var pb: AudioStreamGeneratorPlayback = c["pb"]
	var ph: float = c["phase"]
	var lp: float = c["lp"]
	var buf := PackedVector2Array()
	buf.resize(n)
	for i in n:
		ph = fmod(ph + f0 / RATE, 1.0)
		var s := sin(TAU * ph) * 0.5 + sin(TAU * ph * 2.0) * 0.25 * load_ + (ph * 2.0 - 1.0) * 0.18 * load_ + sin(TAU * ph * 0.5) * 0.2
		var nz := _rng.randf_range(-1.0, 1.0)
		lp += (nz - lp) * 0.35
		s = s * 0.55 + lp * hiss
		buf[i] = Vector2(s, s)
	c["phase"] = ph; c["lp"] = lp
	pb.push_buffer(buf)

## noise through a one-pole low-pass (k = brightness); `rumble` adds a slow random walk (distant traffic)
func _fill_noise(c: Dictionary, k: float, rumble: float) -> void:
	var n := _frames(c)
	if n <= 0: return
	var pb: AudioStreamGeneratorPlayback = c["pb"]
	var lp: float = c["lp"]; var lp2: float = c["lp2"]
	var buf := PackedVector2Array()
	buf.resize(n)
	for i in n:
		lp += (_rng.randf_range(-1.0, 1.0) - lp) * k
		lp2 += (_rng.randf_range(-1.0, 1.0) - lp2) * rumble if rumble > 0.0 else 0.0
		var s := lp * (3.0 if k < 0.1 else 0.7) + lp2 * 4.0
		buf[i] = Vector2(s, s)
	c["lp"] = lp; c["lp2"] = lp2
	pb.push_buffer(buf)

func _fill_wind(c: Dictionary) -> void:
	var n := _frames(c)
	if n <= 0: return
	var pb: AudioStreamGeneratorPlayback = c["pb"]
	var lp: float = c["lp"]; var g: float = c["gust"]; var ph: float = c["phase"]
	var buf := PackedVector2Array()
	buf.resize(n)
	for i in n:
		ph = fmod(ph + 0.13 / RATE, 1.0)
		g = 0.55 + 0.45 * sin(TAU * ph) * sin(TAU * ph * 2.7 + 1.0)
		lp += (_rng.randf_range(-1.0, 1.0) - lp) * (0.01 + 0.03 * g)
		var s := lp * 4.0 * g
		buf[i] = Vector2(s, s)
	c["lp"] = lp; c["gust"] = g; c["phase"] = ph
	pb.push_buffer(buf)

## two-tone wail: the pitch sweeps up and down about every 3 s
var _siren_t := 0.0
func _fill_siren(c: Dictionary, dt: float) -> void:
	var n := _frames(c)
	if n <= 0: return
	var pb: AudioStreamGeneratorPlayback = c["pb"]
	var ph: float = c["phase"]
	var buf := PackedVector2Array()
	buf.resize(n)
	for i in n:
		_siren_t += 1.0 / RATE
		var f := 720.0 + 520.0 * (0.5 + 0.5 * sin(TAU * _siren_t / 3.2))
		ph = fmod(ph + f / RATE, 1.0)
		var s := sin(TAU * ph) * 0.6 + sin(TAU * ph * 2.0) * 0.15
		buf[i] = Vector2(s, s)
	c["phase"] = ph
	pb.push_buffer(buf)

func _fill_thunder(c: Dictionary) -> void:
	var n := _frames(c)
	if n <= 0: return
	var pb: AudioStreamGeneratorPlayback = c["pb"]
	var lp: float = c["lp"]; var lp2: float = c["lp2"]
	var buf := PackedVector2Array()
	buf.resize(n)
	for i in n:
		var s := 0.0
		if _thunder_left > 0.0:
			_thunder_left -= 1.0
			var env := minf(1.0, _thunder_left / (RATE * 2.0)) * (0.7 + 0.3 * sin(_thunder_left / RATE * 9.0))
			lp += (_rng.randf_range(-1.0, 1.0) - lp) * 0.01
			lp2 += (lp - lp2) * 0.05
			s = lp2 * 9.0 * env * _thunder_amp
		buf[i] = Vector2(s, s)
	c["lp"] = lp; c["lp2"] = lp2
	pb.push_buffer(buf)
