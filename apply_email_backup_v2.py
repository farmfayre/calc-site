#!/usr/bin/env python3
"""Farm Fayre: swap Stage 4 (OneDrive/rclone) -> email-relay backup.
Marker-based replacement (robust to whitespace). The VM keeps NO cloud
credential - it emails the report; Power Automate files it into OneDrive.
Idempotent, backs up, bash -n verify.
"""
import shutil, sys, time, subprocess
from pathlib import Path

SCR = Path("/opt/farmfayre/scraper")
WR  = SCR/"weekly_run.sh"
ENV = Path("/opt/farmfayre/.env")
TS  = time.strftime("%Y%m%d-%H%M%S")

def die(m): print(f"ABORT: {m}"); sys.exit(1)

if not WR.exists(): die(f"missing {WR}")
if not (SCR/"send_report_email.py").exists():
    die("send_report_email.py not found in scraper dir (fetch it alongside this installer)")

src = WR.read_text()
if "send_report_email.py" in src:
    die("weekly_run.sh already references send_report_email.py. Nothing to do.")

START = "# ============================================================\n# STAGE 4:"
DONE  = "# ============================================================\n# DONE"

if src.count(START) != 1: die(f"STAGE 4 header marker count={src.count(START)} (expected 1)")
if src.count(DONE)  != 1: die(f"DONE marker count={src.count(DONE)} (expected 1)")
i = src.index(START); d = src.index(DONE)
if i >= d: die("markers out of order")

old_block = src[i:d]
print("Replacing Stage 4 block:")
print("   header:", old_block.splitlines()[1])
print("   ends  :", old_block.rstrip().splitlines()[-1])

NEW = '''# ============================================================
# STAGE 4: EMAIL REPORT FOR ONEDRIVE FILING (best-effort, no storage creds)
# ============================================================
# The VM holds NO OneDrive/cloud credential. It emails the report via the
# existing Postmark relay; a Power Automate flow files the attachments into
# the team's OneDrive folder. A send failure alerts non-fatally and never
# blocks the run or the success state already recorded after Stage 3.
REPORT_TO="${REPORT_EMAIL_TO:-kevin@farmfayre.com}"
log "INFO" "Stage 4/4: Emailing report to ${REPORT_TO} for OneDrive filing (best-effort)"

INTERNAL_DATED_TMP="/tmp/market_data_internal_${scraped_week_ending}.json"
cp "${CALC_SITE_DIR}/market_data_internal.json" "$INTERNAL_DATED_TMP" 2>/dev/null || true

if python3 "${SCRAPER_DIR}/send_report_email.py" \\
        --to "$REPORT_TO" \\
        --week "$scraped_week_ending" \\
        --attach "$PDF_FILE" \\
        --attach "${CALC_SITE_DIR}/market_data_${scraped_week_ending}.json" \\
        --attach "$INTERNAL_DATED_TMP" >> "$LOG_FILE" 2>&1; then
    log "INFO" "Stage 4/4 done - report emailed to ${REPORT_TO} for OneDrive filing"
else
    alert_failure "Report email failed (OneDrive copy not filed)" "send_report_email.py exited non-zero. Publish succeeded and the live calc is current; only the OneDrive backup copy was not sent. Check msmtp/Postmark on the VM."
fi
rm -f "$INTERNAL_DATED_TMP"

'''

new_src = src[:i] + NEW + src[d:]

bak = WR.with_name(WR.name + f".pre-email-{TS}")
shutil.copy2(WR, bak); print(f"  backup -> {bak.name}")
WR.write_text(new_src)
print("  Stage 4 swapped: OneDrive(rclone) -> email relay")

if ENV.exists():
    env = ENV.read_text()
    if "REPORT_EMAIL_TO" not in env:
        if not env.endswith("\n"): env += "\n"
        env += 'REPORT_EMAIL_TO="kevin@farmfayre.com"\n'
        ENV.write_text(env); print("  .env: added REPORT_EMAIL_TO=kevin@farmfayre.com")
    else:
        print("  .env: REPORT_EMAIL_TO already present, left as-is")
else:
    print("  WARN: .env not found; Stage 4 falls back to built-in default recipient")

r = subprocess.run(["bash","-n",str(WR)])
if r.returncode != 0: die(f"bash -n FAILED (restore from {bak.name})")
print("  OK  bash -n weekly_run.sh")
print("\nPATCH COMPLETE.")
