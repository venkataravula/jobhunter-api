"""
Foundit.in (formerly Monster India) scraper for Railway.
Strategy: parse __NEXT_DATA__ embedded JSON from the Next.js search results page.
No undocumented API — reads the same data the browser renders.
"""
import asyncio
import hashlib
import json
import re
from datetime import datetime
from typing import List, Optional

import httpx
from models import JobResult

FOUNDIT_SRP = "https://www.foundit.in/srp/results"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.foundit.in/",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
}


def _extract_jobs_from_next_data(html: str) -> list:
    """
    Pull job list from __NEXT_DATA__ JSON embedded in Foundit search pages.
    Foundit is a Next.js app — all search result data lives in this tag.
    """
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.S
    )
    if not match:
        # Try alternate NEXT_DATA format
        match = re.search(r'window\.__NEXT_DATA__\s*=\s*(\{.*?\});', html, re.S)
    if not match:
        return []

    try:
        data = json.loads(match.group(1))
        props = data.get("props", {}).get("pageProps", {})

        # Foundit embeds jobs under several possible keys
        jobs = (
            props.get("jobDetails") or
            props.get("jobs") or
            props.get("data", {}).get("jobDetails") or
            props.get("searchResults", {}).get("jobs") or
            []
        )
        return jobs
    except Exception as e:
        print(f"[foundit] __NEXT_DATA__ parse error: {e}")
        return []


def _parse_job(job: dict) -> Optional[JobResult]:
    job_id  = str(job.get("jobId") or job.get("id") or "")
    title   = (job.get("title") or "").strip()
    company = (job.get("companyName") or job.get("company") or "").strip()
    if not title:
        return None

    # Location
    locs = job.get("locationDetails") or job.get("locations") or []
    if isinstance(locs, list) and locs:
        first = locs[0]
        loc = (
            first.get("city") or
            first.get("name") or
            first.get("label") or
            "India"
        )
    else:
        loc = str(locs) if locs else "India"

    # URL
    urls = job.get("urls") or {}
    job_url = (
        urls.get("jobUrl") or
        job.get("jobUrl") or
        f"https://www.foundit.in/job/{job_id}" if job_id else ""
    )
    if not job_url:
        return None

    posted_at = (job.get("createdAt") or job.get("createdDate") or "").strip()

    uid = job_id or hashlib.md5(job_url.encode()).hexdigest()[:12]

    return JobResult(
        id=f"foundit-{uid}",
        title=title,
        company=company,
        location=loc,
        is_remote="remote" in loc.lower(),
        url=job_url,
        posted_at=posted_at,
        source="foundit",
    )


async def search_foundit(
    client: httpx.AsyncClient,
    query: str,
    limit: int = 25,
) -> List[JobResult]:
    params = {
        "query":     query,
        "locations": "India",
        "sort":      "1",      # newest first
    }
    try:
        resp = await client.get(FOUNDIT_SRP, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        job_list = _extract_jobs_from_next_data(resp.text)
        print(f"[foundit] '{query}' → {len(job_list)} jobs from __NEXT_DATA__")

        jobs = []
        for raw in job_list[:limit]:
            job = _parse_job(raw)
            if job:
                jobs.append(job)
        return jobs

    except httpx.HTTPStatusError as e:
        print(f"[foundit] HTTP {e.response.status_code} for '{query}'")
        return []
    except Exception as e:
        print(f"[foundit] Error for '{query}': {e}")
        return []


async def fetch_foundit_bulk(queries: List[str], limit_per_query: int = 25) -> List[JobResult]:
    seen_urls: set = set()
    all_jobs: List[JobResult] = []

    async with httpx.AsyncClient(
        timeout=15.0,
        follow_redirects=True,
    ) as client:
        for query in queries:
            results = await search_foundit(client, query, limit_per_query)
            for job in results:
                if job.url and job.url not in seen_urls:
                    seen_urls.add(job.url)
                    all_jobs.append(job)
            await asyncio.sleep(0.6)

    print(f"[foundit] Total unique jobs: {len(all_jobs)}")
    return all_jobs
