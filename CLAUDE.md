# Project context (read first)

Owner: Outta The Madness LLC, property maintenance / make-ready, all of Louisville Metro.
Phone (502) 808-2060 · info@outtathemadness.com · 10401 Linn Station Rd, Suite 330, Louisville KY 40223.
User wants blunt, short answers. Keep replies brief; avoid screenshots unless needed.

## What's built (Python, `leads/`)
- `louisville.py` — pulls city violations + owner data (public ArcGIS) into `data/`.
- `trades.py` — scores properties; `--trade property_maintenance` = handyman work only
  (no roofing/HVAC/electrical panels). Adds owner, absentee/landlord flag, landlord rollup.
- `postcards.py` — Lob postcards (preview default; `--send`, `--live` + `LOB_API_KEY`). Config: `campaign.toml`.
- `outreach.py` — skip-trace upload file + merge results into cold-email CSV. Sequence: `campaign/email-sequence.md`.
- `lookup.py` — `output/email-lookup.xlsx` + `.html` (tap-to-search page) for manual email lookup.
- Tests: `pytest` (all pass).

Typical run:
```
python -m leads.trades --fetch --trade property_maintenance -o output/louisville-property-maintenance-leads.csv
python -m leads.lookup output/louisville-property-maintenance-leads.csv
python -m leads.postcards output/louisville-property-maintenance-leads.csv   # preview
```

## Website
- `site/` = landing page, deployed by Netlify (project "outtathemadness") on every push to `main`.
- Quote form = Netlify Forms (form name "quote"); verified working. Email notification to info@ should be set in Netlify Forms → Notifications.
- DNS (registered agent "Mark", Kentucky Registered Agent): www CNAME → outtathemadness.netlify.app; bare domain forwards to www.
  Never touch MX/SPF/DMARC. Bare domain A record -> 75.2.60.5 (Netlify). HTTPS live since 2026-11-19.
- Ignore the Netlify Agent's "1 open" change; don't publish Agent changes over the repo.

## Status / next steps
- [x] Site live at https://outtathemadness.com; website on postcards + email signature.
- [ ] Lob test key run, then mail top 100 postcards.
- [ ] Outreach email: buy 1-2 lookalike domains + Google Workspace inboxes, warm up 3 weeks (don't cold-email from outtathemadness.com).
- [ ] User looking up emails manually (Tier A first); merge with `python -m leads.outreach campaign`.

## Rules
- Git: work on a branch, push to `main` only when the user approves (Netlify deploys main).
- Never imply affiliation with Louisville Metro; keep "not affiliated" line on mailers/site.
- Don't put Runable/fallback.runable.site anywhere (it served someone else's site).
