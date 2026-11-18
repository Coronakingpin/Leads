import csv
from datetime import datetime

from leads.trades import CODE_TO_TRADES, TRADES, build
from leads.violations import load

HEADER = ["B1_ALT_ID", "FullAddress", "PartialAddress", "Longitude", "Latitude", "PARCEL_ID",
          "CouncilDist", "G6A_G6_COMPL_DD", "G6A_G6_STATUS", "OccupancyStatus",
          "GUIDE_ITEM_TEXT", "VIOLATION_CODE", "GUIDE_ITEM_STATUS", "CitationAmount"]


def _row(parcel, visit, date, case_status, code, item_status, amount="0"):
    return [visit, f"{parcel} ST, LOUISVILLE, KY 40215-0000", f"{parcel} ST", "-85.7", "38.2",
            parcel, "6", date, case_status, "Occupied Structure",
            f"{code} - THING  [1] text", code, item_status, amount]


def test_every_code_maps_to_a_known_trade():
    for code, trades in CODE_TO_TRADES.items():
        assert trades and all(t in TRADES for t in trades), code


def test_roofing_leads_use_latest_status_per_code(tmp_path):
    path = tmp_path / "v.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        # P1: roof cited, still open -> lead.
        w.writerow(_row("P1", "A-PM-1", "11/1/2026 9:00:00 AM", "Citation", "X50", "Citation 1", "700"))
        # P2: roof was open, then a later visit shows it was fixed and the case closed -> not a lead.
        w.writerow(_row("P2", "B-PM-1", "11/1/2026 9:00:00 AM", "Violation Notice", "X50", "No Compliance"))
        w.writerow(_row("P2", "B-PM-2", "11/12/2026 9:00:00 AM", "Closed", "X50", ""))
        # P3: only a plumbing violation -> not a roofing lead.
        w.writerow(_row("P3", "C-PM-1", "11/1/2026 9:00:00 AM", "Violation Notice", "T30", "New Violation"))

    rows = build(load(path), {"roofing"}, datetime(2026, 11, 12))
    assert [r["parcel_id"] for r in rows] == ["P1"]
    r = rows[0]
    assert r["trades"] == "roofing"
    assert r["job_statuses"] == "X50: Citation 1"
    # 1 job (3) + cited (3) + $700 fines (2); visit 11 days before "today" (+2)
    assert r["score"] == "10"


def test_property_maintenance_bundles_minor_items_and_flags_rentals(tmp_path):
    from leads.trades import PROFILES
    assert "X50" not in PROFILES["property_maintenance"]   # roofing is excluded
    path = tmp_path / "v.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        d = "11/10/2026 9:00:00 AM"
        w.writerow(_row("P1", "A-PM-1", d, "Violation Notice", "X72", "New Violation"))
        w.writerow(_row("P1", "A-PM-1", d, "Violation Notice", "T30", "New Violation"))
        w.writerow(_row("P1", "A-PM-1", d, "Violation Notice", "R01", "No Compliance"))
        w.writerow(_row("P1", "A-PM-1", d, "Violation Notice", "X50", "New Violation"))
    rows = build(load(path), {"property_maintenance"}, datetime(2026, 11, 12))
    r = rows[0]
    assert r["job_statuses"] == "T30: New Violation; X72: New Violation"
    assert r["rental"] == "yes"
    assert r["trades"] == "plumbing, windows_doors"
    # 2 jobs (6) + fresh (2) + recent (2) + rental (3)
    assert r["score"] == "13"


def test_owner_classification_and_absentee():
    from leads.trades import is_absentee, owner_type
    from leads.violations import Property
    assert owner_type("First Dime Properties Llc") == "company/LLC"
    assert owner_type("Louisville Metro Housing Authority D") == "government"
    assert owner_type("Purvis Fannie W Heirs Or Devisees Of") == "estate/heirs"
    assert owner_type("Smith John A") == "individual"
    home = Property("P", address="1316 THORNBERRY AVE",
                    owner_address="1316 THORNBERRY AVE, LOUISVILLE, KY 40215-2246")
    away = Property("P", address="1316 THORNBERRY AVE",
                    owner_address="110 FAIRMEADE RD, LOUISVILLE, KY 40207-3905")
    unit = Property("P", address="503 BRIGHTWOOD PL A4", owner_address="503 BRIGHTWOOD PL, LOUISVILLE, KY")
    assert not is_absentee(home) and is_absentee(away) and not is_absentee(unit)


def test_landlord_rollup_groups_by_owner():
    from leads.trades import landlords
    base = {"owner_type": "company/LLC", "owner_mailing_address": "1 X", "fines_total": "0", "zip": "40210"}
    rows = [{**base, "owner": "Acme Llc", "address": "1 A ST", "score": "10", "job_statuses": "X72: Not Due; T30: Not Due"},
            {**base, "owner": "ACME LLC", "address": "2 B ST", "score": "5", "job_statuses": "X72: Not Due"},
            {**base, "owner": "Solo Llc", "address": "3 C ST", "score": "9", "job_statuses": "X72: Not Due",
             "owner_mailing_address": "9 ELSEWHERE"}]
    out = landlords(rows)
    assert len(out) == 1
    assert out[0]["owner_names"] == "Acme Llc"
    assert out[0]["properties"] == "2" and out[0]["open_job_items"] == "3" and out[0]["total_score"] == "15"


def test_landlord_rollup_merges_llcs_at_same_mailing_address():
    from leads.trades import landlords
    base = {"owner_type": "company/LLC", "fines_total": "0", "zip": "40210", "score": "5",
            "job_statuses": "X72: Not Due", "owner_mailing_address": "5720B BROWN AVE, FORT KNOX, KY 40121-2004"}
    rows = [{**base, "owner": "Red Door Legacy Llc", "address": "1 A ST"},
            {**base, "owner": "Lighthouse Estates Llc", "address": "2 B ST"}]
    out = landlords(rows)
    assert out[0]["owner_names"] == "Lighthouse Estates Llc; Red Door Legacy Llc"
    assert out[0]["properties"] == "2"
