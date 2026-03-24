"""
Naukri.com scraper for Railway.
Strategy: GET the homepage first to collect session cookies,
then call the search API — cookies satisfy the WAF check.
"""
import asyncio
import json
import re
from datetime import datetime
from typing import List

import httpx
from models import JobResult

NAUKRI_HOME = "https://www.naukri.com/"
NAUKRI_API  = "https://www.naukri.com/jobapi/v3/search"

HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

HEADERS_API = {
    **HEADERS_BROWSER,
    "Accept": "application/json, text/plain, */*",
    "appid": "109",
    "systemid": "109",
    "naukri-version": "2",
    "Referer": "https://www.naukri.com/",
    "Origin": "https://www.naukri.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


async def _warm_session(client: httpx.AsyncClient):
    """Hit the Naukri homepage to collect session cookies before API calls."""
    try:
        await client.get(NAUKRI_HOME, headers=HEADERS_BROWSER, timeout=12)
    except Exception as e:
        print(f"[naukri] Session warm failed (non-fatal): {e}")


def _parse_next_data(html: str) -> list:
    """
    Fallback: extract jobs from __NEXT_DATA__ if the API is blocked.
    Naukri search pages are Next.js and embed job data in the page HTML.
    """
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
        # Navigate to job list — path varies by page version
        props = data.get("props", {}).get("pageProps", {})
        jobs_raw = (
            props.get("jobDetails") or
            props.get("jobs") or
            props.get("initialProps", {}).get("jobDetails") or
            []
        )
        return jobs_raw
    except Exception:
        return []


async def search_naukri(
    client: httpx.AsyncClient,
    query: str,
    limit: int = 20,
) -> List[JobResult]:
    jobs: List[JobResult] = []

    # ── Try JSON API first ────────────────────────────────────────────────────
    try:
        params = {
            "noOfResults": str(limit),
            "urlType":     "search_by_keyword",
            "searchType":  "adv",
            "keyword":     query,
            "location":    "india",
            "pageNo":      "1",
            "src":         "jobsearchDesk",
            "xp":          "1",
        }
        resp = await client.get(NAUKRI_API, params=params, headers=HEADERS_API, timeout=15)
        resp.raise_for_status()
        data     = resp.json()
        job_list = data.get("jobDetails", [])
        print(f"[naukri-api] '{query}' → {len(job_list)} jobs")

        for job in job_list:
            title   = (job.get("title") or "").strip()
            company = (job.get("companyName") or "").strip()
            job_url = (job.get("jdURL") or "").strip()
            job_id  = str(job.get("jobId") or "")
            if not job_url:
                job_url = f"https://www.naukri.com/job-listings-{job_id}" if job_id else ""
            if not job_url or not title:
                continue
            loc = "India"
            for ph in (job.get("placeholders") or []):
                if ph.get("type") == "location":
                    loc = (ph.get("label") or "India").strip()
                    break
            jobs.append(JobResult(
                id=f"naukri-{job_id or job_url[-12:]}",
                title=title, company=company, location=loc,
                is_remote=bool(job.get("isWorkFromHome")) or "remote" in loc.lower(),
                url=job_url, posted_at="", source="naukri",
            ))
        return jobs

    except httpx.HTTPStatusError as e:
        print(f"[naukri-api] HTTP {e.response.status_code} for '{query}' — trying HTML fallback")
    except Exception as e:
        print(f"[naukri-api] Error for '{query}': {e} — trying HTML fallback")

    # ── Fallback: scrape __NEXT_DATA__ from the search results page ───────────
    try:
        slug = query.lower().replace(" ", "-")
        url  = f"https://www.naukri.com/{slug}-jobs-in-india?k={query}&l=india"
        resp = await client.get(url, headers=HEADERS_BROWSER, timeout=15)
        resp.raise_for_status()
        job_list = _parse_next_data(resp.text)
        print(f"[naukri-html] '{query}' → {len(job_list)} jobs from __NEXT_DATA__")
        for job in job_list:
            title   = (job.get("title") or "").strip()
            company = (job.get("companyName") or "").strip()
            job_url = (job.get("jdURL") or job.get("url") or "").strip()
            if not job_url or not title:
                continue
            loc = "India"
            for ph in (job.get("placeholders") or []):
                if ph.get("type") == "location":
                    loc = (ph.get("label") or "India").strip()
                    break
            jobs.append(JobResult(
                id=f"naukri-{job.get('jobId', job_url[-12:])}",
                title=title, company=company, location=loc,
                is_remote=bool(job.get("isWorkFromHome")),
                url=job_url, posted_at="", source="naukri",
            ))
    except Exception as e:
        print(f"[naukri-html] Error for '{query}': {e}")

    return jobs


async def fetch_naukri_bulk(queries: List[str], limit_per_query: int = 20) -> List[JobResult]:
    seen_urls: set = set()
    all_jobs: List[JobResult] = []

    async with httpx.AsyncClient(
        timeout=15.0,
        follow_redirects=True,
        headers=HEADERS_BROWSER,
    ) as client:
        # Warm up session cookies once before all queries
        await _warm_session(client)

        for query in queries:
            results = await search_naukri(client, query, limit_per_query)
            for job in results:
                if job.url and job.url not in seen_urls:
                    seen_urls.add(job.url)
                    all_jobs.append(job)
            await asyncio.sleep(0.8)

    print(f"[naukri] Total unique jobs: {len(all_jobs)}")
    return all_jobs
