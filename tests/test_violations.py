import csv

from leads.violations import load, to_row

HEADER = ["SERV_PROV_CODE", "B1_ALT_ID", "FullAddress", "PartialAddress", "Longitude", "Latitude",
          "PARCEL_ID", "CouncilDist", "G6A_G6_COMPL_DD", "G6A_G6_STATUS", "OccupancyStatus",
          "GUIDE_ITEM_TEXT", "VIOLATION_CODE", "GUIDE_ITEM_STATUS", "CitationAmount"]


def _row(visit, status, occ, code, item_status, amount, date="11/6/2026 4:13:00 PM"):
    return ["LJCMG", visit, "1 MAIN ST, LOUISVILLE, KY 40203-0000", "1 MAIN ST", "-85.7", "38.2",
            "P1", "6", date, status, occ, f"{code} - ROOF/GUTTERS  [156.0] text", f"{code} ",
            item_status, amount]


def test_rollup_dedupes_citation_per_visit(tmp_path):
    path = tmp_path / "v.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        # Visit 1: two violations, $600 repeated on both rows -> counts once.
        w.writerow(_row("CASE-1-PM-1", "Citation", "Vacant Structure", "X50", "No Compliance", "600"))
        w.writerow(_row("CASE-1-PM-1", "Citation", "Vacant Structure", "X19", "New Violation", "600"))
        # Later visit on a second case.
        w.writerow(_row("CASE-2-PM-1", "Order to Vacate", "Vacant Structure", "X50", "No Compliance",
                        "0", date="11/10/2026 9:00:00 AM"))

    props = load(path)
    assert list(props) == ["P1"]
    row = to_row(props["P1"])
    assert row["citation_total"] == "600"
    assert row["zip"] == "40203"
    assert row["cases"] == "CASE-1-PM; CASE-2-PM"
    assert row["latest_status"] == "Order to Vacate"
    assert row["latest_visit"] == "2026-11-10"
    assert row["violation_count"] == "2"
    assert row["unresolved_count"] == "1"
    assert "X50 ROOF/GUTTERS" in row["violations"]
    # order to vacate 6 + vacant 3 + cited 2 + $600 size 1 + 1 unresolved + extra case 2
    assert row["score"] == "15"
    assert row["addresses_on_parcel"] == "1"
