# One email, all contacts (mail merge)

Merge file: `output/email-campaign.csv` (48 owners with a usable email).
Skipped: `output/email-skipped.csv` (14 inboxes that aren't the owner's: law firms, bank, school, investor relations, etc.).
Leave `{{portfolio_line}}` in; it is blank for single-property owners.

---

**Subject:** {{property_address}}

Hi {{first_name}},

Metro's inspection report for {{property_address}} lists {{repair_items}}.

We're Outta The Madness, a local Louisville crew that handles exactly this kind of work for property owners: repairs, cleanouts and make-ready turns. We usually finish within the week, so the items are cleared before reinspection. {{portfolio_line}}

Want me to come by and give you a price? Reply here or call/text (502) 808-2060.

[Your Name]
Outta The Madness LLC · outtathemadness.com
10401 Linn Station Rd, Suite 330, Louisville, KY 40223

We're a private contractor, not affiliated with Louisville Metro. Reply "no thanks" and I won't email again.
