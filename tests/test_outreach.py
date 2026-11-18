import csv

from leads.outreach import campaign, skiptrace, split_person

LEADS = [
    {"owner": "Burnett Joseph W Sr", "owner_type": "individual", "score": "20",
     "owner_mailing_address": "PO BOX 126, FISHERVILLE, KY 40023-0126", "address": "5 OAK ST",
     "full_address": "5 OAK ST, LOUISVILLE, KY 40211-0000", "zip": "40211",
     "job_statuses": "X72: Not Due; T30: Citation"},
    {"owner": "Burnett Joseph W Sr", "owner_type": "individual", "score": "5",
     "owner_mailing_address": "PO BOX 126, FISHERVILLE, KY 40023-0126", "address": "9 ELM ST",
     "full_address": "9 ELM ST, LOUISVILLE, KY 40211-0000", "zip": "40211", "job_statuses": "02A: Not Due"},
    {"owner": "Acme Rentals Llc", "owner_type": "company/LLC", "score": "9",
     "owner_mailing_address": "1 X ST, LOUISVILLE, KY 40202", "address": "3 PINE ST",
     "full_address": "3 PINE ST, LOUISVILLE, KY 40212-0000", "zip": "40212", "job_statuses": "X07: Not Due"},
]


def test_split_person():
    assert split_person("Burnett Joseph W Sr") == ("Joseph", "Burnett")
    assert split_person("Madonna") == ("", "Madonna")


def test_skiptrace_then_campaign_roundtrip(tmp_path):
    up = tmp_path / "up.csv"
    assert skiptrace(LEADS, up) == 2
    rows = list(csv.DictReader(up.open()))
    joe = next(r for r in rows if r["Last Name"] == "Burnett")
    assert joe["First Name"] == "Joseph" and joe["Mailing Address"] == "PO Box 126"
    assert joe["Property Address"] == "5 Oak St"
    acme = next(r for r in rows if r["Company"])
    assert acme["Company"] == "Acme Rentals LLC" and acme["First Name"] == ""

    # Simulated skip-trace results: service echoes our columns and adds email/phone columns.
    res = tmp_path / "res.csv"
    with res.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) + ["Email 1", "Email 2", "Phone 1"])
        w.writeheader()
        w.writerow({**joe, "Email 1": "JOE@example.org", "Email 2": "bad-email", "Phone 1": "5025550101"})
        w.writerow({**acme, "Email 1": "", "Phone 1": ""})
    out = tmp_path / "camp.csv"
    matched, emails = campaign(LEADS, res, out)
    assert (matched, emails) == (2, 1)
    [row] = list(csv.DictReader(out.open()))
    assert row["email"] == "joe@example.org" and row["first_name"] == "Joseph"
    assert row["property_address"] == "5 Oak St"
    assert row["repair_items"] == "windows, toilet" and row["other_properties"] == "1"
    assert row["phone"] == "5025550101"
