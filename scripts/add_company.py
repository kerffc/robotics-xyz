#!/usr/bin/env python3
"""
Takes a company URL (submitted via the site's "Add a company" form -> Cloudflare
Worker -> repository_dispatch), researches it with Claude, and sends Kerf a
Telegram approval card. Nothing is written to index.html until he taps Approve
(handled by check_approvals.py, same as the news-approval flow).
"""
import json
import os
import re
import sys
import urllib.request

TG_TOKEN = os.environ["TG_BOT_TOKEN"]
KERF_CHAT_ID = 221930844  # Kerf's Telegram user id, for approval DMs
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PENDING_LOG = os.path.join(REPO_ROOT, "scripts", "pending_companies.json")
INDEX_HTML = os.path.join(REPO_ROOT, "index.html")


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (robotics-xyz-bot)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def extract_data_array(html):
    marker = "const DATA = ["
    start = html.index(marker) + len(marker)
    end = html.index("\n  ];", start)
    return html[start:end]


def extract_cats(html):
    data_src = extract_data_array(html)
    return sorted(set(re.findall(r'cat:\s*"([^"]+)"', data_src)))


def extract_existing_names(html):
    data_src = extract_data_array(html)
    return set(re.findall(r'name:\s*"([^"]+)"', data_src))


def call_claude(url, page_text, cats, existing_names):
    cats_list = "\n".join(f"- {c}" for c in cats)
    names_list = ", ".join(sorted(existing_names))
    prompt = f"""You maintain a robotics company market-map site. Someone submitted this URL
to be added: {url}

Here is a text excerpt fetched from that URL (may be truncated/messy — it's
raw-ish HTML-to-text):
---
{page_text[:6000]}
---

Existing categories on the site (reuse one of these if it fits; only invent a
new one if truly nothing fits):
{cats_list}

Companies already on the site (do not add a duplicate of any of these):
{names_list}

Decide if this is a real robotics/robotics-adjacent company (builds robots,
robot components, or embodied-AI software) worth adding, and not already
listed. If it's a duplicate, not robotics-related, a personal blog, a news
article, or you can't identify a specific company, respond with exactly:
SKIP: <one short reason>

Otherwise respond with ONLY a JSON object (no markdown fences, no commentary),
in exactly this shape:
{{
  "name": "Company Name",
  "cat": "one of the categories above (or a new short one if none fit)",
  "hq": "City, CC",
  "lat": 37.37,
  "lng": -122.04,
  "raised": "short funding string, e.g. '~$40M Series A' or 'Public' or 'Undisclosed'",
  "investors": "comma-separated investor names, or 'Not publicly detailed'",
  "roles": ["Role One", "Role Two", "Role Three"],
  "website": "https://...",
  "careers_url": "https://... or null if none found"
}}

Use CC = 2-letter country code (US, CN, DE, JP, etc). lat/lng are the HQ city's
approximate coordinates as decimal degrees. roles should be 2-3 realistic
engineering/technical role titles this company would hire for, matching the
style of "Controls Engineer", "Manipulation Engineer", "Robot Learning Engineer".
Only state funding/investor facts you are reasonably confident about from the
page content; if unsure, use vaguer language like "Undisclosed" rather than
inventing a number."""

    body = json.dumps({
        "model": "claude-sonnet-5",
        "max_tokens": 800,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        resp = json.loads(r.read())
    text_blocks = [b["text"] for b in resp["content"] if b.get("type") == "text"]
    if not text_blocks:
        raise ValueError(f"no text block in response: {resp}")
    return text_blocks[0].strip()


def strip_html(html):
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def escape_html(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tg_call(method, payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TG_TOKEN}/{method}",
        data=body,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def load_pending():
    if os.path.exists(PENDING_LOG):
        with open(PENDING_LOG) as f:
            return json.load(f)
    return {}


def save_pending(pending):
    with open(PENDING_LOG, "w") as f:
        json.dump(pending, f, indent=2)


def send_for_approval(pending_id, company):
    roles = ", ".join(company["roles"])
    text = (
        f"<b>New company submitted</b>\n\n"
        f"<b>{escape_html(company['name'])}</b> — {escape_html(company['cat'])}\n"
        f"HQ: {escape_html(company['hq'])}\n"
        f"Raised: {escape_html(company['raised'])}\n"
        f"Investors: {escape_html(company['investors'])}\n"
        f"Roles: {escape_html(roles)}\n"
        f"Website: {escape_html(company['website'])}\n"
    )
    return tg_call("sendMessage", {
        "chat_id": KERF_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "✅ Add to site", "callback_data": f"addco:{pending_id}"},
                {"text": "❌ Reject", "callback_data": f"rejectco:{pending_id}"},
            ]]
        },
    })


def notify_skip(url, reason):
    tg_call("sendMessage", {
        "chat_id": KERF_CHAT_ID,
        "text": f"Company submission skipped for {escape_html(url)}:\n{escape_html(reason)}",
    })


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("COMPANY_URL", "")
    url = url.strip()
    if not url or not re.match(r"^https?://", url):
        print("no valid url provided")
        sys.exit(1)

    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        html = f.read()
    cats = extract_cats(html)
    existing_names = extract_existing_names(html)

    try:
        page_text = strip_html(fetch(url))
    except Exception as e:
        notify_skip(url, f"couldn't fetch the page: {e}")
        print(f"fetch failed: {e}")
        sys.exit(0)

    result = call_claude(url, page_text, cats, existing_names)

    if result.startswith("SKIP"):
        reason = result.split(":", 1)[1].strip() if ":" in result else "not a fit"
        notify_skip(url, reason)
        print(f"skipped: {reason}")
        return

    match = re.search(r"\{.*\}", result, re.S)
    if not match:
        notify_skip(url, "couldn't parse a result — try again or add manually")
        print(f"unparseable claude response: {result}")
        return

    company = json.loads(match.group(0))
    company["url"] = url

    pending = load_pending()
    pending_id = f"co{len(pending) + 1}_{re.sub(r'[^a-zA-Z0-9]', '', company['name'])[:20]}"
    pending[pending_id] = company
    save_pending(pending)

    send_for_approval(pending_id, company)
    print(f"queued for approval: {company['name']}")


if __name__ == "__main__":
    main()
