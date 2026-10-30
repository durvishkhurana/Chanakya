"""Seed the mock systems with demo merchants. Fictional data only.

Run: ``python -m chanakya.actions.systems.seed [db_path]``
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

from chanakya.actions.systems.db import MockDB
from chanakya.core.config import Settings

# id, name, business type, city, language, window, do_not_call, soundbox, card machine, phone last 4
MERCHANTS = [
    ("mer_ramesh", "Ramesh Kirana Store", "kirana", "Patiala", "hi-IN", (14, 17), 0, 0, 0, "4821"),
    ("mer_gurpreet", "Gurpreet Medical Hall", "pharmacy", "Ludhiana", "pa-IN", (10, 13), 0, 1, 0, "1907"),
    ("mer_anita", "Anita Sweets", "sweet shop", "Jaipur", "hi-IN", (11, 19), 0, 1, 0, "6634"),
    ("mer_imran", "Imran Mobile Point", "mobile accessories", "Lucknow", "hi-IN", (12, 20), 0, 0, 0, "2290"),
    ("mer_lakshmi", "Lakshmi Tailors", "tailoring", "Chennai", "en-IN", (10, 18), 0, 1, 0, "7712"),
    ("mer_sharma", "Sharma General Store", "general store", "Delhi", "hi-IN", (9, 21), 0, 0, 0, "3345"),
    ("mer_baldev", "Baldev Dhaba", "restaurant", "Amritsar", "pa-IN", (15, 18), 1, 0, 0, "5508"),
]
# Former merchants for win-back missions (WINBACK_ENABLED): id, name, business type, city, language, window,
# phone last 4, days since they stopped. Fictional, like everyone above.
FORMER_MERCHANTS = [
    ("mer_harish", "Harish Electronics", "electronics", "Patna", "hi-IN", (10, 19), "6120", 35),  # returned a Soundbox
    ("mer_meena", "Meena Sweets", "sweet shop", "Bhopal", "hi-IN", (11, 20), "8841", 70),  # Soundbox idle 70 days
    ("mer_joginder", "Joginder Auto Parts", "auto parts", "Chandigarh", "pa-IN", (10, 18), "3017", 25),  # late settlement
    ("mer_kavita", "Kavita Fancy Store", "clothing store", "Kanpur", "hi-IN", (12, 20), "5562", 50),  # open complaint
]


def _ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")


def seed(db: MockDB) -> None:
    """Insert demo merchants, devices, settlements and one stalled onboarding. Safe to run twice."""
    with db.conn:
        for m in MERCHANTS:
            merchant_id, name, kind, city, language, (start, end), dnc, soundbox, pos, last4 = m
            db.conn.execute("INSERT OR IGNORE INTO merchants (id, name, business_type, city, language, start_hour, "
                            "end_hour, do_not_call, has_soundbox, has_card_machine, phone_last4) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (merchant_id, name, kind, city, language, start, end, dnc, soundbox, pos, last4))
        devices = [
            ("dev_gurpreet_sb", "mer_gurpreet", "soundbox", "online", _ago(8), "paid"),
            ("dev_anita_sb", "mer_anita", "soundbox", "online", _ago(0), "paid"),
            ("dev_lakshmi_sb", "mer_lakshmi", "soundbox", "online", _ago(1), "overdue"),
        ]
        db.conn.executemany("INSERT OR IGNORE INTO devices VALUES (?, ?, ?, ?, ?, ?)", devices)
        settlements = [
            ("set_anita_1", "mer_anita", 18450, "settled", _ago(1)[:10], None),
            ("set_lakshmi_1", "mer_lakshmi", 6200, "delayed", _ago(2)[:10], "bank holiday at partner bank"),
        ]
        db.conn.executemany("INSERT OR IGNORE INTO settlements VALUES (?, ?, ?, ?, ?, ?)", settlements)
        db.conn.execute("INSERT OR IGNORE INTO onboarding_sessions VALUES (?, ?, NULL, ?, 'pending', ?, NULL)",
                        ("onb_imran_stalled", "mer_imran", "soundbox", _ago(2)))
        seed_former(db)


def seed_former(db: MockDB) -> None:
    """Former merchants with a returned or idle device, one late settlement and one open complaint ticket."""
    for merchant_id, name, kind, city, language, (start, end), last4, days in FORMER_MERCHANTS:
        db.conn.execute("INSERT OR IGNORE INTO merchants (id, name, business_type, city, language, start_hour, "
                        "end_hour, do_not_call, has_soundbox, has_card_machine, phone_last4, relationship, churned_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?, 'former', ?)",
                        (merchant_id, name, kind, city, language, start, end, last4, _ago(days)))
    db.conn.executemany("INSERT OR IGNORE INTO devices VALUES (?, ?, ?, ?, ?, ?)", [
        ("dev_harish_sb", "mer_harish", "soundbox", "returned", _ago(36), "closed"),
        ("dev_meena_sb", "mer_meena", "soundbox", "online", _ago(70), "paid"),
        ("dev_joginder_sb", "mer_joginder", "soundbox", "returned", _ago(26), "closed"),
        ("dev_kavita_sb", "mer_kavita", "soundbox", "returned", _ago(51), "closed"),
    ])
    db.conn.execute("INSERT OR IGNORE INTO settlements VALUES (?, ?, ?, ?, ?, ?)",
                    ("set_joginder_1", "mer_joginder", 9300, "delayed", _ago(27)[:10], "bank account details mismatch"))
    db.conn.execute("INSERT OR IGNORE INTO tickets VALUES (?, ?, NULL, ?, ?, 'open', ?)",
                    ("tkt_kavita_open", "mer_kavita", "device",
                     "Soundbox stopped announcing payments; merchant returned it and is waiting for an answer", _ago(52)))


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else Settings.from_env().db_path
    seed(MockDB(path))
    print(f"Seeded mock systems in {path}")
