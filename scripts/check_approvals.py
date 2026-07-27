#!/usr/bin/env python3
"""
Polls Telegram for Approve/Reject button taps on pending robotics-news drafts
(sent by post_robotics_news.py), and either posts the approved item to
@dailyrobotics + the site's NEWS array, or discards a rejected one.

Also accepts a plain URL sent by Kerf directly in chat: summarizes it via
Claude and posts it straight to the channel (manually-submitted links skip
the approval gate since Kerf already chose to post them).
"""
import json
import os
import re
import time
import urllib.request

TG_TOKEN = os.environ["TG_BOT_TOKEN"]
TG_CHAT = "@dailyrobotics"
KERF_CHAT_ID = 221930844  # Kerf's Telegram user id
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
URL_RE = re.compile(r"https?://\S+")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PENDING_LOG = os.path.join(REPO_ROOT, "scripts", "pending.json")
POSTED_LOG = os.path.join(REPO_ROOT, "scripts", "posted.json")
OFFSET_LOG = os.path.join(REPO_ROOT, "scripts", "tg_offset.json")
INDEX_HTML = os.path.join(REPO_ROOT, "index.html")
PENDING_COMPANIES_LOG = os.path.join(REPO_ROOT, "scripts", "pending_companies.json")


def tg_call(method, payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TG_TOKEN}/{method}",
        data=body,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def escape_html(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def to_html(formatted_text, link):
    lines = formatted_text.strip().split("\n", 1)
    headline = lines[0].strip()
    rest = lines[1].strip() if len(lines) > 1 else ""
    html = f"<b>{escape_html(headline)}</b>"
    if rest:
        html += f"\n\n{escape_html(rest)}"
    html += f"\n\nSource: {escape_html(link)}"
    return html


def fetch_title(link):
    req = urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0 (robotics-xyz-bot)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        html = r.read(200_000).decode("utf-8", errors="ignore")
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else link


def call_claude(title, link):
    prompt = f"""Write a SHORT Telegram post about this robotics/AI news article, in this exact format:

<Headline as a plain sentence, no markdown, under 100 characters>

• <the single most important fact/number>
• <one caveat or bit of context, only if it materially changes the read — omit this bullet entirely otherwise>

Article title: {title}
Article URL: {link}

Rules: no em dashes, no marketing language, be factual and slightly skeptical like an analyst brief. Maximum 2 bullets, prefer 1. Keep the whole thing under 400 characters total."""

    body = json.dumps({
        "model": "claude-sonnet-5",
        "max_tokens": 500,
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
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())
    text_blocks = [b["text"] for b in resp["content"] if b.get("type") == "text"]
    if not text_blocks:
        raise ValueError(f"no text block in response: {resp}")
    return text_blocks[0].strip()


def load_json(path, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def append_to_news_array(title, link, date, summary):
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        html = f.read()
    marker = "const NEWS = ["
    idx = html.index(marker) + len(marker)
    entry = (
        f'\n    {{\n'
        f'      date: "{date}",\n'
        f'      source: "auto",\n'
        f'      title: {json.dumps(title)},\n'
        f'      summary: {json.dumps(summary[:400])},\n'
        f'      url: {json.dumps(link)},\n'
        f'    }},'
    )
    html = html[:idx] + entry + html[idx:]
    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(html)


def insert_before_marker(html, marker, entry):
    idx = html.index(marker) + len(marker)
    return html[:idx] + entry + html[idx:]


def insert_company(company):
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        html = f.read()

    roles_js = ", ".join(json.dumps(r) for r in company["roles"])
    data_entry = (
        f'\n    {{ name: {json.dumps(company["name"])}, cat: {json.dumps(company["cat"])}, '
        f'hq: {json.dumps(company["hq"])}, raised: {json.dumps(company["raised"])}, '
        f'investors: {json.dumps(company["investors"])}, roles: [{roles_js}] }},'
    )
    html = insert_before_marker(html, "const DATA = [", data_entry)

    website_entry = f'\n    {json.dumps(company["name"])}: {json.dumps(company["website"])},'
    html = insert_before_marker(html, "const WEBSITES = {", website_entry)

    careers_val = json.dumps(company["careers_url"]) if company.get("careers_url") else "null"
    careers_entry = f'\n    {json.dumps(company["name"])}: {careers_val},'
    html = insert_before_marker(html, "const CAREERS_URLS = {", careers_entry)

    if company.get("hq") and f'"{company["hq"]}"' not in html.split("const HQ_COORDS = {", 1)[1].split("};", 1)[0]:
        coords_entry = f'\n    {json.dumps(company["hq"])}: [{company["lat"]}, {company["lng"]}],'
        html = insert_before_marker(html, "const HQ_COORDS = {", coords_entry)

    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(html)


def load_pending_companies():
    if os.path.exists(PENDING_COMPANIES_LOG):
        with open(PENDING_COMPANIES_LOG) as f:
            return json.load(f)
    return {}


def save_pending_companies(pending):
    with open(PENDING_COMPANIES_LOG, "w") as f:
        json.dump(pending, f, indent=2)


def main():
    offset_data = load_json(OFFSET_LOG, {"offset": 0})
    pending = load_json(PENDING_LOG, {})
    posted = set(load_json(POSTED_LOG, []))
    pending_companies = load_pending_companies()

    def checkpoint():
        save_json(OFFSET_LOG, offset_data)
        save_json(PENDING_LOG, pending)
        save_json(POSTED_LOG, sorted(posted))
        save_pending_companies(pending_companies)

    def safe_tg_call(method, payload):
        # best-effort UI feedback (ack spinner, button relabel) — must never
        # crash the run or roll back a real action that already happened
        try:
            tg_call(method, payload)
        except Exception as e:
            print(f"non-fatal: {method} failed: {e}")

    updates = tg_call("getUpdates", {"offset": offset_data["offset"], "timeout": 0})["result"]

    resolved = 0
    for u in updates:
        offset_data["offset"] = u["update_id"] + 1
        msg = u.get("message")
        if msg and msg.get("from", {}).get("id") == KERF_CHAT_ID:
            text = msg.get("text", "") or msg.get("caption", "")
            m = URL_RE.search(text) if text else None
            link = m.group(0) if m else None

            if link and link in posted:
                safe_tg_call("sendMessage", {"chat_id": KERF_CHAT_ID, "text": "Already posted, skipping."})
                checkpoint()
                continue

            try:
                if link and text.strip() == link:
                    # bare link: summarize via Claude + log to the site's NEWS array
                    title = fetch_title(link)
                    formatted = call_claude(title, link)
                    tg_call("sendMessage", {
                        "chat_id": TG_CHAT,
                        "text": to_html(formatted, link),
                        "parse_mode": "HTML",
                        "disable_web_page_preview": False,
                    })
                    append_to_news_array(title, link, time.strftime("%Y-%m-%d"), formatted)
                    posted.add(link)
                else:
                    # anything else (text with commentary, photo, video, etc.) — forward as-is
                    tg_call("copyMessage", {
                        "chat_id": TG_CHAT,
                        "from_chat_id": msg["chat"]["id"],
                        "message_id": msg["message_id"],
                    })
                    if link:
                        posted.add(link)
                checkpoint()
                safe_tg_call("sendMessage", {"chat_id": KERF_CHAT_ID, "text": "Posted to @dailyrobotics."})
                print(f"manual post from message {msg['message_id']}")
                resolved += 1
            except Exception as e:
                print(f"manual post failed for message {msg['message_id']}: {e}")
                safe_tg_call("sendMessage", {"chat_id": KERF_CHAT_ID, "text": f"Failed to post: {e}"})
            time.sleep(1)
            continue

        cq = u.get("callback_query")
        if not cq:
            checkpoint()
            continue

        data = cq.get("data", "")
        if ":" not in data:
            checkpoint()
            continue
        action, pending_id = data.split(":", 1)

        if action in ("addco", "rejectco"):
            company = pending_companies.get(pending_id)
            if not company:
                safe_tg_call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "Already handled."})
                checkpoint()
                continue
            if action == "addco":
                insert_company(company)
                del pending_companies[pending_id]
                checkpoint()  # the real action succeeded — persist before any best-effort UI calls
                safe_tg_call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "Added to site."})
                safe_tg_call("editMessageReplyMarkup", {
                    "chat_id": cq["message"]["chat"]["id"],
                    "message_id": cq["message"]["message_id"],
                    "reply_markup": {"inline_keyboard": [[{"text": "✅ Added", "callback_data": "noop"}]]},
                })
                print(f"added company: {company['name']}")
            else:
                del pending_companies[pending_id]
                checkpoint()
                safe_tg_call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "Rejected."})
                safe_tg_call("editMessageReplyMarkup", {
                    "chat_id": cq["message"]["chat"]["id"],
                    "message_id": cq["message"]["message_id"],
                    "reply_markup": {"inline_keyboard": [[{"text": "❌ Rejected", "callback_data": "noop"}]]},
                })
                print(f"rejected company: {company['name']}")
            resolved += 1
            time.sleep(1)
            continue

        item = pending.get(pending_id)
        if not item:
            # unknown/already-resolved id — just ack so the button stops spinning
            safe_tg_call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "Already handled."})
            checkpoint()
            continue

        if action == "approve":
            tg_call("sendMessage", {
                "chat_id": TG_CHAT,
                "text": to_html(item["formatted"], item["link"]),
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            })
            append_to_news_array(item["title"], item["link"], item["date"], item["summary"])
            posted.add(item["link"])
            del pending[pending_id]
            checkpoint()  # the real action succeeded — persist before any best-effort UI calls
            safe_tg_call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "Posted to @dailyrobotics."})
            safe_tg_call("editMessageReplyMarkup", {
                "chat_id": cq["message"]["chat"]["id"],
                "message_id": cq["message"]["message_id"],
                "reply_markup": {"inline_keyboard": [[{"text": "✅ Posted", "callback_data": "noop"}]]},
            })
            print(f"approved + posted: {item['title']}")
            resolved += 1
        elif action == "reject":
            posted.add(item["link"])  # don't re-draft a rejected item
            del pending[pending_id]
            checkpoint()
            safe_tg_call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "Rejected."})
            safe_tg_call("editMessageReplyMarkup", {
                "chat_id": cq["message"]["chat"]["id"],
                "message_id": cq["message"]["message_id"],
                "reply_markup": {"inline_keyboard": [[{"text": "❌ Rejected", "callback_data": "noop"}]]},
            })
            print(f"rejected: {item['title']}")
            resolved += 1
        else:
            checkpoint()
            continue

        time.sleep(1)

    checkpoint()
    print(f"done. {resolved} resolved.")


if __name__ == "__main__":
    main()
