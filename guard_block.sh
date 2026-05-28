
# ------------------------------------------------------------
# FRESHNESS GUARD (v2.1): confirm the source had finished its
# weekly update before we publish. Defends against the mid-update
# read where the source rolls week headers forward but the price
# cells still hold last week's numbers (the 25-May failure).
# Compares this scrape vs last-published on the weeks they share.
# ------------------------------------------------------------
GUARD_ANCHOR_ARG=""
LAST_OK_WEEK="$(cat /opt/farmfayre/state/last_success_week.txt 2>/dev/null | tr -d '[:space:]')"
if [[ -n "$LAST_OK_WEEK" && "$LAST_OK_WEEK" != "$scraped_week_ending" ]]; then
    GUARD_ANCHOR_PATH="${CALC_SITE_DIR}/market_data_${LAST_OK_WEEK}.json"
    [[ -s "$GUARD_ANCHOR_PATH" ]] && GUARD_ANCHOR_ARG="--anchor ${GUARD_ANCHOR_PATH}"
fi

python3 "${SCRAPER_DIR}/freshness_guard.py" "${CALC_SITE_DIR}/market_data_internal.json" ${GUARD_ANCHOR_ARG} >> "$LOG_FILE" 2>&1
GUARD_RC=$?
if [[ $GUARD_RC -eq 4 ]]; then
    if [[ "${FF_LAST_ATTEMPT:-0}" == "1" ]]; then
        alert_failure "Source not settled after all Monday attempts" \
            "Freshness guard blocked every attempt today. livestock-live.com data never settled (mid-update or unchanged). Nothing published - live calc still shows last good week. Check the source manually."
    else
        log "WARN" "Freshness guard BLOCKED publish - source data not settled. Will retry next cron tick."
    fi
    exit 4
elif [[ $GUARD_RC -ne 0 ]]; then
    alert_failure "Freshness guard error" "freshness_guard.py exited ${GUARD_RC} (expected 0 or 4). Investigate before trusting published data."
    exit 3
fi
log "INFO" "Freshness guard passed - source data settled, safe to publish"

