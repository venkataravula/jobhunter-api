"""
🚀 JobHunter API — India focus
"""
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List
import httpx
import asyncio
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

ADZUNA_APP_ID  = os.getenv("ADZUNA_APP_ID")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY")
REED_API_KEY   = os.getenv("REED_API_KEY")
SUPABASE_URL   = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY   = os.getenv("SUPABASE_KEY", "")
CRON_SECRET    = os.getenv("CRON_SECRET", "")  # same secret as Lambda

from scrapers.indeed_india import fetch_indeed_india_bulk, search_indeed_india
from scrapers.naukri import fetch_naukri_bulk
from scrapers.foundit import fetch_foundit_bulk
from scrapers.adzuna import search_adzuna
from scrapers.remotive import search_remotive
from scrapers.themuse import search_themuse
from scrapers.reed import search_reed
from models import JobResult, SearchResponse

app = FastAPI(
    title="🔍 JobHunter API — India",
    description="India-focused job search. Indeed runs here (Railway) to bypass AWS IP ban.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


# ─── Supabase helpers ─────────────────────────────────────────────────────────

async def _sb_get(client: httpx.AsyncClient, path: str) -> list:
    resp = await client.get(
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def _sb_post(client: httpx.AsyncClient, path: str, payload, prefer: str = "resolution=ignore-duplicates"):
    resp = await client.post(
        f"{SUPABASE_URL}/rest/v1/{path}",
        json=payload,
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": prefer,
        },
        timeout=15,
    )
    resp.raise_for_status()


async def _sb_patch(client: httpx.AsyncClient, path: str, payload: dict):
    resp = await client.patch(
        f"{SUPABASE_URL}/rest/v1/{path}",
        json=payload,
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
        },
        timeout=10,
    )
    resp.raise_for_status()


async def _get_or_create_batch(client: httpx.AsyncClient, date_iso: str) -> Optional[str]:
    rows = await _sb_get(client, f"job_batches?date=eq.{date_iso}&select=id,status")
    if rows:
        return rows[0]["id"]
    await _sb_post(
        client, "job_batches",
        {"date": date_iso, "status": "draft", "source": "railway-indeed"},
        prefer="return=representation",
    )
    rows = await _sb_get(client, f"job_batches?date=eq.{date_iso}&select=id,status")
    return rows[0]["id"] if rows else None


async def _save_jobs(client: httpx.AsyncClient, jobs: List[JobResult], batch_id: str) -> int:
    """Write jobs to job_cache + job_postings. Returns count of new postings saved."""
    if not jobs or not batch_id:
        return 0

    existing = await _sb_get(client, f"job_postings?batch_id=eq.{batch_id}&select=url&limit=2000")
    existing_urls = {r["url"] for r in existing if r.get("url")}

    new_postings = []
    cache_rows = []
    for job in jobs:
        if not job.url or not job.title:
            continue
        cache_rows.append({
            "title": job.title, "company": job.company,
            "location": job.location, "url": job.url,
            "is_remote": job.is_remote, "source": job.source,
            "posted_at": job.posted_at or None,
            "fetched_at": datetime.utcnow().isoformat(),
        })
        if job.url not in existing_urls:
            existing_urls.add(job.url)
            new_postings.append({
                "batch_id": batch_id,
                "title": job.title, "company": job.company,
                "location": job.location, "url": job.url,
                "tags": [job.source],
                "posted_at": job.posted_at or None,
            })

    # job_cache — ignore duplicates
    for i in range(0, len(cache_rows), 20):
        try:
            await _sb_post(client, "job_cache", cache_rows[i:i+20])
        except Exception:
            pass

    # job_postings — chunks of 20
    saved = 0
    for i in range(0, len(new_postings), 20):
        chunk = new_postings[i:i+20]
        try:
            await _sb_post(client, "job_postings", chunk, prefer="return=minimal")
            saved += len(chunk)
        except Exception:
            for row in chunk:
                try:
                    await _sb_post(client, "job_postings", row, prefer="return=minimal")
                    saved += 1
                except Exception:
                    pass

    return saved


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", tags=["Info"])
async def root():
    return {
        "message": "JobHunter API 🇮🇳",
        "docs": "/docs",
        "sources": {
            "indeed_india": "✅ active (Railway — bypasses AWS IP ban)",
            "adzuna":       "✅" if (ADZUNA_APP_ID and ADZUNA_APP_KEY) else "❌ keys not set",
            "reed":         "✅" if REED_API_KEY else "❌ key not set",
            "remotive":     "✅",
            "themuse":      "✅",
        },
        "supabase": "✅ connected" if SUPABASE_URL else "❌ not configured",
    }

"""
Temporary debug routes — add these to main.py to diagnose
why Naukri and Foundit return 0 jobs.

Paste these two routes into main.py just before the @app.get("/health") line,
redeploy, then hit the debug URLs to see what's actually coming back.
"""

# ─── DEBUG routes (remove after diagnosis) ───────────────────────────────────

@app.get("/debug/naukri-raw", tags=["Debug"])
async def debug_naukri_raw(query: str = Query(default="Java Developer")):
    """Returns raw Naukri API response so we can see what the server actually sends back."""
    import urllib.parse
    params = urllib.parse.urlencode({
        "noOfResults": "5",
        "urlType": "search_by_keyword",
        "searchType": "adv",
        "keyword": query,
        "location": "india",
        "pageNo": "1",
        "src": "jobsearchDesk",
        "xp": "1",
    })
    url = f"https://www.naukri.com/jobapi/v3/search?{params}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-IN,en;q=0.9",
        "appid": "109",
        "systemid": "109",
        "Referer": "https://www.naukri.com/",
        "Origin": "https://www.naukri.com",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        # Warm session
        try:
            await client.get("https://www.naukri.com/", headers=headers, timeout=10)
        except Exception:
            pass
        try:
            resp = await client.get(url, headers=headers, timeout=15)
            return {
                "status_code": resp.status_code,
                "headers": dict(resp.headers),
                "body_preview": resp.text[:3000],
            }
        except Exception as e:
            return {"error": str(e)}


@app.get("/debug/foundit-raw", tags=["Debug"])
async def debug_foundit_raw(query: str = Query(default="Java Developer")):
    """Returns raw Foundit HTML snippet so we can see if __NEXT_DATA__ is present."""
    import re
    params = {"query": query, "locations": "India", "sort": "1"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Referer": "https://www.foundit.in/",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        try:
            resp = await client.get("https://www.foundit.in/srp/results", params=params, headers=headers, timeout=15)
            html = resp.text
            has_next_data = "__NEXT_DATA__" in html
            # Extract just the __NEXT_DATA__ block if present
            match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
            next_data_preview = match.group(1)[:3000] if match else "NOT FOUND"
            return {
                "status_code": resp.status_code,
                "url": str(resp.url),
                "has_next_data": has_next_data,
                "html_length": len(html),
                "next_data_preview": next_data_preview,
            }
        except Exception as e:
            return {"error": str(e)}
@app.get("/health", tags=["Info"])
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# ─── Indeed India ─────────────────────────────────────────────────────────────

@app.post("/jobs/indeed-india/fetch", tags=["India Jobs"])
async def fetch_and_save_indeed_india(
    queries: List[str] = Query(..., description="Job title keywords"),
    secret: str = Query(..., description="Cron secret"),
    days: int = Query(3, description="Jobs posted within N days"),
    limit_per_query: int = Query(20, ge=1, le=50),
):
    """
    🇮🇳 Scrape Indeed India and save to Supabase.
    Called by Lambda at the end of each run — not browser-facing.

    Example (from Lambda):
      POST /jobs/indeed-india/fetch
           ?queries=Data+Analyst&queries=Java+Developer
           &secret=cron_9f8a7d6c5b4a3e2f1
    """
    if not CRON_SECRET or secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid secret")
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=500, detail="Supabase not configured on Railway")

    date_iso = datetime.utcnow().strftime("%Y-%m-%d")
    jobs = await fetch_indeed_india_bulk(queries, limit_per_query=limit_per_query, days=days)

    async with httpx.AsyncClient() as client:
        batch_id = await _get_or_create_batch(client, date_iso)
        if not batch_id:
            raise HTTPException(status_code=500, detail="Could not get/create today's batch")
        saved = await _save_jobs(client, jobs, batch_id)
        if saved > 0:
            await _sb_patch(client, f"job_batches?id=eq.{batch_id}", {"status": "published"})

    return {
        "date": date_iso,
        "batch_id": batch_id,
        "queries_run": len(queries),
        "indeed_jobs_found": len(jobs),
        "saved_to_supabase": saved,
        "batch_status": "published" if saved > 0 else "draft (no new jobs)",
    }


@app.get("/jobs/indeed-india", tags=["India Jobs"])
async def preview_indeed_india(
    query: str = Query(...),
    limit: int = Query(20, ge=1, le=50),
    days: int = Query(3),
):
    """🔍 Preview Indeed India results without writing to Supabase."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        jobs = await search_indeed_india(client, query, limit, days)
    return {
        "query": query, "location": "India",
        "total": len(jobs), "source": "indeed",
        "jobs": [j.dict() for j in jobs],
        "fetched_at": datetime.utcnow().isoformat(),
    }



# ─── India Portals (Naukri + Foundit) ────────────────────────────────────────

@app.post("/jobs/india-portals/fetch", tags=["India Jobs"])
async def fetch_and_save_india_portals(
    queries: List[str] = Query(..., description="Job title keywords"),
    secret: str = Query(..., description="Cron secret"),
    limit_per_query: int = Query(20, ge=1, le=50),
):
    """
    🇮🇳 Scrape Naukri + Foundit and save to Supabase.
    Called by Lambda at end of each run — not browser-facing.

    Example (from Lambda):
      POST /jobs/india-portals/fetch
           ?queries=Data+Analyst&queries=Java+Developer
           &secret=cron_9f8a7d6c5b4a3e2f1
    """
    if not CRON_SECRET or secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid secret")
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=500, detail="Supabase not configured")

    date_iso = datetime.utcnow().strftime("%Y-%m-%d")

    # Run Naukri and Foundit concurrently
    naukri_jobs, foundit_jobs = await asyncio.gather(
        fetch_naukri_bulk(queries, limit_per_query),
        fetch_foundit_bulk(queries, limit_per_query),
        return_exceptions=True,
    )

    if isinstance(naukri_jobs, Exception):
        print(f"[india-portals] Naukri error: {naukri_jobs}")
        naukri_jobs = []
    if isinstance(foundit_jobs, Exception):
        print(f"[india-portals] Foundit error: {foundit_jobs}")
        foundit_jobs = []

    all_jobs = list(naukri_jobs) + list(foundit_jobs)

    # Deduplicate by URL
    seen: set = set()
    deduped = []
    for job in all_jobs:
        if job.url and job.url not in seen:
            seen.add(job.url)
            deduped.append(job)

    async with httpx.AsyncClient() as client:
        batch_id = await _get_or_create_batch(client, date_iso)
        if not batch_id:
            raise HTTPException(status_code=500, detail="Could not get/create today's batch")
        saved = await _save_jobs(client, deduped, batch_id)
        if saved > 0:
            await _sb_patch(client, f"job_batches?id=eq.{batch_id}", {"status": "published"})

    return {
        "date": date_iso,
        "batch_id": batch_id,
        "queries_run": len(queries),
        "naukri_found": len(naukri_jobs),
        "foundit_found": len(foundit_jobs),
        "total_found": len(deduped),
        "saved_to_supabase": saved,
        "batch_status": "published" if saved > 0 else "draft (no new jobs)",
    }


@app.get("/jobs/india-portals/preview", tags=["India Jobs"])
async def preview_india_portals(
    query: str = Query(...),
    source: str = Query("naukri", description="naukri or foundit"),
    limit: int = Query(10, ge=1, le=25),
):
    """🔍 Preview Naukri/Foundit results without writing to Supabase."""
    if source == "foundit":
        from scrapers.foundit import search_foundit
        async with httpx.AsyncClient(follow_redirects=True) as client:
            jobs = await search_foundit(client, query, limit)
    else:
        from scrapers.naukri import search_naukri, _warm_session
        async with httpx.AsyncClient(follow_redirects=True) as client:
            await _warm_session(client)
            jobs = await search_naukri(client, query, limit)
    return {
        "query": query, "source": source, "location": "India",
        "total": len(jobs),
        "jobs": [j.dict() for j in jobs],
        "fetched_at": datetime.utcnow().isoformat(),
    }

# ─── Existing endpoints (India defaults) ─────────────────────────────────────

@app.get("/jobs/search", response_model=SearchResponse, tags=["Job Search"])
async def search_all_jobs(
    query: str = Query(...),
    location: Optional[str] = Query("India"),       # ← was None
    remote_only: bool = Query(False),
    results_per_source: int = Query(10, ge=1, le=50),
    sources: Optional[str] = Query("remotive,themuse,adzuna,reed"),
):
    """🔍 Search all sources. Defaults to India."""
    source_list = [s.strip().lower() for s in sources.split(",")]
    tasks, names = [], []

    async with httpx.AsyncClient(timeout=15.0) as client:
        if "remotive" in source_list:
            tasks.append(search_remotive(client, query, location, results_per_source))
            names.append("remotive")
        if "themuse" in source_list:
            tasks.append(search_themuse(client, query, location, results_per_source))
            names.append("themuse")
        if "adzuna" in source_list and ADZUNA_APP_ID and ADZUNA_APP_KEY:
            tasks.append(search_adzuna(client, query, location, results_per_source,
                                       ADZUNA_APP_ID, ADZUNA_APP_KEY, country="in"))  # ← country=in
            names.append("adzuna")
        if "reed" in source_list and REED_API_KEY:
            tasks.append(search_reed(client, query, location, results_per_source, REED_API_KEY))
            names.append("reed")
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_jobs, counts, errors = [], {}, []
    for name, result in zip(names, results):
        if isinstance(result, Exception):
            errors.append(f"{name}: {result}")
        else:
            if remote_only:
                result = [j for j in result if j.is_remote]
            all_jobs.extend(result)
            counts[name] = len(result)

    all_jobs.sort(key=lambda x: x.posted_at or "", reverse=True)
    return SearchResponse(query=query, location=location, total=len(all_jobs),
        sources_used=counts, errors=errors or None,
        jobs=all_jobs, fetched_at=datetime.utcnow().isoformat())


@app.get("/jobs/remote", response_model=SearchResponse, tags=["Job Search"])
async def get_remote_jobs(query: Optional[str] = Query(None), limit: int = Query(20, ge=1, le=100)):
    async with httpx.AsyncClient(timeout=15.0) as client:
        jobs = await search_remotive(client, query or "", None, limit)
    return SearchResponse(query=query or "all", location="remote", total=len(jobs),
        sources_used={"remotive": len(jobs)}, jobs=jobs, fetched_at=datetime.utcnow().isoformat())


@app.get("/jobs/adzuna", response_model=SearchResponse, tags=["Job Search"])
async def get_adzuna_jobs(
    query: str = Query(...),
    location: Optional[str] = Query("India"),       # ← was None
    country: str = Query("in"),                      # ← was "us"
    limit: int = Query(20, ge=1, le=50),
):
    """📋 Adzuna jobs — defaults to India."""
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return SearchResponse(query=query, total=0, sources_used={},
            errors=["Adzuna keys not set"], jobs=[], fetched_at=datetime.utcnow().isoformat())
    async with httpx.AsyncClient(timeout=15.0) as client:
        jobs = await search_adzuna(client, query, location, limit, ADZUNA_APP_ID, ADZUNA_APP_KEY, country)
    return SearchResponse(query=query, location=location, total=len(jobs),
        sources_used={"adzuna": len(jobs)}, jobs=jobs, fetched_at=datetime.utcnow().isoformat())


@app.get("/jobs/reed", response_model=SearchResponse, tags=["Job Search"])
async def get_reed_jobs(
    query: str = Query(...),
    location: Optional[str] = Query("India"),       # ← was None
    limit: int = Query(20, ge=1, le=50),
):
    """🇬🇧 Reed jobs."""
    if not REED_API_KEY:
        return SearchResponse(query=query, total=0, sources_used={},
            errors=["Reed key not set"], jobs=[], fetched_at=datetime.utcnow().isoformat())
    async with httpx.AsyncClient(timeout=15.0) as client:
        jobs = await search_reed(client, query, location, limit, REED_API_KEY)
    return SearchResponse(query=query, location=location, total=len(jobs),
        sources_used={"reed": len(jobs)}, jobs=jobs, fetched_at=datetime.utcnow().isoformat())
