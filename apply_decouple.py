#!/usr/bin/env python3
"""Farm Fayre weekly_run.sh patch: decouple success-state from OneDrive.
Idempotent, backs up, fail-loud, bash -n verify.
  1. Record last_success_week.txt right after Stage 3 (publish) succeeds.
  2. Make Stage 4 (OneDrive) best-effort: alert/warn but never abort or
     roll back success.
  3. Drop the now-redundant success write at the bottom.
"""
import shutil, sys, time, subprocess
from pathlib import Path

WR = Path("/opt/farmfayre/scraper/weekly_run.sh")
TS = time.strftime("%Y%m%d-%H%M%S")

def die(m): print(f"ABORT: {m}"); sys.exit(1)

if not WR.exists(): die(f"missing {WR}")
src = WR.read_text()

if "Success state recorded" in src:
    die("weekly_run.sh already patched (found 'Success state recorded'). Nothing to do.")

# ---- EDIT 1: record success right after Stage 3 done ----
OLD1 = 'log "INFO" "Stage 3/4 done"'
NEW1 = '''log "INFO" "Stage 3/4 done"

# ------------------------------------------------------------
# PUBLISH SUCCEEDED -> record success state NOW, before the backup.
# The live calc is updated and this week's dated archive (next week's
# clean guard anchor) is already on disk from Stage 1. OneDrive (Stage 4)
# is offsite backup only and must never gate this: a backup outage would
# otherwise stall the freshness-guard anchor chain.
# ------------------------------------------------------------
echo "$this_publish_week" > "$LAST_SUCCESS_FILE"
log "INFO" "Success state recorded (week ${this_publish_week}) - anchor chain advanced; OneDrive backup is best-effort from here"'''

if src.count(OLD1) != 1: die(f"EDIT1 anchor count != 1 ({src.count(OLD1)})")
src = src.replace(OLD1, NEW1, 1)

# ---- EDIT 2: Stage 4 becomes best-effort (no exit 7) ----
OLD2 = '''# ============================================================
# STAGE 4: UPLOAD PDF + JSONs TO ONEDRIVE
# ============================================================
log "INFO" "Stage 4/4: Uploading PDF + JSONs to OneDrive"

if ! command -v rclone >/dev/null 2>&1; then
    alert_failure "rclone not installed" "rclone command not found"
    exit 7
fi

# Test connectivity to OneDrive remote
if ! rclone lsd "${ONEDRIVE_REMOTE%:*}:" --max-depth 0 >> "$LOG_FILE" 2>&1; then
    alert_failure "OneDrive auth failed" "rclone cannot reach ${ONEDRIVE_REMOTE}. OAuth may have expired - run 'rclone config reconnect onedrive:' on the VM."
    exit 7
fi

# Upload the PDF
if ! rclone copy "$PDF_FILE" "$ONEDRIVE_REMOTE/" --log-file="$LOG_FILE" --log-level=INFO; then
    alert_failure "OneDrive upload failed" "rclone copy returned non-zero. Check log for details."
    exit 7
fi

# Also upload the dated JSON archive for completeness
JSON_ARCHIVE="${CALC_SITE_DIR}/market_data_${scraped_week_ending}.json"
if [[ -s "$JSON_ARCHIVE" ]]; then
    rclone copy "$JSON_ARCHIVE" "$ONEDRIVE_REMOTE/" --log-file="$LOG_FILE" --log-level=INFO || \\
        log "WARN" "JSON archive upload failed (non-fatal)"
fi

# Audit-trail: upload the INTERNAL (unrounded, full taxonomy) JSON alongside the public.
# This is the unambiguous source of truth for any future question about what was scraped.
INTERNAL_JSON="${CALC_SITE_DIR}/market_data_internal.json"
if [[ -s "$INTERNAL_JSON" ]]; then
    # Rename on upload so it's easy to spot in OneDrive next to the dated version
    INTERNAL_DATED="market_data_internal_${scraped_week_ending}.json"
    rclone copyto "$INTERNAL_JSON" "$ONEDRIVE_REMOTE/${INTERNAL_DATED}" --log-file="$LOG_FILE" --log-level=INFO || \\
        log "WARN" "Internal JSON upload failed (non-fatal)"
fi

log "INFO" "Stage 4/4 done - PDF + JSONs in OneDrive"'''

NEW2 = '''# ============================================================
# STAGE 4: BACKUP TO ONEDRIVE (best-effort - never gates success)
# ============================================================
# Publish already succeeded and the success state is recorded above.
# OneDrive is an offsite backup of the PDF + JSON archives. A backup
# outage (expired OAuth, Microsoft throttling) must NOT fail the run or
# stall the guard's anchor chain - so every failure here alerts or warns
# but lets the run finish clean.
log "INFO" "Stage 4/4: Backing up PDF + JSONs to OneDrive (best-effort)"

if ! command -v rclone >/dev/null 2>&1; then
    alert_failure "rclone not installed (backup skipped)" "rclone command not found. Publish succeeded; offsite backup did not run."
elif ! rclone lsd "${ONEDRIVE_REMOTE%:*}:" --max-depth 0 >> "$LOG_FILE" 2>&1; then
    alert_failure "OneDrive unreachable (backup skipped)" "rclone cannot reach ${ONEDRIVE_REMOTE}. OAuth may have expired or Microsoft is throttling - run 'rclone config reconnect onedrive:' on the VM. Publish succeeded; only the offsite backup is affected."
else
    # Connectivity OK - upload PDF + both JSON archives. Individual
    # failures warn but never abort.
    rclone copy "$PDF_FILE" "$ONEDRIVE_REMOTE/" --log-file="$LOG_FILE" --log-level=INFO || \\
        log "WARN" "PDF upload failed (non-fatal)"

    JSON_ARCHIVE="${CALC_SITE_DIR}/market_data_${scraped_week_ending}.json"
    if [[ -s "$JSON_ARCHIVE" ]]; then
        rclone copy "$JSON_ARCHIVE" "$ONEDRIVE_REMOTE/" --log-file="$LOG_FILE" --log-level=INFO || \\
            log "WARN" "JSON archive upload failed (non-fatal)"
    fi

    # Audit-trail: the INTERNAL (unrounded, full taxonomy) JSON.
    INTERNAL_JSON="${CALC_SITE_DIR}/market_data_internal.json"
    if [[ -s "$INTERNAL_JSON" ]]; then
        INTERNAL_DATED="market_data_internal_${scraped_week_ending}.json"
        rclone copyto "$INTERNAL_JSON" "$ONEDRIVE_REMOTE/${INTERNAL_DATED}" --log-file="$LOG_FILE" --log-level=INFO || \\
            log "WARN" "Internal JSON upload failed (non-fatal)"
    fi

    log "INFO" "Stage 4/4 done - PDF + JSONs in OneDrive"
fi'''

if src.count(OLD2) != 1: die(f"EDIT2 anchor count != 1 ({src.count(OLD2)})")
src = src.replace(OLD2, NEW2, 1)

# ---- EDIT 3: drop the redundant success write at the bottom ----
OLD3 = '''# ============================================================
# SUCCESS
# ============================================================
echo "$this_publish_week" > "$LAST_SUCCESS_FILE"
log "INFO" "=== Weekly pipeline COMPLETE for week ${scraped_week_ending} ==="
log "INFO" "Live calculator: https://calc.farmfayre.com"
log "INFO" "PDF in OneDrive: ${ONEDRIVE_REMOTE}/farmfayre_report_${scraped_week_ending}.pdf"

exit 0'''

NEW3 = '''# ============================================================
# DONE (success state already recorded after Stage 3)
# ============================================================
log "INFO" "=== Weekly pipeline COMPLETE for week ${scraped_week_ending} ==="
log "INFO" "Live calculator: https://calc.farmfayre.com"

exit 0'''

if src.count(OLD3) != 1: die(f"EDIT3 anchor count != 1 ({src.count(OLD3)})")
src = src.replace(OLD3, NEW3, 1)

# ---- backup + write ----
bak = WR.with_name(WR.name + f".pre-decouple-{TS}")
shutil.copy2(WR, bak)
print(f"  backup -> {bak.name}")
WR.write_text(src)
print("  3 edits applied (success-after-stage3, best-effort stage4, redundant write removed)")

# ---- verify ----
r = subprocess.run(["bash", "-n", str(WR)])
if r.returncode != 0: die(f"bash -n FAILED (restore from {bak.name})")
print("  OK  bash -n weekly_run.sh")
print("\nPATCH COMPLETE.")
