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
