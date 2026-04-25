"""
Detection Agent
Polls Swiggy Food MCP every 2 minutes.
Watches for: ETA breach, wrong item complaint, low rating, bad refund ratio.
Writes events to SQLite queue.
"""

import httpx
import json
import os
from datetime import datetime, timedelta
from db import insert_event, upsert_customer

FOOD_MCP_URL = os.getenv("SWIGGY_MCP_FOOD_URL")
ETA_BREACH_MINS = int(os.getenv("ETA_BREACH_THRESHOLD_MINUTES", 20))
REFUND_RATIO_THRESHOLD = float(os.getenv("LOW_REFUND_RATIO_THRESHOLD", 0.2))

# In-memory set of already-processed order IDs
processed_orders = set()


async def call_mcp_tool(tool_name: str, params: dict) -> dict:
    """Call a Swiggy MCP tool and return the result."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.getenv('SWIGGY_CLIENT_ID')}:{os.getenv('SWIGGY_CLIENT_SECRET')}"
    }
    payload = {"tool": tool_name, "params": params}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(FOOD_MCP_URL, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


def detect_eta_breach(order: dict) -> bool:
    promised = order.get("promised_delivery_time")
    actual = order.get("actual_delivery_time") or order.get("current_time")
    if not promised or not actual:
        return False
    try:
        fmt = "%Y-%m-%dT%H:%M:%S"
        delta = datetime.strptime(actual, fmt) - datetime.strptime(promised, fmt)
        return delta.total_seconds() / 60 > ETA_BREACH_MINS
    except Exception:
        return False


def detect_bad_refund(order: dict) -> bool:
    refund = order.get("refund_amount", 0)
    total = order.get("order_total", 0)
    if total == 0:
        return False
    ratio = refund / total
    return 0 < ratio < REFUND_RATIO_THRESHOLD


def detect_low_rating(order: dict) -> bool:
    rating = order.get("customer_rating")
    return rating is not None and rating <= 2


def detect_wrong_item(order: dict) -> bool:
    complaints = order.get("complaints", [])
    wrong_keywords = ["wrong", "missing", "different", "incorrect", "not ordered"]
    for c in complaints:
        if any(kw in c.get("type", "").lower() for kw in wrong_keywords):
            return True
    return False


async def fetch_active_orders(customer_ids: list) -> list:
    """Fetch recent orders for a list of customer IDs."""
    orders = []
    for cid in customer_ids:
        try:
            result = await call_mcp_tool("get_orders", {"customer_id": cid, "limit": 5})
            orders.extend(result.get("orders", []))
        except Exception as e:
            print(f"[Detector] Error fetching orders for {cid}: {e}")
    return orders


async def run_detection_cycle(customer_ids: list):
    """Main detection loop — called every 2 minutes by scheduler."""
    print(f"[Detector] Running detection cycle at {datetime.now().isoformat()}")

    orders = await fetch_active_orders(customer_ids)
    new_events = 0

    for order in orders:
        order_id = order.get("order_id")
        customer_id = order.get("customer_id")

        if not order_id or order_id in processed_orders:
            continue

        # Update customer profile
        history = order.get("customer_history", {})
        tier = await upsert_customer(
            customer_id,
            history.get("total_orders", 0),
            history.get("total_spend", 0)
        )

        # Check each failure type
        if detect_wrong_item(order):
            await insert_event(order_id, customer_id, "WRONG_ITEM", {
                "order_total": order.get("order_total"),
                "refund_amount": order.get("refund_amount", 0),
                "items_ordered": order.get("items", []),
                "complaints": order.get("complaints", []),
                "loyalty_tier": tier
            })
            print(f"[Detector] WRONG_ITEM detected for order {order_id}")
            processed_orders.add(order_id)
            new_events += 1

        elif detect_eta_breach(order):
            await insert_event(order_id, customer_id, "ETA_BREACH", {
                "promised_time": order.get("promised_delivery_time"),
                "actual_time": order.get("actual_delivery_time"),
                "order_total": order.get("order_total"),
                "loyalty_tier": tier
            })
            print(f"[Detector] ETA_BREACH detected for order {order_id}")
            processed_orders.add(order_id)
            new_events += 1

        elif detect_bad_refund(order):
            await insert_event(order_id, customer_id, "BAD_REFUND", {
                "order_total": order.get("order_total"),
                "refund_amount": order.get("refund_amount"),
                "refund_ratio": round(order.get("refund_amount", 0) / order.get("order_total", 1), 2),
                "loyalty_tier": tier
            })
            print(f"[Detector] BAD_REFUND detected for order {order_id}")
            processed_orders.add(order_id)
            new_events += 1

        elif detect_low_rating(order):
            await insert_event(order_id, customer_id, "LOW_RATING", {
                "rating": order.get("customer_rating"),
                "order_total": order.get("order_total"),
                "loyalty_tier": tier
            })
            print(f"[Detector] LOW_RATING detected for order {order_id}")
            processed_orders.add(order_id)
            new_events += 1

    print(f"[Detector] Cycle complete. {new_events} new events detected.")
    return new_events
