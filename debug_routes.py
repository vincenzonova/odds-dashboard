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
