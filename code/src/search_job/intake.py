"""Import portable company/board route seeds without importing old job filters."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

from .core import upsert_board, upsert_company


def import_seed(db: sqlite3.Connection, path: Path) -> dict[str, int]:
    data = json.loads(path.read_text())
    counts = {"companies": 0, "boards": 0, "pending": 0, "identity_review": 0}
    for item in data["companies"]:
        domain = item["domain"].lower().strip()
        if not domain or "/" in domain or ":" in domain:
            raise ValueError(f"Invalid company domain: {domain}")
        key = domain
        upsert_company(db, key, item["name"], f"https://{domain}/", "route-seed")
        counts["companies"] += 1
        for route in item.get("routes", []):
            provider, token = route["provider"], route.get("board_token")
            if not token:
                counts["pending"] += 1
                continue
            board_key = f"{provider}:{token}"
            evidence = route.get("evidence_url")
            if evidence and urlsplit(evidence).scheme != "https":
                raise ValueError(f"Non-HTTPS route evidence for {key}")
            upsert_board(db, board_key, provider, token, evidence)
            status = "pending_identity" if route.get("identity_review") else "pending_recheck"
            db.execute("""INSERT INTO company_boards(company_key,board_key,evidence_url,brand_filter,status)
              VALUES (?,?,?,?,?) ON CONFLICT(company_key,board_key)
              DO UPDATE SET evidence_url=excluded.evidence_url,
              brand_filter=excluded.brand_filter,
              status=CASE WHEN company_boards.status='pending_identity'
                THEN excluded.status ELSE company_boards.status END""", (key, board_key, evidence, route.get("brand_filter"), status))
            counts["boards"] += 1
            counts["identity_review"] += status == "pending_identity"
    return counts
