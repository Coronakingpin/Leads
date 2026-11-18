# Cold email sequence: property maintenance / make-ready

Built for Instantly or Smartlead. `{{variables}}` match the columns in
`output/email-campaign.csv`. Replace `[Your Name]`, `[Business]`, `[Phone]`.

Ground rules:
- Send from a **separate domain** (not your main one, never a personal Gmail),
  warmed up for 2-3 weeks, max ~30-50 sends per inbox per day.
- Plain text, no images, no links in email 1 (better deliverability).
- Include your physical business address and an opt-out line (CAN-SPAM).
- Never imply you're from Louisville Metro or that this is an official notice.
- Stop the sequence the moment someone replies.

---

## Email 1 (day 0)

**Subject:** {{property_address}}

Hi {{first_name|there}},

Saw Metro's inspection report on {{property_address}}. It lists {{repair_items}}.

We're a local crew that handles exactly this kind of work for landlords around
Louisville: repairs, cleanouts and make-ready turns, usually within the week, so
the items are cleared before the reinspection.

Want me to swing by and give you a price?

[Your Name]
[Business] · [Phone]
[Business street address]
Reply "no thanks" and I won't email again.

---

## Email 2 (day 3)

**Subject:** re: {{property_address}}

Hi {{first_name|there}},

Quick follow-up. Metro's deadlines on these tend to come fast, and fines stack per
visit. If it helps, I can send photos and a fixed price for the {{repair_items_short}}
before anyone has to meet us there.

[Your Name] · [Phone]

---

## Email 3 (day 7, only if other_properties > 0)

**Subject:** your other Louisville properties

Hi {{first_name|there}},

Looks like Metro has open items on {{other_properties}} of your other properties too.
A lot of owners we work with hand us the whole list and we knock it out property by
property, with photos after each one.

Worth a 10-minute call?

[Your Name] · [Phone]

---

## Email 4 (day 14, breakup)

**Subject:** closing the loop

Hi {{first_name|there}},

I'll stop here. If you ever need a make-ready turn, repairs or a cleanout
anywhere in Louisville Metro, my number is [Phone].

[Your Name]
