"""Debug connectivity routes for Railway diagnostics."""
import socket
import time
import aiohttp
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
        entry = {"host": host}
        try:
            ips = socket.getaddrinfo(host, 443, socket.AF_INET)
            entry["dns"] = [ip[4][0] for ip in ips[:3]]
        except Exception as e:
            entry["dns"] = f"FAILED: {e}"
        try:
            t0 = time.time()
            sock = socket.create_connection((host, 443), timeout=10)
            entry["tcp_ms"] = round((time.time() - t0) * 1000)
            sock.close()
        except Exception as e:
            entry["tcp_ms"] = f"FAILED: {e}"
        try:
            t0 = time.time()
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"https://{host}/", ssl=False) as resp:
                    entry["http_status"] = resp.status
                    entry["http_ms"] = round((time.time() - t0) * 1000)
        except Exception as e:
            entry["http_ms"] = f"FAILED: {e}"
        results[name] = entry
    try:
        container_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        container_ip = "unknown"
    return JSONResponse({
        "container_ip": container_ip,
        "timestamp": datetime.now().isoformat(),
        "results": results,
    })


@router.get("/debug/chromium-check")
async def chromium_check():
    """Diagnose why Chromium fails to launch: /tmp state, binary, bare launch."""
    import subprocess, traceback, shutil, os
    result = {}

    def run(cmd):
        try:
            out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            return {"stdout": out.stdout[-2000:], "stderr": out.stderr[-2000:], "code": out.returncode}
        except Exception as e:
            return {"error": repr(e)}

    result["ls_tmp"] = run("ls -la /tmp | head -80")
    result["df_tmp"] = run("df -h /tmp")
    result["which_chromium"] = run("which chromium || which chromium-browser || echo not-found")
    result["playwright_path_ms"] = run("ls -la /ms-playwright 2>&1 || true")
    result["playwright_path_home"] = run("ls -la /root/.cache/ms-playwright 2>&1 || true")
    result["chromium_version"] = run("ls /ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null | head -1 | xargs -r -I{} {} --version 2>&1 || echo not-found")
    result["tmp_writable"] = os.access("/tmp", os.W_OK)
    try:
        result["tmp_free_bytes"] = shutil.disk_usage("/tmp").free
    except Exception as e:
        result["tmp_free_bytes_error"] = repr(e)

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context()
            page = await ctx.new_page()
            await page.goto("about:blank")
            title = await page.title()
            await browser.close()
            result["bare_launch"] = {"ok": True, "title": title}
    except Exception as e:
        result["bare_launch"] = {"ok": False, "error": repr(e), "traceback": traceback.format_exc()}

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                ],
            )
            await browser.close()
            result["scraper_args_launch"] = {"ok": True}
    except Exception as e:
        result["scraper_args_launch"] = {"ok": False, "error": repr(e), "traceback": traceback.format_exc()}

    return JSONResponse(result)
"""Debug connectivity routes for Railway diagnostics."""
import socket
import time
import aiohttp
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
        entry = {"host": host}
        try:
            ips = socket.getaddrinfo(host, 443, socket.AF_INET)
            entry["dns"] = [ip[4][0] for ip in ips[:3]]
        except Exception as e:
            entry["dns"] = f"FAILED: {e}"
        try:
            t0 = time.time()
            sock = socket.create_connection((host, 443), timeout=10)
            entry["tcp_ms"] = round((time.time() - t0) * 1000)
            sock.close()
        except Exception as e:
            entry["tcp_ms"] = f"FAILED: {e}"
        try:
            t0 = time.time()
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"https://{host}/", ssl=False) as resp:
                    entry["http_status"] = resp.status
                    entry["http_ms"] = round((time.time() - t0) * 1000)
        except Exception as e:
            entry["http_ms"] = f"FAILED: {e}"
        results[name] = entry
    try:
        container_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        container_ip = "unknown"
    return JSONResponse({
        "container_ip": container_ip,
        "timestamp": datetime.now().isoformat(),
        "results": results,
    })
