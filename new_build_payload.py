def parse_change(cell):
    """'15.43%' -> 15.43, '-.41%' -> -0.41, '' or '-' -> None."""
    if not cell or cell.strip() in ("", "-", "\u2013", "\u2014"):
        return None
    m = re.search(r"(-?\.?\d+(?:\.\d+)?)\s*%", cell)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def build_payload(table):
    """v2.1: display structure unchanged (newest 4 weeks, oldest-first).
    ADDS full capture of every weekly price column + every Change% column
    into payload['_raw'] for audit and the freshness guard. Principle:
    scrape everything, display selectively."""
    if not table or len(table) < 2:
        raise ValueError("Weight-range table empty or missing header.")

    header = table[0]
    rows = table[1:]

    # ALL weekly price columns (not just the newest 4) for full capture
    all_price_indices = [i for i, c in enumerate(header)
                         if "PRICE" in c.upper() and "WEEK" in c.upper()]
    all_week_dates = extract_week_dates(header)  # newest -> oldest, all of them

    if len(all_price_indices) < 4 or len(all_week_dates) < 4:
        raise ValueError(f"Expected >=4 weekly price columns, got "
                         f"{len(all_price_indices)} cols / {len(all_week_dates)} dates")

    def change_idx_for(price_idx):
        # On this source the Change% cell sits immediately after each price cell
        ci = price_idx + 1
        if ci < len(header) and ("%" in header[ci] or "CHANGE" in header[ci].upper()):
            return ci
        return None

    # --- DISPLAY contract (unchanged): newest 4 weeks, oldest-first ---
    week_dates = all_week_dates[:4]
    week_ending = week_dates[0]
    weeks_oldest_first = list(reversed(week_dates))

    categories = {
        "male":   {"label": "Male",   "subcategories": {}},
        "female": {"label": "Female", "subcategories": {}},
        "calves": {"label": "Calves", "subcategories": {}},
    }

    raw_rows = []          # FULL capture: every row, every column, prices + change%
    skipped = []
    rows_added = 0

    for row in rows:
        if len(row) < 4:
            continue
        section = row[0].strip().upper()
        breed = row[1].strip().upper()
        band = parse_weight_band(row[2])

        if section not in SECTION_MAP:
            skipped.append(f"unknown section: {section}")
            continue
        if not breed:
            skipped.append(f"empty breed in {section}")
            continue
        if not band:
            skipped.append(f"bad weight band '{row[2]}' in {section} {breed}")
            continue

        # full capture across ALL columns (newest -> oldest)
        all_prices_newest = [parse_price(row[i]) if i < len(row) else None
                             for i in all_price_indices]
        all_changes_newest = []
        for pidx in all_price_indices:
            cidx = change_idx_for(pidx)
            all_changes_newest.append(
                parse_change(row[cidx]) if (cidx is not None and cidx < len(row)) else None)

        raw_rows.append({
            "section": section,
            "breed": breed,
            "band": band,
            "weeks_newest_first": all_week_dates,
            "prices_newest_first": all_prices_newest,
            "changes_newest_first": all_changes_newest,
        })

        # display contract: newest 4, oldest-first
        prices_oldest_first = list(reversed(all_prices_newest[:4]))
        if not any(p is not None for p in prices_oldest_first):
            continue

        sex, subcat_key, subcat_label = SECTION_MAP[section]
        sub_node = categories[sex]["subcategories"].setdefault(
            subcat_key, {"label": subcat_label, "breeds": {}}
        )
        breed_node = sub_node["breeds"].setdefault(breed, {})
        breed_node[band] = prices_oldest_first
        rows_added += 1

    payload = {
        "week_ending": week_ending,
        "source": "livestock-live.com",
        "weeks": weeks_oldest_first,
        "categories": categories,
        "breed_names": BREED_NAMES,
        "_raw": raw_rows,
        "_meta": {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "scraper_version": "2.1",
            "rows_added": rows_added,
            "rows_skipped": len(skipped),
            "all_weeks_newest_first": all_week_dates,
            "price_columns_captured": len(all_price_indices),
        },
    }
    return payload, skipped
