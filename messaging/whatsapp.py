"""
WhatsApp messaging via Twilio.
"""

import os
from twilio.rest import Client

def send_whatsapp(to_number: str, message: str) -> bool:
    """Send a WhatsApp message via Twilio. Returns True if sent."""
    try:
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        from_number = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

        if not account_sid or not auth_token:
            print(f"[WhatsApp] MOCK SEND to {to_number}:\n{message}\n")
            return True  # Mock success in dev

        client = Client(account_sid, auth_token)
        msg = client.messages.create(
            from_=from_number,
            to=f"whatsapp:{to_number}",
            body=message
        )
        print(f"[WhatsApp] Sent to {to_number} — SID: {msg.sid}")
        return True

    except Exception as e:
        print(f"[WhatsApp] Failed to send to {to_number}: {e}")
        return False
