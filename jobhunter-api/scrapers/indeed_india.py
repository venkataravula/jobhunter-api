"""
Indeed India scraper — RSS feed, no API key needed.
Must run on Railway (not Lambda) — AWS datacenter IPs are banned by Indeed.
"""
import asyncio
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import List

import httpx
from models import JobResult

INDEED_RSS_URL = "https://in.indeed.com/rss"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
    "Referer": "https://in.indeed.com/",
}

INDIA_CITIES = {
    "india", "bangalore", "bengaluru", "mumbai", "delhi", "new delhi",
    "hyderabad", "chennai", "pune", "kolkata", "noida", "gurgaon",
    "gurugram", "ahmedabad", "jaipur", "kochi", "chandigarh", "indore",
    "nagpur", "surat", "lucknow", "bhopal", "visakhapatnam", "coimbatore",
    "remote",
}


def _is_india_location(loc: str) -> bool:
    loc_l = loc.lower()
    return any(city in loc_l for city in INDIA_CITIES)


def _parse_rss(xml_bytes: bytes, query: str) -> List[JobResult]:
    jobs = []
    try:
        root = ET.fromstring(xml_bytes)
        channel = root.find("channel")
        if channel is None:
            return jobs

        for item in channel.findall("item"):
            title   = (item.findtext("title") or "").strip()
            link    = (item.findtext("link") or "").strip()
            pub     = (item.findtext("pubDate") or "").strip()

            # Indeed puts location in a custom namespace tag when available
            loc_tag = item.find("{https://www.indeed.com/about/rss}location")
            loc = loc_tag.text.strip() if (loc_tag is not None and loc_tag.text) else "India"

            if not link:
                continue
            if not _is_india_location(loc):
                continue

            # Extract company from "Role - Company" title pattern
            company = "Unknown"
            if " - " in title:
                parts   = title.rsplit(" - ", 1)
                title   = parts[0].strip()
                company = parts[1].strip()

            posted_at = ""
            if pub:
                try:
                    posted_at = parsedate_to_datetime(pub).isoformat()
                except Exception:
                    pass

            # Stable ID from URL
            uid = hashlib.md5(link.encode()).hexdigest()[:12]

            jobs.append(JobResult(
                id=f"indeed-{uid}",
                title=title,
                company=company,
                location=loc,
                is_remote="remote" in loc.lower(),
                url=link,
                posted_at=posted_at,
                source="indeed",
            ))
    except ET.ParseError as e:
        print(f"[indeed_india] RSS parse error: {e}")
    return jobs


async def search_indeed_india(
    client: httpx.AsyncClient,
    query: str,
    limit: int = 20,
    days: int = 3,
) -> List[JobResult]:
    """Fetch India jobs from Indeed RSS for a single query term."""
    params = {
        "q":       query,
        "l":       "India",
        "sort":    "date",
        "fromage": str(days),
        "limit":   str(min(limit, 50)),
    }
    try:
        resp = await client.get(INDEED_RSS_URL, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        jobs = _parse_rss(resp.content, query)
        print(f"[indeed_india] '{query}' → {len(jobs)} India jobs")
        return jobs[:limit]
    except httpx.HTTPStatusError as e:
        print(f"[indeed_india] HTTP {e.response.status_code} for '{query}'")
        return []
    except Exception as e:
        print(f"[indeed_india] Error for '{query}': {e}")
        return []


async def fetch_indeed_india_bulk(
    queries: List[str],
    limit_per_query: int = 20,
    days: int = 3,
) -> List[JobResult]:
    """
    Fetch Indeed India jobs for multiple queries concurrently.
    Returns deduplicated list of JobResult objects.
    """
    seen_urls: set = set()
    all_jobs: List[JobResult] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Run all queries concurrently
        results = await asyncio.gather(
            *[search_indeed_india(client, q, limit_per_query, days) for q in queries],
            return_exceptions=True,
        )

    for query, result in zip(queries, results):
        if isinstance(result, Exception):
            print(f"[indeed_india] gather error for '{query}': {result}")
            continue
        for job in result:
            if job.url and job.url not in seen_urls:
                seen_urls.add(job.url)
                all_jobs.append(job)

    print(f"[indeed_india] Total unique India jobs: {len(all_jobs)}")
    return all_jobs
