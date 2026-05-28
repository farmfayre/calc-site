#!/usr/bin/env python3
"""Farm Fayre v2.1 freshness-guard installer. Idempotent, backs up, fail-loud."""
import shutil, sys, time, subprocess
from pathlib import Path

SCR = Path("/opt/farmfayre/scraper")
TS = time.strftime("%Y%m%d-%H%M%S")

def die(msg):
    print(f"ABORT: {msg}"); sys.exit(1)

def backup(p):
    if not p.exists(): die(f"missing file: {p}")
    b = p.with_name(p.name + f".pre-guard-{TS}")
    shutil.copy2(p, b); print(f"  backup -> {b.name}")

# content provided alongside this script
NEW_BP   = (SCR/"new_build_payload.py").read_text()
GUARD_BLK= (SCR/"guard_block.sh").read_text()
GUARD_PY = (SCR/"freshness_guard.py").read_text()   # already placed by deploy step
NEW_CRON = (SCR/"new_crontab.txt").read_text()

# --- 1. scraper.py: swap build_payload (+ add parse_change) ---
sp = SCR/"scraper.py"; src = sp.read_text()
if '"scraper_version": "2.1"' in src or '"_raw"' in src:
    die("scraper.py already looks patched (found 2.1 / _raw). Nothing to do.")
try:
    a = src.index("def build_payload(table):")
    b = src.index("def write_outputs(")
except ValueError:
    die("could not find build_payload..write_outputs boundary in scraper.py")
print("scraper.py:")
backup(sp)
new_src = src[:a] + NEW_BP.rstrip() + "\n\n\n" + src[b:]
sp.write_text(new_src)
print("  build_payload replaced, parse_change added")

# --- 2. weekly_run.sh: insert guard block before 'Stage 1/4 done' ---
wr = SCR/"weekly_run.sh"; w = wr.read_text()
if "freshness_guard.py" in w:
    die("weekly_run.sh already references freshness_guard.py.")
anchor = 'log "INFO" "Stage 1/4 done"'
if anchor not in w:
    die(f"anchor not found in weekly_run.sh: {anchor!r}")
print("weekly_run.sh:")
backup(wr)
wr.write_text(w.replace(anchor, GUARD_BLK.rstrip("\n") + "\n\n" + anchor, 1))
print("  guard block inserted before Stage 1/4 done")

# --- 3. crontab.txt ---
ct = SCR/"crontab.txt"
print("crontab.txt:")
backup(ct)
ct.write_text(NEW_CRON)
print("  crontab rewritten (Mon 6-14 UTC, 2-hourly, last attempt alerts)")

# --- 4. verify ---
print("verifying syntax:")
for f in ("scraper.py", "freshness_guard.py"):
    r = subprocess.run([sys.executable, "-m", "py_compile", str(SCR/f)])
    if r.returncode != 0: die(f"py_compile FAILED: {f} (restore from .pre-guard-{TS})")
    print(f"  OK  py_compile {f}")
r = subprocess.run(["bash", "-n", str(SCR/"weekly_run.sh")])
if r.returncode != 0: die(f"bash -n FAILED: weekly_run.sh (restore from .pre-guard-{TS})")
print("  OK  bash -n weekly_run.sh")

print("\nPATCH COMPLETE. Next:")
print("  1) install cron:  sudo -u farmfayre crontab /opt/farmfayre/scraper/crontab.txt")
print("  2) test run:      sudo rm -f /opt/farmfayre/state/last_success_week.txt && \\")
print("                    sudo -u farmfayre FF_FORCE_NOW=1 /opt/farmfayre/scraper/weekly_run.sh 2>&1 | tail -25")
