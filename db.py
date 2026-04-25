import aiosqlite
import json
from datetime import datetime

DB_PATH = "swiggyguard.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_data TEXT,
                risk_score TEXT,
                recovery_action TEXT,
                message_sent TEXT,
                message_sent_at TEXT,
                retained INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                customer_id TEXT PRIMARY KEY,
                total_orders INTEGER DEFAULT 0,
                total_spend REAL DEFAULT 0,
                loyalty_tier TEXT DEFAULT 'New',
                last_order_at TEXT,
                bad_experiences INTEGER DEFAULT 0,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                events_detected INTEGER DEFAULT 0,
                messages_sent INTEGER DEFAULT 0,
                customers_retained INTEGER DEFAULT 0,
                revenue_saved REAL DEFAULT 0
            )
        """)
        await db.commit()

async def insert_event(order_id, customer_id, event_type, event_data):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO events (order_id, customer_id, event_type, event_data)
            VALUES (?, ?, ?, ?)
        """, (order_id, customer_id, event_type, json.dumps(event_data)))
        await db.commit()

async def update_event(event_id, **kwargs):
    cols = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [event_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE events SET {cols} WHERE id=?", vals)
        await db.commit()

async def get_pending_events():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM events WHERE message_sent IS NULL
            ORDER BY created_at DESC LIMIT 20
        """) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

async def get_recent_events(limit=50):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM events ORDER BY created_at DESC LIMIT ?
        """, (limit,)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

async def upsert_customer(customer_id, total_orders, total_spend):
    tier = "New"
    if total_orders >= 20 or total_spend >= 15000:
        tier = "Tier 1"
    elif total_orders >= 10 or total_spend >= 7000:
        tier = "Tier 2"
    elif total_orders >= 3:
        tier = "Regular"

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO customers (customer_id, total_orders, total_spend, loyalty_tier, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(customer_id) DO UPDATE SET
                total_orders=excluded.total_orders,
                total_spend=excluded.total_spend,
                loyalty_tier=excluded.loyalty_tier,
                updated_at=excluded.updated_at
        """, (customer_id, total_orders, total_spend, tier))
        await db.commit()
    return tier

async def get_dashboard_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT COUNT(*) as total FROM events") as c:
            total_events = (await c.fetchone())["total"]
        async with db.execute("SELECT COUNT(*) as total FROM events WHERE message_sent IS NOT NULL") as c:
            messages_sent = (await c.fetchone())["total"]
        async with db.execute("SELECT COUNT(*) as total FROM events WHERE retained=1") as c:
            retained = (await c.fetchone())["total"]
        async with db.execute("SELECT COUNT(*) as total FROM customers") as c:
            total_customers = (await c.fetchone())["total"]
        async with db.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT 10") as c:
            recent = [dict(r) for r in await c.fetchall()]

    return {
        "total_events": total_events,
        "messages_sent": messages_sent,
        "customers_retained": retained,
        "total_customers": total_customers,
        "recent_events": recent,
        "retention_rate": round((retained / messages_sent * 100) if messages_sent > 0 else 0, 1)
    }
