#!/usr/bin/env python3
"""
Finds recent robotics funding/news items from RSS feeds, summarizes each into
a headline + bullet format via Claude, posts new ones to the @dailyrobotics
Telegram channel, and appends them to the NEWS array in index.html.

Dedup state lives in scripts/posted.json (committed back to the repo each run).
"""
import json
import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET

TG_TOKEN = os.environ["TG_BOT_TOKEN"]
TG_CHAT = "@dailyrobotics"
KERF_CHAT_ID = 221930844  # Kerf's Telegram user id, for approval DMs
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTED_LOG = os.path.join(REPO_ROOT, "scripts", "posted.json")
PENDING_LOG = os.path.join(REPO_ROOT, "scripts", "pending.json")
INDEX_HTML = os.path.join(REPO_ROOT, "index.html")

FEEDS = [
    "https://techcrunch.com/tag/robotics/feed/",
    "https://www.therobotreport.com/feed/",
    "https://spectrum.ieee.org/feeds/topic/robotics.rss",
]

FUNDING_KEYWORDS = re.compile(
    r"\b(raises?|raised|funding|series [a-e]\b|seed round|valuation|invest(s|ed|ment)?|million|billion)\b",
    re.IGNORECASE,
)


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (robotics-xyz-bot)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_feed(xml_bytes):
    items = []
    root = ET.fromstring(xml_bytes)
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        desc = re.sub("<[^<]+?>", "", desc)
        if title and link:
            items.append({"title": title, "link": link, "summary": desc})
    return items


def load_posted():
    if os.path.exists(POSTED_LOG):
        with open(POSTED_LOG) as f:
            return set(json.load(f))
    return set()


def save_posted(posted):
    with open(POSTED_LOG, "w") as f:
        json.dump(sorted(posted), f, indent=2)


def call_claude(title, summary, link):
    prompt = f"""Write a SHORT Telegram post about this robotics/AI funding or industry news item, in this exact format:

<Headline as a plain sentence, no markdown, under 100 characters>

• <the single most important fact/number>
• <one caveat or bit of context, only if it materially changes the read — omit this bullet entirely otherwise>

Article title: {title}
Article summary: {summary}
Article URL: {link}

Rules: no em dashes, no marketing language, be factual and slightly skeptical like an analyst brief. Maximum 2 bullets, prefer 1. Keep the whole thing under 400 characters total. If the article isn't about funding/a notable robotics development, respond with exactly SKIP."""

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


def tg_call(method, payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TG_TOKEN}/{method}",
        data=body,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def post_to_telegram(text, link):
    return tg_call("sendMessage", {
        "chat_id": TG_CHAT,
        "text": to_html(text, link),
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    })


def send_for_approval(pending_id, text, link):
    return tg_call("sendMessage", {
        "chat_id": KERF_CHAT_ID,
        "text": to_html(text, link),
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "✅ Approve", "callback_data": f"approve:{pending_id}"},
                {"text": "❌ Reject", "callback_data": f"reject:{pending_id}"},
            ]]
        },
    })


def load_pending():
    if os.path.exists(PENDING_LOG):
        with open(PENDING_LOG) as f:
            return json.load(f)
    return {}


def save_pending(pending):
    with open(PENDING_LOG, "w") as f:
        json.dump(pending, f, indent=2)


def call_claude_reads(title, summary, link):
    prompt = f"""Decide if this article belongs in a "Good reads" section of a robotics
market-map site — i.e. it's a substantive deep dive, teardown, or essay, NOT
routine funding/product news.

If it qualifies, respond with exactly two lines:
<one-line summary, no markdown, factual tone, under 160 characters>
<source name, e.g. "IEEE Spectrum">

If it's routine news (funding round, product launch blurb, earnings), respond with exactly SKIP.

Article title: {title}
Article summary: {summary}
Article URL: {link}"""

    body = json.dumps({
        "model": "claude-sonnet-5",
        "max_tokens": 200,
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


def append_to_reads_array(source, title, link, summary):
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        html = f.read()

    marker = "const READS = ["
    idx = html.index(marker) + len(marker)
    entry = (
        f'\n    {{ source: {json.dumps(source)}, title: {json.dumps(title)}, '
        f'url: {json.dumps(link)}, summary: {json.dumps(summary[:200])} }},'
    )
    html = html[:idx] + entry + html[idx:]

    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(html)


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


def main():
    posted = load_posted()
    pending = load_pending()
    pending_links = {p["link"] for p in pending.values()}
    new_posts = 0

    for feed_url in FEEDS:
        try:
            items = parse_feed(fetch(feed_url))
        except Exception as e:
            print(f"feed failed: {feed_url}: {e}")
            continue

        for item in items:
            if item["link"] in posted or item["link"] in pending_links:
                continue

            if not FUNDING_KEYWORDS.search(item["title"] + " " + item["summary"]):
                # not funding/routine news — consider it for the Good Reads section instead
                try:
                    verdict = call_claude_reads(item["title"], item["summary"], item["link"])
                except Exception as e:
                    print(f"claude reads call failed for {item['link']}: {e}")
                    continue  # transient failure, retry next run — do not mark seen
                if verdict.strip() == "SKIP" or "\n" not in verdict:
                    posted.add(item["link"])  # not a good read either, don't reconsider it
                    continue
                summary_line, source_line = verdict.strip().split("\n", 1)
                append_to_reads_array(source_line.strip(), item["title"], item["link"], summary_line.strip())
                posted.add(item["link"])  # only mark seen once actually added
                print(f"added to reads: {item['title']}")
                time.sleep(2)
                continue

            try:
                formatted = call_claude(item["title"], item["summary"], item["link"])
            except Exception as e:
                print(f"claude call failed for {item['link']}: {e}")
                continue  # transient failure, retry next run — do not mark seen

            if formatted.strip() == "SKIP":
                posted.add(item["link"])  # not news we want, don't reconsider it
                continue

            pending_id = str(abs(hash(item["link"])) % 10**8)
            try:
                send_for_approval(pending_id, formatted, item["link"])
                print(f"sent for approval: {item['title']}")
                new_posts += 1
            except Exception as e:
                print(f"approval DM failed for {item['link']}: {e}")
                continue  # transient failure, retry next run — do not mark seen

            pending[pending_id] = {
                "link": item["link"],
                "title": item["title"],
                "formatted": formatted,
                "summary": item["summary"],
                "date": time.strftime("%Y-%m-%d"),
            }
            pending_links.add(item["link"])

            time.sleep(2)  # avoid hammering telegram / claude

    save_posted(posted)
    save_pending(pending)
    print(f"done. {new_posts} sent for approval.")


if __name__ == "__main__":
    main()
