"""
Scoring Agent
Uses Claude API to calculate churn risk from event + customer data.
Returns: Low / Medium / High / Critical + recommended recovery action.
"""

import anthropic
import json
import os

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SCORER_PROMPT = open("prompts/scorer.txt").read()


def build_scoring_context(event: dict, customer: dict) -> str:
    return f"""
EVENT DETAILS:
- Type: {event['event_type']}
- Order ID: {event['order_id']}
- Data: {event.get('event_data', '{}')}

CUSTOMER PROFILE:
- Customer ID: {customer.get('customer_id')}
- Total Orders: {customer.get('total_orders', 0)}
- Total Lifetime Spend: ₹{customer.get('total_spend', 0):,.0f}
- Loyalty Tier: {customer.get('loyalty_tier', 'Unknown')}
- Previous Bad Experiences: {customer.get('bad_experiences', 0)}
- Last Order: {customer.get('last_order_at', 'Unknown')}
"""


async def score_churn_risk(event: dict, customer: dict) -> dict:
    """Send event + customer data to Claude. Get back risk score + recovery plan."""

    context = build_scoring_context(event, customer)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=SCORER_PROMPT,
        messages=[{"role": "user", "content": context}]
    )

    text = response.content[0].text.strip()

    try:
        # Claude returns JSON as instructed in the system prompt
        result = json.loads(text)
    except json.JSONDecodeError:
        # Fallback if Claude adds prose
        import re
        match = re.search(r'\{.*\}', text, re.DOTALL)
        result = json.loads(match.group()) if match else {
            "risk_tier": "Medium",
            "recovery_type": "FOOD_CREDIT",
            "recovery_value": 100,
            "reasoning": text,
            "cross_vertical": False
        }

    print(f"[Scorer] Risk: {result.get('risk_tier')} | Recovery: {result.get('recovery_type')}")
    return result
