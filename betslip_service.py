"""
Betslip Service — Standalone FastAPI microservice that wraps betslip_scraper.py.

Deployed as a separate Railway service to avoid resource contention with the
main odds-dashboard app. The main app calls this service via HTTP when the
user clicks "Live Check" on the dashboard.

Run locally:  uvicorn betslip_service:app --port 8001
Railway:      Set start command to "uvicorn betslip_service:app --host 0.0.0.0 --port $PORT"
"""

import os
import logging
import asyncio
from typing import List, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from betslip_scraper import scrape_live_betslips

# ── Logging ────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App ────────────────────────────────────────────────────────────────
app = FastAPI(title="Betslip Service", version="1.0.0")

# Allow the main odds-dashboard to call us
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared secret so only the main app can call us
API_SECRET = os.getenv("BETSLIP_API_SECRET", "betslip-secret-key")


# ── Health check ───────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "betslip"}


# ── Main endpoint ──────────────────────────────────────────────────────
@app.post("/api/scrape-betslips")
async def scrape_betslips(request: Request):
    """
    Scrape live betslips for the given selections across bookmaker sites.

    Expected JSON body:
    {
        "selections": [
            {"event": "Arsenal - Everton", "home": "Arsenal", "away": "Everton",
             "sign": "1", "market": "1X2"},
            ...
        ],
        "stake": 100,
        "bookmakers": ["bet9ja", "sportybet", "msport", "betgr8"],
        "secret": "<BETSLIP_API_SECRET>"
    }

    Returns:
    {
        "results": {
            "bet9ja": {"bookmaker": "bet9ja", "status": "success", "total_odds": ..., ...},
            "sportybet": {...},
            ...
        }
    }
    """
    try:
        body = await request.json()

        # Verify shared secret
        secret = body.get("secret", "")
        if secret != API_SECRET:
            raise HTTPException(status_code=403, detail="Invalid API secret")

        selections = body.get("selections", [])
        stake = float(body.get("stake", 100.0))
        bookmakers = body.get("bookmakers", ["bet9ja", "sportybet", "msport", "betgr8"])

        if not selections:
            raise HTTPException(status_code=400, detail="No selections provided")

        logger.info(
            f"Scraping betslips: {len(selections)} selections, "
            f"stake={stake}, bookmakers={bookmakers}"
        )

        # Run the Playwright-based betslip scraper
        results = await scrape_live_betslips(
            selections=selections,
            stake=stake,
            bookmakers=bookmakers,
        )

        status_list = [f"{bm}={r.get('status')}" for bm, r in results.items()]
            logger.info(f"Scrape complete: {status_list}")

        return JSONResponse({"results": results})

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Betslip scrape failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ── Install Playwright browsers on startup ─────────────────────────────
@app.on_event("startup")
async def install_browsers():
    """Ensure Playwright Chromium is installed when the service starts."""
    logger.info("Installing Playwright browsers...")
    proc = await asyncio.create_subprocess_exec(
        "playwright", "install", "chromium",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0:
        logger.info("Playwright browsers installed successfully")
    else:
        logger.warning(f"Playwright install returned {proc.returncode}: {stderr.decode()}")
