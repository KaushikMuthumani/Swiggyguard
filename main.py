"""
SwiggyGuard — Main entry point
FastAPI server + APScheduler agent loop
"""

import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
import httpx

load_dotenv()

from db import init_db, get_dashboard_stats, get_recent_events, get_pending_events, update_event
from agents.detector import run_detection_cycle
from agents.scorer import score_churn_risk
from agents.recovery import execute_recovery
from agents.followup import check_for_next_orders

scheduler = AsyncIOScheduler()

# Demo customer IDs — replace with real IDs from Swiggy MCP
DEMO_CUSTOMER_IDS = ["cust_001", "cust_002", "cust_003"]

# OAuth token store (in-memory for demo)
oauth_tokens = {}


async def agent_loop():
    """Main agent loop — runs every 2 minutes."""
    await run_detection_cycle(DEMO_CUSTOMER_IDS)

    # Process pending events
    pending = await get_pending_events()
    for event in pending:
        try:
            customer = {"customer_id": event["customer_id"], "loyalty_tier": "Regular", "total_orders": 5, "total_spend": 2000}
            score = await score_churn_risk(event, customer)
            result = await execute_recovery(event, customer, score)
            await update_event(
                event["id"],
                risk_score=score.get("risk_tier"),
                recovery_action=result.get("recovery_type"),
                message_sent=result.get("message"),
                message_sent_at=__import__("datetime").datetime.now().isoformat()
            )
        except Exception as e:
            print(f"[Loop] Error processing event {event['id']}: {e}")

    # Check for retained customers
    await check_for_next_orders()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    scheduler.add_job(agent_loop, "interval", seconds=int(os.getenv("POLL_INTERVAL_SECONDS", 120)), id="agent_loop")
    scheduler.start()
    print("[SwiggyGuard] Agent started. Polling every 2 minutes.")
    yield
    scheduler.shutdown()


app = FastAPI(title="SwiggyGuard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="dashboard/static"), name="static")


# ── Dashboard ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    with open("dashboard/index.html") as f:
        return f.read()


@app.get("/api/stats")
async def stats():
    return await get_dashboard_stats()


@app.get("/api/events")
async def events():
    return await get_recent_events(50)


# ── OAuth Callback (for Swiggy MCP auth) ──────────────────────────────────────

@app.get("/callback")
async def oauth_callback(request: Request):
    """
    Swiggy MCP OAuth redirect URI.
    Exchanges authorization code for access token.
    """
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        return HTMLResponse(f"""
        <html><body style="font-family:sans-serif;padding:40px;background:#fff0f0">
        <h2>Auth Error</h2><p>{error}</p>
        </body></html>
        """, status_code=400)

    if not code:
        return HTMLResponse("<html><body>Missing authorization code.</body></html>", status_code=400)

    # Exchange code for token
    try:
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://api.swiggy.com/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": os.getenv("SWIGGY_CLIENT_ID"),
                    "client_secret": os.getenv("SWIGGY_CLIENT_SECRET"),
                    "redirect_uri": os.getenv("REDIRECT_URI", "http://localhost:8000/callback")
                }
            )
            token_data = token_response.json()
            oauth_tokens["access_token"] = token_data.get("access_token")
            oauth_tokens["refresh_token"] = token_data.get("refresh_token")

        return HTMLResponse("""
        <html><body style="font-family:sans-serif;padding:40px;text-align:center">
        <h2 style="color:#1e8a5e">✓ Connected to Swiggy MCP</h2>
        <p>SwiggyGuard is now authorised. You can close this tab.</p>
        <script>setTimeout(()=>window.close(),2000)</script>
        </body></html>
        """)

    except Exception as e:
        return HTMLResponse(f"""
        <html><body style="font-family:sans-serif;padding:40px">
        <h2>Token Exchange Failed</h2><p>{str(e)}</p>
        <p><small>Code received: {code[:20]}...</small></p>
        </body></html>
        """, status_code=500)


@app.get("/health")
async def health():
    return {"status": "running", "agent": "SwiggyGuard v1.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
