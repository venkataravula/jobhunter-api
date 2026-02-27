"""
🚀 JobHunter API - Your Free Alternative to Paid Job APIs
Aggregates jobs from: Adzuna, Remotive, The Muse, Reed (all free)
"""

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import httpx
import asyncio
from datetime import datetime

from scrapers.adzuna import search_adzuna
from scrapers.remotive import search_remotive
from scrapers.themuse import search_themuse
from scrapers.reed import search_reed
from models import JobResult, SearchResponse

app = FastAPI(
    title="🔍 JobHunter API",
    description="""
    ## Your Free Replacement for Paid Job APIs

    Aggregates jobs from multiple FREE sources:
    - **Adzuna** – Millions of jobs (free API key required)
    - **Remotive** – Remote jobs (no key needed)
    - **The Muse** – Tech/startup jobs (no key needed)
    - **Reed** – UK jobs (free key required)

    ### How to set up free API keys:
    - Adzuna: https://developer.adzuna.com/ (free)
    - Reed: https://www.reed.co.uk/developers/jobseeker (free)
    """,
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["Info"])
async def root():
    return {
        "message": "Welcome to JobHunter API 🚀",
        "docs": "/docs",
        "endpoints": {
            "search_all": "/jobs/search",
            "remotive_only": "/jobs/remote",
            "adzuna_only": "/jobs/adzuna",
            "themuse_only": "/jobs/themuse",
        }
    }


@app.get("/jobs/search", response_model=SearchResponse, tags=["Job Search"])
async def search_all_jobs(
    query: str = Query(..., description="Job title or keywords (e.g. 'python developer')"),
    location: Optional[str] = Query(None, description="Location (e.g. 'New York', 'remote')"),
    remote_only: bool = Query(False, description="Only show remote jobs"),
    results_per_source: int = Query(10, ge=1, le=50, description="Max results per source"),
    sources: Optional[str] = Query(
        "remotive,themuse",
        description="Comma-separated sources: remotive, themuse, adzuna, reed"
    ),
    adzuna_app_id: Optional[str] = Query(None, description="Your free Adzuna App ID"),
    adzuna_app_key: Optional[str] = Query(None, description="Your free Adzuna App Key"),
    reed_api_key: Optional[str] = Query(None, description="Your free Reed API Key"),
):
    source_list = [s.strip().lower() for s in sources.split(",")]
    tasks = []
    source_names = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        if "remotive" in source_list:
            tasks.append(search_remotive(client, query, location, results_per_source))
            source_names.append("remotive")

        if "themuse" in source_list:
            tasks.append(search_themuse(client, query, location, results_per_source))
            source_names.append("themuse")

        if "adzuna" in source_list and adzuna_app_id and adzuna_app_key:
            tasks.append(search_adzuna(client, query, location, results_per_source, adzuna_app_id, adzuna_app_key))
            source_names.append("adzuna")

        if "reed" in source_list and reed_api_key:
            tasks.append(search_reed(client, query, location, results_per_source, reed_api_key))
            source_names.append("reed")

        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_jobs = []
    source_counts = {}
    errors = []

    for name, result in zip(source_names, results):
        if isinstance(result, Exception):
            errors.append(f"{name}: {str(result)}")
        else:
            if remote_only:
                result = [j for j in result if j.is_remote]
            all_jobs.extend(result)
            source_counts[name] = len(result)

    all_jobs.sort(key=lambda x: x.posted_at or "", reverse=True)

    return SearchResponse(
        query=query,
        location=location,
        total=len(all_jobs),
        sources_used=source_counts,
        errors=errors if errors else None,
        jobs=all_jobs,
        fetched_at=datetime.utcnow().isoformat()
    )


@app.get("/jobs/remote", response_model=SearchResponse, tags=["Job Search"])
async def get_remote_jobs(
    query: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    async with httpx.AsyncClient(timeout=15.0) as client:
        jobs = await search_remotive(client, query or "", None, limit)

    return SearchResponse(
        query=query or "all",
        location="remote",
        total=len(jobs),
        sources_used={"remotive": len(jobs)},
        jobs=jobs,
        fetched_at=datetime.utcnow().isoformat()
    )


@app.get("/jobs/themuse", response_model=SearchResponse, tags=["Job Search"])
async def get_themuse_jobs(
    query: str = Query(...),
    location: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=50),
):
    async with httpx.AsyncClient(timeout=15.0) as client:
        jobs = await search_themuse(client, query, location, limit)

    return SearchResponse(
        query=query,
        location=location,
        total=len(jobs),
        sources_used={"themuse": len(jobs)},
        jobs=jobs,
        fetched_at=datetime.utcnow().isoformat()
    )


@app.get("/jobs/adzuna", response_model=SearchResponse, tags=["Job Search"])
async def get_adzuna_jobs(
    query: str = Query(...),
    location: Optional[str] = Query(None),
    country: str = Query("us"),
    limit: int = Query(20, ge=1, le=50),
    app_id: str = Query(...),
    app_key: str = Query(...),
):
    async with httpx.AsyncClient(timeout=15.0) as client:
        jobs = await search_adzuna(client, query, location, limit, app_id, app_key, country)

    return SearchResponse(
        query=query,
        location=location,
        total=len(jobs),
        sources_used={"adzuna": len(jobs)},
        jobs=jobs,
        fetched_at=datetime.utcnow().isoformat()
    )


@app.get("/health", tags=["Info"])
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
