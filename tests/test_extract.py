from leads.extract import extract

HTML = """
<html><head><title> Joe's Plumbing </title>
<meta name="description" content="Fast plumbing in Austin"></head>
<body>
  <a href="mailto:joe@joesplumbing.com?subject=hi">Email us</a>
  <a href="tel:+15125550147">Call</a>
  <a href="https://www.facebook.com/joesplumbing?ref=x">FB</a>
  <a href="https://instagram.com/joesplumbing">IG</a>
  <a href="/contact-us">Contact</a>
  <a href="https://other.com/contact">Partner contact</a>
  <img src="logo@2x.png">
  <p>Office: (512) 555-0199 or sales@joesplumbing.com. Order #1234567890.</p>
  <p>UK: +44 20 7946 0958. Sequence: 55 89 144 233 377. Price $1,299.00</p>
  <script>var x = "tracking@sentry.io";</script>
</body></html>
"""


def test_extract_contact_details():
    data = extract(HTML, "https://joesplumbing.com/")
    assert data.title == "Joe's Plumbing"
    assert data.description == "Fast plumbing in Austin"
    assert data.emails == {"joe@joesplumbing.com", "sales@joesplumbing.com"}
    assert "+15125550147" in data.phones
    assert "(512) 555-0199" in data.phones
    assert "+44 20 7946 0958" in data.phones
    assert len(data.phones) == 3  # no order IDs, number sequences or prices
    assert data.socials == {
        "facebook": "https://www.facebook.com/joesplumbing",
        "instagram": "https://instagram.com/joesplumbing",
    }
    assert data.contact_links == ["https://joesplumbing.com/contact-us"]
