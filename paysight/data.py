"""Build an immutable, seeded SQLite snapshot. Only the setup path writes."""

import os
import random
import sqlite3
import tempfile
from datetime import date, timedelta
from pathlib import Path

START = date(2026, 10, 5)
END = date(2026, 11, 15)
METHODS = ["UPI", "Credit Card", "Debit Card", "Net Banking", "Wallet"]
BANKS = ["Meridian", "Northstar", "Cedar", "Rivermark"]
REGIONS = ["North", "South", "East", "West"]
CATEGORIES = [
    "Retail",
    "Travel",
    "Education",
    "Food Delivery",
    "Healthcare",
    "E-commerce",
]
DEFAULT = Path(__file__).resolve().parents[1] / "data" / "payments-v1.sqlite"


def build(path=DEFAULT):
    path = Path(path)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    os.close(fd)
    db = sqlite3.connect(tmp)
    rng = random.Random(412)
    try:
        db.executescript("""
        CREATE TABLE merchants(id INTEGER PRIMARY KEY,name TEXT,category TEXT,region TEXT);
        CREATE TABLE banks(id INTEGER PRIMARY KEY,name TEXT);
        CREATE TABLE raw_transactions(id INTEGER, day TEXT, bank_id INTEGER, merchant_id INTEGER,
            method TEXT, status TEXT, paise INTEGER, reason TEXT);
        """)
        db.executemany("INSERT INTO banks VALUES(?,?)", enumerate(BANKS))
        db.executemany(
            "INSERT INTO merchants VALUES(?,?,?,?)",
            [
                (i, f"Merchant {i + 1:02d}", CATEGORIES[i % 6], REGIONS[(i // 6) % 4])
                for i in range(48)
            ],
        )
        rows = []
        for d in range((END - START).days + 1):
            recent = d >= 35
            for _ in range(rng.randint(930, 1070)):
                i = len(rows) + 1
                bank, merchant = rng.randrange(4), rng.randrange(48)
                method = rng.choices(
                    METHODS, [55, 18, 13, 8, 6] if recent else [23, 38, 22, 10, 7]
                )[0]
                risk = (
                    0.025
                    + 0.105 * (method == "UPI")
                    + 0.045 * (merchant % 6 == 1)
                    + 0.16 * (recent and bank == 1)
                )
                status = (
                    "PENDING"
                    if rng.random() < 0.015
                    else ("FAILED" if rng.random() < risk else "SUCCESS")
                )
                reason = None
                if status == "FAILED":
                    reason = rng.choices(
                        [
                            "Bank timeout",
                            "Insufficient funds",
                            "Authentication failure",
                            "Network error",
                        ],
                        [65 if recent and bank == 1 else 18, 35, 22, 15],
                    )[0]
                rows.append(
                    (
                        i,
                        (START + timedelta(days=d)).isoformat(),
                        bank,
                        merchant,
                        method,
                        status,
                        rng.randint(1000, 420000),
                        reason,
                    )
                )
        # Remove the reason from 15 distinct failed attempts before copying duplicates.
        misses = [j for j, r in enumerate(rows) if r[5] == "FAILED"][:15]
        for j in misses:
            rows[j] = (*rows[j][:-1], None)
        db.executemany(
            "INSERT INTO raw_transactions VALUES(?,?,?,?,?,?,?,?)", rows + rows[:24]
        )
        db.executescript("""
        CREATE INDEX raw_id ON raw_transactions(id);
        CREATE TABLE attempts AS SELECT * FROM raw_transactions WHERE rowid IN
            (SELECT MIN(rowid) FROM raw_transactions GROUP BY id);
        CREATE UNIQUE INDEX attempts_id ON attempts(id);
        CREATE INDEX attempts_day ON attempts(day);
        CREATE VIEW eligible AS SELECT a.day,a.method,a.status,a.paise,
            COALESCE(a.reason,'Unknown') AS reason,b.name AS bank,m.category,m.region
            FROM attempts a JOIN banks b ON b.id=a.bank_id JOIN merchants m ON m.id=a.merchant_id
            WHERE a.status IN ('SUCCESS','FAILED');
        """)
        db.commit()
        db.close()
        os.replace(tmp, path)
    finally:
        db.close()
        Path(tmp).unlink(missing_ok=True)
    return path


def connect(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def quality(path):
    with connect(path) as db:
        return {
            "Raw rows": db.execute("SELECT count(*) FROM raw_transactions").fetchone()[
                0
            ],
            "Unique attempts": db.execute("SELECT count(*) FROM attempts").fetchone()[
                0
            ],
            "Duplicates": db.execute(
                "SELECT id, count(*) AS copies FROM raw_transactions GROUP BY id HAVING copies>1"
            ).fetchall(),
            "Missing failure reasons": db.execute(
                "SELECT id FROM attempts WHERE status='FAILED' AND reason IS NULL"
            ).fetchall(),
            "Pending": db.execute(
                "SELECT count(*) FROM attempts WHERE status='PENDING'"
            ).fetchone()[0],
            "Orphan references": db.execute(
                "SELECT count(*) FROM attempts a LEFT JOIN banks b ON b.id=a.bank_id LEFT JOIN merchants m ON m.id=a.merchant_id WHERE b.id IS NULL OR m.id IS NULL"
            ).fetchone()[0],
        }


if __name__ == "__main__":
    print(build())
