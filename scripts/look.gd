class_name Look
## Art direction switch (owner, 2026-11-21): "4K upscaled Bully" style on modern geometry. Reads
## source_data/look.json; with "style": "bully" every colour texture loads from textures_bully/ (hand-painted
## versions made by tools/pipeline/make_bully_textures.py) when one exists, normal maps are softened, and
## main.gd uses the warm, soft Bully lighting preset. Command line --look=classic / --look=bully overrides.

static var _style := ""

static func style() -> String:
	if _style == "":
		_style = "classic"
		if FileAccess.file_exists("res://source_data/look.json"):
			var d = JSON.parse_string(FileAccess.get_file_as_string("res://source_data/look.json"))
			if d is Dictionary: _style = String(d.get("style", "classic"))
		for a in OS.get_cmdline_user_args():
			if a.begins_with("--look="): _style = a.substr(7)
	return _style

static func bully() -> bool:
	return style() == "bully"

## A texture path, swapped for its hand-painted version in the Bully look.
static func t(path: String) -> String:
	if bully() and path.begins_with("res://textures/"):
		var q := path.replace("res://textures/", "res://textures_bully/")
		if ResourceLoader.exists(q): return q
	return path

## Normal-map strength multiplier (painted surfaces carry their relief in the colour, not in fine bumps).
static func normal_k() -> float:
	return 0.45 if bully() else 1.0
