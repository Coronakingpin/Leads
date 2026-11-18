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
