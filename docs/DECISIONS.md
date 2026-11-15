# Decision log

Changes to the development bible made by the project owner. The latest explicit decision wins (Bible §0, §18).

| date | topic | bible v1.0 | new decision |
|---|---|---|---|
| 2026-11-14 | Real-time day length | 48 real minutes per game day (1 game hour = 2 real min) | **60 real minutes per game day** (1 game hour = 2.5 real min). A 12-day season is 12 real hours; a 48-day year is 48 real hours. Value lives in `source_data/climate.json` (`clock.real_seconds_per_game_day`). |
| 2026-11-14 | Graphics approach | Godot first, UE5 rebuild later | Confirmed: build the game close to finished with the current Godot look, then do the full visual upgrade in Unreal 5. |
