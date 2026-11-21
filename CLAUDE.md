# Instructions for AI assistants working on GLASS CITY

1. Read `README.md` first: it is the complete project brief (what the game is, the bible, map, pipeline, systems,
   every file, every data list, tests, current state, owner's preferences, decisions, lessons learned).
2. **Every edit to the project must also update the README** in the same commit (owner's rule, 2026-11-21):
   update the hand-written parts in `docs/readme/` (current state, decisions, lessons) and `docs/CHANGELOG.md`,
   give new files a header comment/docstring, then run `python3 tools/make_readme.py` and commit README.md.
3. Never pick business/brand names yourself: ask the owner with options (one recommended). Every real business
   gets a parody / non-copyrighted name.
4. Character models are built with the MPFB2-based creator in `tools/blender/charcreator/`.
5. Commits end with the Co-Authored-By / Claude-Session trailers given in README section 10.
