#!/usr/bin/env python3
"""
Polls Telegram for Approve/Reject button taps on pending robotics-news drafts
(sent by post_robotics_news.py), and either posts the approved item to
@dailyrobotics + the site's NEWS array, or discards a rejected one.
"""
import json
import os
import time
import urllib.request

TG_TOKEN = os.environ["TG_BOT_TOKEN"]
TG_CHAT = "@dailyrobotics"

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
