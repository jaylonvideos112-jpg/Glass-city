# Instructions for AI assistants working on GLASS CITY

1. Read `README.md` first: it is the complete project brief (what the game is, the bible, map, pipeline, systems,
   every file, every data list, tests, current state, owner's preferences, decisions, lessons learned).
2. **Every edit to the project must also update the README** in the same commit (owner's rule, 2026-11-21):
   update the hand-written parts in `docs/readme/` (current state, decisions, lessons) and `docs/CHANGELOG.md`,
   give new files a header comment/docstring, then run `python3 tools/make_readme.py` and commit README.md.
3. Never pick business/brand names yourself: ask the owner with options (one recommended). Every real business
   gets a parody / non-copyrighted name.
4. Character models are built with the owner's Schoolyard add-on (`tools/blender/schoolyard/`, driver
   `gen_character.py`; master copy in his Google Drive "GLASS CITY / GLASS CITY – Character Generator").
5. Commits end with the Co-Authored-By / Claude-Session trailers given in README section 10.
6. **Keep the GitHub repo current** (owner, 2026-11-27: "upload versions of the godot project and update it often so
   when I use another Claude account I can continue"): `git push origin main` after every commit. The repo is
   github.com/jaylonvideos112-jpg/Glass-city (PUBLIC, owner's choice), so never commit secrets, the owner's email,
   or county photos. The built city (data/, gitignored on main) lives on the orphan branch `city-data`; after a
   rebuild, push it again the same way (README "Getting the project").
7. Also drop a code snapshot `glass-city-YYYY-MM-DD-code.zip` into the owner's Google Drive "GLASS CITY / Game
   Backups" folder (Drive takes about 3 MB per upload from a session) and add a Change log row to "GLASS CITY —
   Master Archive" (the story canon doc) each session.
8. **Art direction is photoreal and dirty** (owner, 2026-11-28: "This is the style I want the whole game"). The map is
   built in Blender first, photo accurate, area by area (`tools/photoreal/`), then converted. The Bully look is retired.
