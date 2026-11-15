extends Node
## Simple categorized inventory (Bible section 3): weapons, food/consumables, misc/essentials. No weight or volume.
## I opens it; in the food list a number eats that item. Saved as world-state section "inventory".

var main: Node
var items := {"weapons": {}, "food": {}, "misc": {}}   # category -> {item name: count}
var fish_log := {}            # species -> biggest kg caught (collecting)
var open := false
var _label: Label
var _food_order: Array = []

func _ready() -> void:
	_label = main.hud.overlay_label()

func add(cat: String, item: String, n := 1) -> void:
	items[cat][item] = int(items[cat].get(item, 0)) + n

func take(cat: String, item: String, n := 1) -> bool:
	if int(items[cat].get(item, 0)) < n: return false
	items[cat][item] = int(items[cat][item]) - n
	if items[cat][item] <= 0: items[cat].erase(item)
	return true

func count(cat: String, item: String) -> int:
	return int(items[cat].get(item, 0))

## food items and what eating them does (needs.gd food kinds)
const FOOD_KIND := {"Snack": "snack", "Fish fillet": "fish_meal", "Groceries (1 meal)": "home_meal"}

func eat_item(item: String) -> bool:
	var kind: String = FOOD_KIND.get(item, "")
	if kind == "" or not take("food", item): return false
	main.needs.eat(kind)
	main.hud.flash("Ate %s" % item.to_lower())
	return true

func refresh() -> void:
	_label.visible = open
	if not open: return
	var lines := ["INVENTORY  ·  I = close  ·  number = eat"]
	_food_order = []
	for cat in ["food", "misc", "weapons"]:
		lines.append(cat.capitalize() + ":")
		if items[cat].is_empty(): lines.append("   (empty)")
		for it in items[cat]:
			if cat == "food" and FOOD_KIND.has(it):
				_food_order.append(it)
				lines.append("   %d. %s x%d" % [_food_order.size(), it, items[cat][it]])
			else: lines.append("   %s x%d" % [it, items[cat][it]])
	if not fish_log.is_empty():
		lines.append("Fish caught (best): " + ", ".join(fish_log.keys().map(func(k): return "%s %.1f kg" % [k, fish_log[k]])))
	lines.append(main.needs.status() if main.needs else "")
	_label.text = "\n".join(lines)

func _unhandled_input(e: InputEvent) -> void:
	if not (e is InputEventKey and e.pressed and not e.echo): return
	if e.physical_keycode == KEY_I:
		open = not open; refresh(); get_viewport().set_input_as_handled()
	elif open and e.physical_keycode >= KEY_1 and e.physical_keycode <= KEY_9:
		var n: int = e.physical_keycode - KEY_1
		if n < _food_order.size(): eat_item(_food_order[n])
		refresh(); get_viewport().set_input_as_handled()

func get_save_data() -> Dictionary:
	return {"items": items, "fish_log": fish_log}

func apply_save_data(d: Dictionary) -> void:
	var it: Dictionary = d.get("items", {})
	for cat in ["weapons", "food", "misc"]: items[cat] = it.get(cat, {})
	fish_log = d.get("fish_log", {})
