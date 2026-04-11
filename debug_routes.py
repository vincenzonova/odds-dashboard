"""Debug connectivity routes for Railway diagnostics."""
import socket
import time
import aiohttp
import asyncio
import subprocess
import os
import shutil
from datetime import datetime
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/debug/connectivity")
async def debug_connectivity():
    targets = {
        "bet9ja_api": "sports.bet9ja.com",
        "sportybet": "www.sportybet.com",
        "msport": "www.msport.com",
        "betgr8": "betgr8.com",
        "google": "www.google.com",
    }
    results = {}
    for name, host in targets.items():
        try:
            start = time.time()
            ip = socket.gethostbyname(host)
            dns_time = time.time() - start
            start = time.time()
            sock = socket.create_connection((ip, 443), timeout=5)
            conn_time = time.time() - start
            sock.close()
            results[name] = {
                "status": "ok",
                "ip": ip,
                "dns_ms": round(dns_time * 1000, 1),
                "connect_ms": round(conn_time * 1000, 1),
            }
        except Exception as e:
            results[name] = {"status": "error", "error": str(e)}

    async with aiohttp.ClientSession() as session:
        for name, host in targets.items():
            if results[name]["status"] == "ok":
                try:
                    start = time.time()
                    async with session.get(
                        f"https://{host}", timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        http_time = time.time() - start
                        results[name]["http_status"] = resp.status
                        results[name]["http_ms"] = round(http_time * 1000, 1)
                except Exception as e:
                    results[name]["http_error"] = str(e)

    return JSONResponse(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "results": results,
        }
    )


@router.get("/debug/chromium-check")
async def debug_chromium_check():
    """Diagnostic endpoint to check Chromium/Playwright health without running a full scrape."""
    info = {
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {},
    }

    # 1. Check if chromium binary exists
    pw_browsers = os.path.expanduser("~/.cache/ms-playwright")
    chromium_paths = []
    if os.path.isdir(pw_browsers):
        for root, dirs, files in os.walk(pw_browsers):
            for f in files:
                if f in ("chromium", "chrome", "headless_shell"):
                    chromium_paths.append(os.path.join(root, f))
    info["checks"]["browser_binaries"] = chromium_paths or "NONE FOUND"

    # 2. /dev/shm size
    try:
        shm = shutil.disk_usage("/dev/shm")
        info["checks"]["dev_shm"] = {
            "total_mb": round(shm.total / 1024 / 1024, 1),
            "used_mb": round(shm.used / 1024 / 1024, 1),
            "free_mb": round(shm.free / 1024 / 1024, 1),
        }
    except Exception as e:
        info["checks"]["dev_shm"] = {"error": str(e)}

    # 3. System memory
    try:
        with open("/proc/meminfo") as f:
            mem_lines = f.read()
        for line in mem_lines.splitlines():
            if any(k in line for k in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree")):
                parts = line.split()
                info["checks"].setdefault("memory", {})[parts[0].rstrip(":")] = parts[1] + " " + parts[2]
    except Exception as e:
        info["checks"]["memory"] = {"error": str(e)}

    # 4. Try launching Chromium via Playwright
    launch_result = {}
    try:
        from playwright.async_api import async_playwright
        pw = None
        browser = None
        try:
            pw = await async_playwright().start()
            browser = await asyncio.wait_for(
                pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
                ),
                timeout=30,
            )
            version = browser.version
            launch_result = {"status": "ok", "version": version}
            page = await browser.new_page()
            await page.goto("about:blank")
            title = await page.title()
            launch_result["page_test"] = "ok (title={})".format(title)
            await page.close()
        finally:
            if browser:
                await browser.close()
            if pw:
                await pw.stop()
    except Exception as e:
        launch_result = {"status": "FAILED", "error": str(e), "type": type(e).__name__}
    info["checks"]["chromium_launch"] = launch_result

    return JSONResponse(info)
