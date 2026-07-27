#!/usr/bin/env python3
"""
Pulls real, live job postings from each company's ATS public API (Greenhouse,
Lever, Ashby) for companies listed in scripts/ats_config.json, and writes
normalized results to data/careers.json for the site to render.

Companies without a known ATS token are simply absent from this file — the
site falls back to the generic per-company role list in index.html's DATA
for those.

Add coverage by adding an entry to ats_config.json:
  "Company Name": { "provider": "greenhouse" | "lever" | "ashby", "token": "..." }
Find the token by viewing a company's careers page source for a
boards-api.greenhouse.io, api.lever.co, or api.ashbyhq.com URL.
"""
import json
import os
import re
import time
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(REPO_ROOT, "scripts", "ats_config.json")
OUT_PATH = os.path.join(REPO_ROOT, "data", "careers.json")

INTERN_RE = re.compile(r"\bintern\b|\binternship\b", re.IGNORECASE)


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (robotics-xyz-bot)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def normalize_employment_type(raw_type, title):
    if raw_type:
        t = raw_type.strip().lower()
        if "intern" in t:
            return "Intern"
        if "part" in t:
            return "Part-time"
        if "contract" in t or "temp" in t:
            return "Contract"
        if "full" in t:
            return "Full-time"
    # Greenhouse doesn't expose employment type on the list endpoint —
    # infer from the title, default to Full-time (the overwhelming norm).
    if INTERN_RE.search(title or ""):
        return "Intern"
    return "Full-time"


def fetch_greenhouse(token):
    data = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs")
    jobs = []
    for j in data.get("jobs", []):
        jobs.append({
            "title": j.get("title", "").strip(),
            "location": (j.get("location") or {}).get("name", "").strip() or "Unspecified",
            "employmentType": normalize_employment_type(None, j.get("title")),
            "url": j.get("absolute_url"),
        })
    return jobs


def fetch_lever(token):
    data = fetch_json(f"https://api.lever.co/v0/postings/{token}?mode=json")
    jobs = []
    for j in data:
        commitment = (j.get("categories") or {}).get("commitment", "")
        jobs.append({
            "title": j.get("text", "").strip(),
            "location": (j.get("categories") or {}).get("location", "").strip() or "Unspecified",
            "employmentType": normalize_employment_type(commitment, j.get("text")),
            "url": j.get("hostedUrl"),
        })
    return jobs


def fetch_ashby(token):
    data = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
    jobs = []
    for j in data.get("jobs", []):
        jobs.append({
            "title": j.get("title", "").strip(),
            "location": j.get("location", "").strip() or "Unspecified",
            "employmentType": normalize_employment_type(j.get("employmentType"), j.get("title")),
            "url": j.get("jobUrl") or j.get("applyUrl"),
        })
    return jobs


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby}


def main():
    with open(CONFIG_PATH) as f:
        config = json.load(f)

    result = {}
    for company, cfg in config.items():
        fetcher = FETCHERS.get(cfg["provider"])
        if not fetcher:
            print(f"unknown provider for {company}: {cfg['provider']}")
            continue
        try:
            jobs = fetcher(cfg["token"])
            result[company] = jobs
            print(f"{company}: {len(jobs)} postings")
        except Exception as e:
            print(f"failed to fetch {company} ({cfg['provider']}/{cfg['token']}): {e}")
        time.sleep(1)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump({"updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "companies": result}, f, indent=2)
    print(f"wrote {sum(len(v) for v in result.values())} postings across {len(result)} companies")


if __name__ == "__main__":
    main()
