# Leads

Scrape contact info from a list of websites you choose and save it to a CSV.

For each URL it collects:
- page title and meta description
- email addresses (from `mailto:` links and page text)
- phone numbers (from `tel:` links and page text)
- Facebook, Instagram, LinkedIn, Twitter/X, TikTok and YouTube links

It also follows up to 3 contact/about pages on the same site, because that is
usually where the email and phone are.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

1. Put your links in `urls.txt`, one per line (`#` lines are ignored):

   ```
   https://somebusiness.com
   https://anotherbusiness.com/locations/austin
   ```

2. Run:

   ```bash
   python -m leads
   ```

   Results land in `output/leads-<timestamp>.csv`, one row per URL.

### Options

| Flag | Default | What it does |
| --- | --- | --- |
| `input` | `urls.txt` | File with the URLs |
| `-o, --output` | `output/leads-<timestamp>.csv` | Where to save the CSV |
| `--follow N` | `3` | Contact/about pages to follow per site (`0` = only the given page) |
| `--delay S` | `1.0` | Seconds between requests |
| `--timeout S` | `15` | Request timeout |
| `-v` | off | Verbose logging |

Example: `python -m leads my_list.txt -o output/austin.csv --follow 5`

## Limits

- Pages that build their content with JavaScript (some Wix/Squarespace/React
  sites) may come back empty, since this reads the raw HTML.
- Sites behind Cloudflare or login walls will show up in the `error` column.
- Respect each site's terms of service and robots.txt, and anti-spam laws
  (CAN-SPAM, GDPR) when you contact the leads.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Louisville code-violation leads

`leads.violations` turns a Louisville Metro property-maintenance export
(`PM_SiteVisit_Violations_*.csv` from the city's ArcGIS open data) into one row
per property, scored by how distressed it looks: condemned, order to vacate,
vacant/abandoned, emergency or citation referrals, fines, unresolved
violations and repeat cases. Highest score first.

```bash
python -m leads.violations PM_SiteVisit_Violations.csv                  # everything still open
python -m leads.violations export.csv --vacant-only --single-address    # vacant houses, no apartment complexes
python -m leads.violations export.csv --zip 40211 --zip 40212 --min-score 10
```

| Flag | What it does |
| --- | --- |
| `--vacant-only` | Only vacant, abandoned or condemned properties |
| `--single-address` | Skip parcels with several unit addresses (apartment complexes) |
| `--include-closed` | Keep properties whose latest visit was Closed (dropped by default) |
| `--zip Z` | Limit to a ZIP code (repeatable) |
| `--min-score N` | Drop properties below this score |

Score weights are in `SCORE` at the top of `leads/violations.py`; tweak them to
fit what you're looking for. The export has **no owner names or contact
info**: only address, parcel ID, district and coordinates. Owner lookup is a
separate step (parcel ID → Jefferson County PVA records).

## Contractor leads by trade

`leads.trades` finds properties where the city has ordered repairs in a trade
and the work is still open, ranked by how pressured the owner is (citations,
court, fines, fresh deadlines) and how recently the inspector was out.
Properties whose latest case status is Closed are dropped, and each violation
uses its status from the most recent visit, so items already fixed don't show up.

```bash
python -m leads.trades export.csv                         # one CSV per trade in output/trades/
python -m leads.trades export.csv --trade roofing         # just roofing
python -m leads.trades export.csv --trade roofing --trade exterior_siding_paint --zip 40210 -o output/my-leads.csv
python -m leads.trades --list-trades                      # trades and the violation codes in each
```

Trades: roofing, exterior_siding_paint, windows_doors, carpentry_porch_stairs,
interior_drywall_flooring, electrical, plumbing, hvac, cleanup_junk_lawn, tree,
concrete_paving, drainage, pest_control, demolition, appliances. The code →
trade mapping is `TRADES` in `leads/trades.py`.

## Property maintenance / make-ready leads with owners (recommended)

Pulls live data from the city's public ArcGIS services (violations + the
property-maintenance occupancy layer, which carries the PVA owner name and
mailing address), so there's no export link to expire:

```bash
python -m leads.trades --fetch --trade property_maintenance -o output/pm-leads.csv
```

That writes two files:

- `pm-leads.csv`: one row per property with open handyman/make-ready items
  (cleanup, exterior surfaces, paint, windows, doors, porches, steps, fences,
  drywall, floors, cabinets, fixture-level plumbing, smoke detectors,
  appliances), plus **owner, owner type, owner mailing address** and whether
  the owner is absentee (mails somewhere else = landlord/investor).
- `pm-leads-landlords.csv`: owners with 2+ such properties, grouped by mailing
  address so one operator's multiple LLCs show up as one pitch.

Government-owned properties (Metro, Housing Authority, Landbank) are dropped
unless you pass `--include-government`; they hire through bids, not cold outreach.

Run `python -m leads.louisville fetch` alone to just refresh `data/`. Owner
names are the last PVA owner the city has on file and can lag recent sales.

## Outreach: postcards + email

### Postcards (Lob)

```bash
cp campaign.example.toml campaign.toml      # fill in business name, phone, return address
python -m leads.postcards output/pm-leads.csv                       # preview only, sends nothing
LOB_API_KEY=test_... python -m leads.postcards output/pm-leads.csv --send          # free test
LOB_API_KEY=live_... python -m leads.postcards output/pm-leads.csv --send --live   # real mail
```

One card per owner mailing address, naming their property and the cited items
in plain English. `max_per_run` caps spend; `output/postcards-sent.csv` logs
every live send and the same address isn't re-mailed within `skip_days`.
Preview writes `output/postcards-preview.csv` and `output/postcard-proof.html`.

### Email (skip trace -> Instantly/Smartlead)

The city data has no emails, so:

```bash
python -m leads.outreach skiptrace output/pm-leads.csv              # -> output/skiptrace-upload.csv
# upload that to BatchSkipTracing / REISkip / etc., download their results CSV
python -m leads.outreach campaign output/pm-leads.csv results.csv   # -> output/email-campaign.csv
```

Import `email-campaign.csv` into a cold-email tool and use the sequence in
`campaign/email-sequence.md`. For LLC owners, find the real person on the
Kentucky Secretary of State business search first; known contacts for the
biggest operators are in `campaign/landlord-contacts.csv`.
