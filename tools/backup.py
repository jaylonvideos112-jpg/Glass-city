"""Working backup (owner, 2026-11-21: "every 20 minutes that you are working, make a backup of what you're working on,
update the readme and send it").

Writes backups/glasscity_backup_<date>_<time>.zip with:
  * all source: scripts, shaders, scenes, tests, tools, source_data, docs, README.md, CLAUDE.md, project.godot
  * every file changed since the last backup (models, textures ... anything that isn't generated city data),
    so the work in progress is always in it
  * BACKUP_NOTE.txt: the git commit, what changed, and what's being worked on
Generated data (data/, .godot/) and unchanged big art are left out (they're in git / rebuilt by tools/build.sh).
usage: python3 tools/backup.py [note]"""
import os, sys, zipfile, time, subprocess, json

R = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTD = os.path.join(os.path.dirname(R), "backups")
os.makedirs(OUTD, exist_ok=True)
STAMP = os.path.join(OUTD, ".last_backup")
last = float(open(STAMP).read()) if os.path.exists(STAMP) else 0.0
SRC_DIRS = ("scripts", "shaders", "scenes", "tests", "tools", "source_data", "docs")
SRC_FILES = ("README.md", "CLAUDE.md", "project.godot", "export_presets.cfg", ".gitignore")
SKIP_DIRS = {"data", ".godot", ".git", "__pycache__", "out"}
now = time.time()
name = time.strftime("glasscity_backup_%Y-%m-%d_%H%M.zip")
path = os.path.join(OUTD, name)
changed = []
with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(R):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel_root = os.path.relpath(root, R)
        top = rel_root.split(os.sep)[0]
        for f in files:
            p = os.path.join(root, f); rel = os.path.relpath(p, R)
            if f.endswith((".import", ".uid", ".pyc")): continue
            is_src = top in SRC_DIRS or rel in SRC_FILES
            new = os.path.getmtime(p) > last
            if is_src or (new and os.path.getsize(p) < 60 * 1024 * 1024):
                z.write(p, os.path.join("glasscity", rel))
                if new and not is_src: changed.append(rel)
                elif new: changed.append(rel)
    head = subprocess.run(["git", "-C", R, "log", "--oneline", "-1"], capture_output=True, text=True).stdout.strip()
    status = subprocess.run(["git", "-C", R, "status", "--short"], capture_output=True, text=True).stdout
    note = " ".join(sys.argv[1:]) or "work in progress"
    z.writestr("glasscity/BACKUP_NOTE.txt",
               "GLASS CITY backup %s\nLast commit: %s\nWorking on: %s\n\nChanged since the previous backup (%d files):\n%s\n\nUncommitted:\n%s\n\n"
               "Generated city data (data/) is not included: rebuild it with tools/build.sh city (see README section 3/5).\n"
               % (time.strftime("%Y-%m-%d %H:%M"), head, note, len(changed), "\n".join(sorted(changed)[:400]), status or "(none)"))
open(STAMP, "w").write(str(now))
print(path, "%.1f MB" % (os.path.getsize(path) / 1e6), "%d changed files" % len(changed))
