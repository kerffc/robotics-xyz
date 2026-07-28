# Setting up "Add a company" (one-time)

This wires the paste-a-URL form on the site to a Cloudflare Worker, which
queues a GitHub Action, which researches the company with Claude and sends
you a Telegram approval card. Nothing goes live until you tap Approve.

## 1. GitHub token

1. https://github.com/settings/personal-access-tokens/new
2. Fine-grained token, repository access limited to `kerffc/robotics-xyz`.
3. Permissions: **Contents: Read and write** (that's all `repository_dispatch`
   needs).
4. Copy the token — you'll paste it into the Worker in step 2.

## 2. Deploy the Cloudflare Worker

```
cd worker
npm install -g wrangler   # if you don't have it
wrangler login
wrangler deploy
wrangler secret put GH_TOKEN     # paste the token from step 1
```

Optional but recommended — per-IP rate limiting so the public form can't be
spammed:

```
wrangler kv namespace create RATE_LIMIT_KV
# copy the id it prints into worker/wrangler.toml under [[kv_namespaces]]
wrangler deploy   # redeploy with the binding
```

`wrangler deploy` prints your Worker's URL, e.g.
`https://robotics-xyz-add-company.kerf.workers.dev`.

## 3. Point the site at the Worker

In `index.html`, find:

```js
const ADD_COMPANY_ENDPOINT = "https://robotics-xyz-add-company.YOUR-SUBDOMAIN.workers.dev";
```

Replace with the URL from step 2, then commit + push.

## Done — how it behaves

- Someone pastes a URL into the form on the site → Worker checks it looks like
  a URL, rate-limits by IP, fires a `repository_dispatch` to this repo.
- The `add-company.yml` workflow runs `scripts/add_company.py`: fetches the
  page, asks Claude to identify the company (name/category/HQ/funding/roles)
  and skip if it's a duplicate or not robotics-related, then sends **you** a
  Telegram DM with an Approve/Reject button.
- Tapping ✅ Approve runs the existing `check-approvals.yml` cron (every 10
  min), which inserts the company into `DATA`, `WEBSITES`, `CAREERS_URLS`, and
  `HQ_COORDS` in `index.html` and commits.
- Tapping ❌ Reject just discards the submission.

No new secrets needed beyond `GH_TOKEN` in the Worker — `TG_BOT_TOKEN` and
`ANTHROPIC_API_KEY` already exist as repo secrets from the news-bot workflows.

## 4. (Optional, fixes cron-throttling) Wire up the Telegram webhook

GitHub silently delays high-frequency scheduled workflows on quiet repos —
`check-approvals.yml`'s 10-min cron has been observed running 1-3 hours late,
so an Approve/Reject tap can sit unprocessed a while. The worker (already
deployed above) now also serves `/telegram-webhook`, which Telegram calls the
instant you tap a button, waking `check-approvals.yml` immediately instead of
waiting for the next cron tick. The cron stays on as a fallback (dialed back
to every 30 min).

1. Set the webhook secret in the Worker (same value as the `TG_WEBHOOK_SECRET`
   repo secret — ask whoever set that up for the value, or generate a new
   random one and update both places):
   ```
   cd worker
   wrangler secret put TG_WEBHOOK_SECRET
   wrangler deploy
   ```
2. In GitHub: Actions tab → **Set Telegram webhook** → Run workflow → paste
   your Worker's URL (e.g. `https://robotics-xyz-add-company.kerf.workers.dev`,
   no trailing slash, no `/telegram-webhook` suffix — the workflow adds that).
3. Check the run's "Verify" step output — `getWebhookInfo` should show your
   URL under `"url"` and `"last_error_message": null` (or empty).

To roll back to pure polling, call `setWebhook` with an empty `url`, or just
ignore it — `check-approvals.yml`'s cron keeps working as a fallback either way.
