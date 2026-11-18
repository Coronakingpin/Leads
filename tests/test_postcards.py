from leads.postcards import back_html, build_mailings, display_name, greeting, parse_mailing_address

CFG = {"business": {"name": "Ace Repairs", "phone": "(502) 555-0100", "website": "ace.com",
                    "tagline": "x", "address_line1": "1 A St", "city": "Louisville", "state": "KY",
                    "zip": "40202"}}


def test_parse_mailing_address():
    a = parse_mailing_address("1033 DEMONBREUN ST STE 600, NASHVILLE, TN 37203-4460")
    assert a == {"address_line1": "1033 Demonbreun St", "address_line2": "STE 600",
                 "address_city": "Nashville", "address_state": "TN", "address_zip": "37203-4460"}
    assert parse_mailing_address("PO BOX 819, PROVO, UT 84603-0819")["address_line1"] == "PO Box 819"
    assert parse_mailing_address("8701 SW 6TH STREET CT, BLUE SPRINGS, MO 64064")["address_line1"] == "8701 SW 6th Street Ct"
    assert parse_mailing_address("10 RUE X, PARIS, FRANCE") is None


def test_names_and_greeting():
    assert display_name("Rb Properties Ii Llc") == "Rb Properties II LLC"
    assert greeting("Rb Properties Ii Llc") == "Hi Rb Properties II LLC,"
    assert greeting("Burnett Joseph W") == "Hello,"


def test_one_card_per_mailing_address_with_friendly_items():
    lead = {"owner": "Acme Llc", "owner_mailing_address": "1 X ST, LOUISVILLE, KY 40202",
            "job_statuses": "X72: Not Due; T30: Citation; R01: No Compliance"}
    leads = [{**lead, "address": "5 OAK ST", "score": "20"}, {**lead, "address": "9 ELM ST", "score": "5"}]
    [m] = build_mailings(leads)
    assert m["property"] == "5 Oak St" and m["other_properties"] == 1
    assert m["items"] == ["windows", "toilet"]           # R01 paperwork isn't a job
    back = back_html(CFG, m)
    assert "5 Oak St" in back and "<li>windows</li>" in back and "1 of your other Louisville property." in back
    assert "Not affiliated with Louisville Metro" in back
