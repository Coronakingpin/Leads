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
