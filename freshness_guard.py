#!/usr/bin/env python3
"""
Farm Fayre freshness guard - v1

Decides whether a freshly-scraped internal JSON is SAFE TO PUBLISH or whether
the source was caught mid-update (the 25-May failure: source updates row-by-row
through Monday morning, so an early scrape mixes fresh + week-stale rows under
the new week's labels).

Two independent checks:

  PRIMARY  - overlap match vs last published (anchor).
             A correct scrape's overlapping weeks match what we already
             published. A shifted/partial row mismatches because its
             "last week" column secretly holds the week-before's number.
             This is the real detector. Needs an anchor (skipped on first run).

  SECONDARY- internal Change% consistency (anchor-free backstop).
             For each row, stated Change% must match the price ratio.
             Catches gross parse garble even with no prior to compare to.
             NOTE: a cleanly-shifted row stays internally consistent, so this
             does NOT catch shifts - that's the PRIMARY's job. This is the
             week-1 / garbage safety net only.

Exit codes:
  0  PASS  - safe to publish
  4  BLOCK - do not publish, retry next cron tick (matches existing convention)
"""
import json
import sys
import argparse

# --- tunables (kept as constants so they're easy to adjust as we see weeks) ---
PRICE_TOL          = 0.051   # 5c: treat <=5c diff as a match (public is 5c-rounded)
# Bias HARD toward blocking: a false block = one extra retry (cheap);
# a false pass = stale data shipped to customers (the bug we are killing).
OVERLAP_CELL_PCT   = 0.12    # block if >12% of comparable overlap cells mismatch
SHIFTED_ROW_PCT    = 0.03    # OR block if >3% of rows are "shifted" (multi-week row mismatch)
SHIFTED_ROW_MIN    = 3       # OR block on >=3 clearly-shifted rows in absolute terms
CHANGE_TOL_PCT     = 2.0     # Change% allowed to differ from computed ratio by 2pts
CHANGE_FAIL_PCT    = 0.20    # block if >20% of checkable rows are change-inconsistent


def iter_bands(payload):
    """Yield ((sex, subcat, breed, band), prices_oldest_first) for every cell."""
    for sex, sex_node in payload.get("categories", {}).items():
        for subcat, sub in sex_node.get("subcategories", {}).items():
            for breed, bands in sub.get("breeds", {}).items():
                for band, prices in bands.items():
                    yield (sex, subcat, breed, band), prices


def primary_overlap_check(cand, anchor):
    """Compare candidate vs anchor on the weeks they share. Returns dict."""
    cand_weeks = cand.get("weeks", [])
    anch_weeks = anchor.get("weeks", [])
    shared = [w for w in cand_weeks if w in anch_weeks]
    if not shared:
        return {"ran": False, "reason": "no shared weeks with anchor"}

    # index anchor cells for lookup
    anchor_map = {}
    for key, prices in iter_bands(anchor):
        anchor_map[key] = prices

    cells_compared = 0
    cells_mismatch = 0
    shifted_rows = 0
    rows_with_data = 0
    examples = []

    for key, c_prices in iter_bands(cand):
        if key not in anchor_map:
            continue
        a_prices = anchor_map[key]
        row_mismatch = 0
        row_compared = 0
        for w in shared:
            ci = cand_weeks.index(w)
            ai = anch_weeks.index(w)
            if ci >= len(c_prices) or ai >= len(a_prices):
                continue
            cv, av = c_prices[ci], a_prices[ai]
            if cv is None or av is None:
                continue
            row_compared += 1
            cells_compared += 1
            if abs(cv - av) > PRICE_TOL:
                cells_mismatch += 1
                row_mismatch += 1
        if row_compared:
            rows_with_data += 1
        # a "shifted" row = mismatches on a majority of its shared weeks
        if row_compared >= 2 and row_mismatch >= 2:
            shifted_rows += 1
            if len(examples) < 6:
                examples.append((key, [(w, a_prices[anch_weeks.index(w)],
                                        c_prices[cand_weeks.index(w)]) for w in shared]))

    pct = (cells_mismatch / cells_compared) if cells_compared else 0.0
    shifted_pct = (shifted_rows / rows_with_data) if rows_with_data else 0.0
    block = (pct > OVERLAP_CELL_PCT
             or shifted_pct > SHIFTED_ROW_PCT
             or shifted_rows >= SHIFTED_ROW_MIN)
    return {
        "ran": True, "shared_weeks": shared,
        "cells_compared": cells_compared, "cells_mismatch": cells_mismatch,
        "mismatch_pct": pct, "shifted_rows": shifted_rows,
        "rows_with_data": rows_with_data, "shifted_pct": shifted_pct,
        "block": block, "examples": examples,
    }


def secondary_change_check(cand):
    """Internal Change% consistency using _raw. Anchor-free backstop."""
    raw = cand.get("_raw")
    if not raw:
        return {"ran": False, "reason": "no _raw change data captured"}
    rows_checked = 0
    rows_bad = 0
    examples = []
    for r in raw:
        prices = r.get("prices_newest_first") or []
        changes = r.get("changes_newest_first") or []
        bad_here = 0
        chk_here = 0
        for n in range(len(prices) - 1):
            new, old = prices[n], prices[n + 1]
            ch = changes[n] if n < len(changes) else None
            if new is None or old is None or ch is None or old == 0:
                continue
            computed = (new / old - 1.0) * 100.0
            chk_here += 1
            if abs(computed - ch) > CHANGE_TOL_PCT:
                bad_here += 1
        if chk_here:
            rows_checked += 1
            if bad_here:
                rows_bad += 1
                if len(examples) < 6:
                    examples.append((r.get("section"), r.get("breed"), r.get("band")))
    pct = (rows_bad / rows_checked) if rows_checked else 0.0
    block = pct > CHANGE_FAIL_PCT
    return {"ran": True, "rows_checked": rows_checked, "rows_bad": rows_bad,
            "bad_pct": pct, "block": block, "examples": examples}


def fully_stale_check(cand, anchor):
    """Newest column identical to anchor's newest AND different week label = stale republish."""
    if cand.get("week_ending") == anchor.get("week_ending"):
        return {"ran": False, "reason": "same week_ending as anchor (re-run, not stale)"}
    anchor_newest = {}
    for key, prices in iter_bands(anchor):
        if prices and prices[-1] is not None:
            anchor_newest[key] = prices[-1]
    if not anchor_newest:
        return {"ran": False, "reason": "anchor has no newest data"}
    same = 0
    total = 0
    for key, prices in iter_bands(cand):
        if prices and prices[-1] is not None and key in anchor_newest:
            total += 1
            if abs(prices[-1] - anchor_newest[key]) <= PRICE_TOL:
                same += 1
    pct = (same / total) if total else 0.0
    block = pct >= 0.98  # ~all newest cells identical to last week = nothing advanced
    return {"ran": True, "identical_pct": pct, "block": block, "total": total}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate", help="fresh internal JSON just scraped")
    ap.add_argument("--anchor", help="last published internal JSON (dated archive)", default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    with open(args.candidate) as f:
        cand = json.load(f)

    anchor = None
    if args.anchor:
        try:
            with open(args.anchor) as f:
                anchor = json.load(f)
        except FileNotFoundError:
            anchor = None

    verdicts = []
    block = False

    if anchor:
        p = primary_overlap_check(cand, anchor)
        verdicts.append(("PRIMARY overlap", p))
        if p.get("block"):
            block = True
        s = fully_stale_check(cand, anchor)
        verdicts.append(("fully-stale", s))
        if s.get("block"):
            block = True
    else:
        verdicts.append(("PRIMARY overlap", {"ran": False, "reason": "no anchor (first run / last week missing)"}))

    c = secondary_change_check(cand)
    verdicts.append(("SECONDARY change%", c))
    if c.get("block"):
        block = True

    if not args.quiet:
        for name, v in verdicts:
            print(f"[guard] {name}: {json.dumps(v, default=str)}")

    if block:
        print("[guard] VERDICT: BLOCK - data not settled, do not publish, retry")
        sys.exit(4)
    print("[guard] VERDICT: PASS - safe to publish")
    sys.exit(0)


if __name__ == "__main__":
    main()
