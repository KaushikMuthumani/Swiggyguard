"""
Follow-up Agent
After a recovery message is sent, watches for the customer's next order.
When they order again, sends a follow-up and marks them as retained.
This is the layer that proves the system works.
"""

import httpx
import os
from datetime import datetime
from db import update_event, get_recent_events

FOOD_MCP_URL = os.getenv("SWIGGY_MCP_FOOD_URL")


async def check_for_next_orders():
    """Check if any recovered customers have placed a new order."""
    from messaging.whatsapp import send_whatsapp

    # Get all events where message was sent but not yet retained
    events = await get_recent_events(limit=100)
    pending = [e for e in events if e.get("message_sent") and not e.get("retained")]

    for event in pending:
        customer_id = event["customer_id"]
        sent_at = event.get("message_sent_at")
        if not sent_at:
            continue

        try:
            headers = {"Authorization": f"Bearer {os.getenv('SWIGGY_CLIENT_ID')}:{os.getenv('SWIGGY_CLIENT_SECRET')}"}
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(FOOD_MCP_URL, json={
                    "tool": "get_orders",
                    "params": {"customer_id": customer_id, "limit": 3, "after": sent_at}
                }, headers=headers)
                orders = r.json().get("orders", [])

            if orders:
                # Customer ordered again — they're retained
                new_order = orders[0]
                await update_event(event["id"], retained=1)

                # Send a warm follow-up
                phone = event.get("customer_phone")
                if phone:
                    followup = (
                        f"We noticed you ordered again — and honestly, that means a lot to us. "
                        f"Hope this one was everything it should've been. "
                        f"If it wasn't, you know we'll make it right. 🧡"
                    )
                    await send_whatsapp(phone, followup)

                print(f"[Followup] Customer {customer_id} RETAINED — ordered ₹{new_order.get('order_total', 0):.0f}")

        except Exception as e:
            print(f"[Followup] Error checking customer {customer_id}: {e}")
