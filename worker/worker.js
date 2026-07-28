/**
 * Public entry point for robotics.xyz's Cloudflare-side glue. Two routes:
 *
 *   POST /              - "Add a company" form submission. Validates the
 *                          URL, rate-limits by IP, fires a GitHub
 *                          repository_dispatch event. GitHub Actions then
 *                          does the actual research + Telegram approval step
 *                          - this worker only ever queues, never writes.
 *
 *   POST /telegram-webhook - Telegram calls this the instant Kerf taps an
 *                          Approve/Reject button, instead of check-approvals.yml
 *                          waiting for its next (GitHub-throttled) 10-min cron
 *                          tick. Validated via the X-Telegram-Bot-Api-Secret-Token
 *                          header, then just wakes check-approvals.yml via
 *                          repository_dispatch - check_approvals.py's own
 *                          getUpdates call does the actual resolving.
 *
 * Secrets/vars to set (wrangler secret put / wrangler.toml [vars]):
 *   GH_TOKEN            - fine-grained PAT, Contents: Read & Write on the repo, secret
 *   GH_REPO             - "kerffc/robotics-xyz"
 *   TG_WEBHOOK_SECRET   - random token, must match Telegram's setWebhook secret_token, secret
 */

const RATE_LIMIT_WINDOW_MS = 60 * 60 * 1000; // 1 hour
const RATE_LIMIT_MAX = 3; // submissions per IP per window

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/telegram-webhook") {
      return handleTelegramWebhook(request, env);
    }

    const cors = {
      "Access-Control-Allow-Origin": "https://kerffc.github.io",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "content-type",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: cors });
    }
    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405, headers: cors });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "Invalid JSON body" }, 400, cors);
    }

    const url = (body.url || "").trim();
    if (!/^https?:\/\/[^\s]+\.[^\s]+$/i.test(url)) {
      return json({ error: "Please submit a valid URL." }, 400, cors);
    }
    if (url.length > 500) {
      return json({ error: "URL too long." }, 400, cors);
    }

    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    const rateLimited = await isRateLimited(env, ip);
    if (rateLimited) {
      return json(
        { error: "Too many submissions from this connection. Try again later." },
        429,
        cors
      );
    }

    const ghResp = await fetch(
      `https://api.github.com/repos/${env.GH_REPO}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GH_TOKEN}`,
          Accept: "application/vnd.github+json",
          "Content-Type": "application/json",
          "User-Agent": "robotics-xyz-worker",
        },
        body: JSON.stringify({
          event_type: "add-company",
          client_payload: { url },
        }),
      }
    );

    if (!ghResp.ok) {
      const errText = await ghResp.text();
      return json(
        { error: "Failed to queue submission. Try again shortly." },
        502,
        cors
      );
    }

    return json(
      { ok: true, message: "Queued! It'll appear on the site once reviewed." },
      200,
      cors
    );
  },
};

async function handleTelegramWebhook(request, env) {
  if (request.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  const secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
  if (!env.TG_WEBHOOK_SECRET || secret !== env.TG_WEBHOOK_SECRET) {
    return new Response("Unauthorized", { status: 401 });
  }

  // Fire-and-forget wake-up: check_approvals.py's own getUpdates call does the
  // actual work of resolving whatever Telegram just sent (button tap or DM).
  // We deliberately don't parse/forward the update body - keeps this worker
  // dumb and avoids duplicating check_approvals.py's logic in two languages.
  const ghResp = await fetch(
    `https://api.github.com/repos/${env.GH_REPO}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "robotics-xyz-worker",
      },
      body: JSON.stringify({ event_type: "telegram-update" }),
    }
  );

  if (!ghResp.ok) {
    // Telegram retries webhooks that don't return 200 promptly, and the 10-min
    // cron is still running as a fallback - so a dropped dispatch here isn't fatal.
    console.log(`dispatch failed: ${ghResp.status} ${await ghResp.text()}`);
  }

  // Always 200 to Telegram regardless of the dispatch outcome - the fallback
  // cron will pick up the update on its own within 10 minutes either way.
  return new Response("ok", { status: 200 });
}

function json(obj, status, headers) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...headers, "Content-Type": "application/json" },
  });
}

async function isRateLimited(env, ip) {
  if (!env.RATE_LIMIT_KV) return false; // KV optional; skip limiting if not bound
  const key = `rl:${ip}`;
  const raw = await env.RATE_LIMIT_KV.get(key);
  const now = Date.now();
  const entries = raw ? JSON.parse(raw) : [];
  const recent = entries.filter((t) => now - t < RATE_LIMIT_WINDOW_MS);
  if (recent.length >= RATE_LIMIT_MAX) return true;
  recent.push(now);
  await env.RATE_LIMIT_KV.put(key, JSON.stringify(recent), {
    expirationTtl: RATE_LIMIT_WINDOW_MS / 1000,
  });
  return false;
}
