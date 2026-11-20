# Four-minute evaluator walkthrough

Start from the README launch command. Keep the default date window of 9–15 November 2026, clear the bank and method filters and use the offline engine for a reproducible demonstration.

| Time | Action | Speaking script |
|---|---|---|
| 0:00–0:35 | Open Overview. Point to volume, rate and daily charts. | “This synthetic portfolio recorded 6,980 eligible attempts this week. A leader sees 86.59% success and wants to know what changed. The dashboard and analyst share the same cleaned data and denominator.” |
| 0:35–1:00 | Open AI analyst and run the first example. | “I’m asking why success declined last week. This demonstration uses the offline interpreter. It resolves the dates, compiles SQL and compares the week with the preceding seven days.” |
| 1:00–1:25 | Read the executive summary. Expand Query evidence. | “The portfolio went from 6,354 successes in 6,744 attempts to 6,044 in 6,980. That is a 7.63 percentage-point fall. Here are the actual query, its bound dates and the aggregate counts.” |
| 1:25–2:15 | Open the Payment method tab under What drove the change? Read the UPI shares. | “UPI rose from about 23% to 55% of volume. Keeping prior method rates fixed, shifting traffic explains about 3.23 points of the decline. The remaining 4.39 points come from changes within methods. Each method has a volume weight.” |
| 2:15–2:45 | Switch to Bank and show Northstar. | “The bank view gives another cut of the same decline. Northstar has the largest negative within-bank contribution. An outage is a possible explanation. To investigate, I would compare processor timeouts, authorization logs and payment-method mix.” |
| 2:45–3:25 | Open Data quality and display the affected IDs. | “Ingestion produced 24 extra copies. Counting those rows would inflate volume. We keep the first copy of each ID. Fifteen failed attempts lack a reason. They still count as failures, and the reason breakdown labels them Unknown.” |
| 3:25–4:00 | Return to AI analyst. Select the 30-day daily-volume example and run it. Open evidence. | “A different question changes the date range, grouping and SQL. The data here is synthetic. The investigation establishes what changed and where to look next. The optional model-assisted mode uses the same validated metric and query layer.” |

## Before recording

- Start the app locally and load Overview before sharing the screen.
- Keep the whole browser window visible and enlarge the evidence panel when reading SQL.
- Run the flagship question, inspect both attribution tabs and show the quality page live.
- Report percentage-point changes and keep the method and bank decompositions separate.
- Verify the numbers against the displayed evidence if changing filters or dates.

## Publish from the extracted folder

Install Git and GitHub CLI on the publishing computer. Run these commands from the directory containing app.py. GitHub CLI will ask you to authenticate if needed.

```bash
gh auth login
git init -b main
git add .
git status --short
git commit -m "Build PaySight enterprise payments analyst"
gh repo create paysight-ai-enterprise-analyst --public --source=. --remote=origin --push
gh repo view --json url,visibility
```

If this computer has no Git author configured, set your preferred author name and email with `git config user.name` and `git config user.email` in this repository before committing. Copy the URL printed by GitHub and open it in a signed-out window. Verify README, source files and demo guide are accessible. Submit that public URL before 22 November 2026 at 6:00 PM IST. The optional video can accompany the repository.
