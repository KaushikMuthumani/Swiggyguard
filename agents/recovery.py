"""
Recovery Agent
Claude writes a personalised WhatsApp recovery message.
For HIGH/CRITICAL risk customers, triggers cross-vertical Dineout recovery.
"""

import anthropic
import httpx
import json
import os

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
DINEOUT_MCP_URL = os.getenv("SWIGGY_MCP_DINEOUT_URL")
RECOVERY_PROMPT = open("prompts/recovery.txt").read()


async def get_dineout_offer(customer_id: str, city: str = "Bangalore") -> dict | None:
    """Pull a real Dineout slot to include in the recovery message."""
    try:
        headers = {"Authorization": f"Bearer {os.getenv('SWIGGY_CLIENT_ID')}:{os.getenv('SWIGGY_CLIENT_SECRET')}"}
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(DINEOUT_MCP_URL, json={
                "tool": "search_restaurants_dineout",
                "params": {"city": city, "cuisine": "fine_dining", "limit": 3}
            }, headers=headers)
            restaurants = r.json().get("restaurants", [])
            if not restaurants:
                return None

            top = restaurants[0]
            slots_r = await c.post(DINEOUT_MCP_URL, json={
                "tool": "get_available_slots",
                "params": {"restaurant_id": top["id"], "party_size": 2}
            }, headers=headers)
            slots = slots_r.json().get("slots", [])
            if not slots:
                return None

            return {
                "restaurant_name": top["name"],
                "restaurant_cuisine": top.get("cuisine", ""),
                "slot": slots[0],
                "restaurant_id": top["id"]
            }
    except Exception as e:
        print(f"[Recovery] Dineout fetch failed: {e}")
        return None


async def generate_recovery_message(event: dict, customer: dict, score: dict) -> str:
    """Use Claude to write the personalised recovery message."""

    dineout_offer = None
    if score.get("cross_vertical") and score.get("risk_tier") in ["High", "Critical"]:
        dineout_offer = await get_dineout_offer(customer.get("customer_id", ""))

    context = f"""
EVENT: {event['event_type']}
EVENT DATA: {event.get('event_data', '{}')}

CUSTOMER:
- Loyalty Tier: {customer.get('loyalty_tier', 'Regular')}
- Total Orders: {customer.get('total_orders', 0)}
- Total Spend: ₹{customer.get('total_spend', 0):,.0f}

RISK SCORE: {score.get('risk_tier')}
RECOVERY TYPE: {score.get('recovery_type')}
RECOVERY VALUE: ₹{score.get('recovery_value', 100)}
CROSS-VERTICAL DINEOUT OFFER: {json.dumps(dineout_offer) if dineout_offer else 'None'}
SCORER REASONING: {score.get('reasoning', '')}
"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=RECOVERY_PROMPT,
        messages=[{"role": "user", "content": context}]
    )

    message = response.content[0].text.strip()
    print(f"[Recovery] Message generated ({len(message)} chars)")
    return message, dineout_offer


async def execute_recovery(event: dict, customer: dict, score: dict) -> dict:
    """Full recovery execution: generate message, send via WhatsApp."""
    from messaging.whatsapp import send_whatsapp

    message, dineout_offer = await generate_recovery_message(event, customer, score)

    phone = customer.get("phone_number")
    sent = False
    if phone:
        sent = await send_whatsapp(phone, message)

    return {
        "message": message,
        "sent": sent,
        "dineout_offer": dineout_offer,
        "recovery_type": score.get("recovery_type"),
        "recovery_value": score.get("recovery_value")
    }
