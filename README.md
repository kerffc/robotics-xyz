# Robotics.xyz

[![Tests](https://github.com/kerffc/robotics-xyz/actions/workflows/tests.yml/badge.svg)](https://github.com/kerffc/robotics-xyz/actions/workflows/tests.yml)

**[kerffc.github.io/robotics-xyz](https://kerffc.github.io/robotics-xyz/)**

A self-updating market map of the robotics industry — companies, funding, open
roles, a glossary, and news, all in one static page. The frontend is a single
`index.html`; everything else is a set of scheduled agents that keep its data
current without anyone editing it by hand.

## How it stays current

```
                    ┌─────────────────────────┐
  every 3h  ───────►│ post_robotics_news.py    │──► scrapes robotics press,
                    │ (post-robotics-news.yml) │    asks Claude to draft a
                    └─────────────────────────┘    summary, posts a Telegram
                                                     approval card
                    ┌─────────────────────────┐
  daily     ───────►│ sync_careers.py          │──► pulls live postings
                    │ (sync-careers.yml)        │    straight from company
                    └─────────────────────────┘    ATS APIs (Greenhouse,
                                                     Lever, etc.)

  visitor   ───────►┌─────────────────────────┐
  pastes a URL       │ Cloudflare Worker         │──► repository_dispatch
  on the site        │ (rate-limited by IP)      │    fires add-company.yml
                    └─────────────────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │ add_company.py            │──► Claude researches the
                    │ (add-company.yml)          │    company (name, category,
                    └─────────────────────────┘    HQ, funding, roles),
                                │                    skips duplicates/non-
                                ▼                    robotics sites
                    Telegram Approve/Reject card
                                │
                                ▼
                    ┌─────────────────────────┐
  every 30min  ─────►│ check_approvals.py        │──► on Approve: inserts the
  (+ instant via     │ (check-approvals.yml)     │    company into index.html
  Telegram webhook)  └─────────────────────────┘    and commits
```

Nothing goes live without a human tap. Claude proposes, a Telegram
Approve/Reject button decides, and a GitHub Action commits the result
straight to `index.html` — no build step, no database.

**Why this shape:**
- **No backend, no database.** `index.html` *is* the database — the bots
  read and rewrite it directly via `git commit`. Simple to host (GitHub
  Pages), simple to reason about, at the cost of a single large file instead
  of a proper data layer — an intentional trade-off for a project this size.
- **Approval-gated, not fully autonomous.** New company submissions are
  agent-*researched*, not agent-*published* — Claude can misidentify a
  company or approve something off-topic, so a human stays in the loop for
  anything that changes the dataset's shape. Recurring syncs (careers, news)
  are lower-risk and run unattended.
- **Telegram webhook, not just cron.** GitHub silently throttles quiet
  scheduled workflows (a 10-min cron was observed running 1-3 hours late), so
  a Cloudflare Worker also wakes `check-approvals.yml` the instant a button
  is tapped. The cron stays on as a fallback.

See [SETUP.md](SETUP.md) for the one-time setup (Worker deploy, secrets,
webhook) if you're standing this up from scratch.

## Stack

- Static frontend: single `index.html`, no build step
- Automation: GitHub Actions (Python) + Cloudflare Worker
- Data sources: company ATS APIs (careers), scraped press (news), Claude
  (company research)
- Approval channel: Telegram bot
