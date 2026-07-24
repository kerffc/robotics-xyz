# Feature: "Drop a company link → add it to the site"

## Flow
Form on site → Cloudflare Worker (holds GH token) → GitHub `repository_dispatch`
→ Actions runs `add_company.py` → Claude researches the company → sends YOU a
Telegram approval card → you tap ✅ → `check_approvals.py` inserts into the site.

Public input never auto-publishes. You approve every add (reuses the existing
pending.json / 10-min check-approvals workflow).

## What Claude extracts from the URL
name, cat (constrained to existing CATS), hq ("City, CC"), lat/lng, raised,
investors, roles[3], website, careers_url. Returns SKIP if not a real robotics
company or a dupe of an existing DATA name.

## Build
- [ ] `scripts/add_company.py` — fetch page, call Claude (JSON out), dedupe vs DATA,
      queue to pending.json, send Telegram approval card with parsed fields.
- [ ] extend `scripts/check_approvals.py` — handle `addco:<id>` taps →
      `insert_company()` patches DATA + WEBSITES + CAREERS_URLS + HQ_COORDS.
- [ ] `.github/workflows/add-company.yml` — on `repository_dispatch: [add-company]`,
      run add_company.py with the submitted url, commit pending.json.
- [ ] `worker/worker.js` + `worker/wrangler.toml` — validate URL, light rate-limit,
      fire repository_dispatch. Holds GH_TOKEN as a secret.
- [ ] Form UI in `index.html` — paste box + "Add company" button → POST to Worker,
      show "queued for review" toast.
- [ ] `SETUP.md` — the 3 manual steps below.

## Manual setup you'll do (I can't do these for you)
1. Create a fine-grained GitHub PAT (Contents: RW on robotics-xyz) — for dispatch.
2. Deploy the Worker (`wrangler deploy`), set secret GH_TOKEN + var REPO.
3. Paste the Worker URL into the form in index.html, commit.

## Notes
- No new API keys: ANTHROPIC_API_KEY + TG_BOT_TOKEN already exist as repo secrets.
- lat/lng come from Claude (no separate geocoding dependency).
- All array edits use the existing marker-insertion style (no fragile regex).
