"""A local, read-only dashboard for staged company leads and their original links."""
from __future__ import annotations

import html
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


TEMPLATE = Path(__file__).parents[2] / "templates" / "review-dashboard.html"
STAGES = {"route_pending": "ATS 路线待核实", "board_pending": "招聘板归属待核实",
          "adapter_pending": "Adapter 待开发", "scan_pending": "等待岗位扫描"}
REVIEW_STATES = {"script_pending": "等待脚本", "ai_pending": "待 AI 处理",
                 "ai_in_progress": "AI 核查中", "needs_user": "需要你提供线索",
                 "resolved": "路线已确认"}


def _safe_link(url: str | None, *, missing: str = "暂无") -> str:
    if not url:
        return f'<span class="missing">{html.escape(missing)}</span>'
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return f'<span class="missing">{html.escape(url)}（不可直接打开）</span>'
    escaped = html.escape(url, quote=True)
    return f'<a href="{escaped}" target="_blank" rel="noopener noreferrer">{html.escape(url)}</a>'


def _reason(row: sqlite3.Row) -> str:
    if row["stage"] == "adapter_pending":
        return f"官方 ATS 已确认；{row['provider_hint'] or '未知'} adapter 尚未完成"
    if row["stage"] == "board_pending":
        return row["last_error"] or "已发现 ATS 线索，但公司招聘板归属尚未确定"
    if row["stage"] == "scan_pending":
        return row["last_error"] or "官方路线已确认，等待完整扫描"
    return row["last_error"] or "尚未完成官网路线核实"


def dashboard_snapshot(db: sqlite3.Connection) -> dict:
    rows = db.execute("""SELECT * FROM source_leads WHERE source_name='simplify'
      ORDER BY CAST(source_id AS INTEGER)""").fetchall()
    stages = Counter(row["stage"] for row in rows)
    reviews = Counter(row["review_state"] for row in rows if row["stage"] != "scanned")
    return {"total": len(rows), "scanned": stages["scanned"],
            "pending": len(rows) - stages["scanned"],
            "stages": dict(stages), "review_states": dict(reviews), "rows": rows}


def write_review_dashboard(db: sqlite3.Connection, path: Path) -> dict:
    snapshot = dashboard_snapshot(db)
    cards = []
    for row in snapshot["rows"]:
        if row["stage"] == "scanned":
            continue
        stage = row["stage"]
        state = row["review_state"]
        name = html.escape(row["name"])
        key = html.escape(row["lead_key"])
        search = html.escape(" ".join(str(row[field] or "") for field in
            ("name", "lead_key", "provider_hint", "board_hint", "last_error", "ai_review_note")),
            quote=True).lower()
        links = [
            ("Simplify 公司资料", row["profile_url"]),
            ("Simplify 列表来源", row["source_url"]),
            ("原始目录中的公司官网", row["source_company_url"]),
            ("从 Simplify 资料提取的官网", row["profile_company_url"]),
            ("当前候选／已确认官网", row["official_url"]),
            ("原始样本 Job", row["sample_apply_url"]),
            ("样本 Job 跳转后", row["sample_probe_url"]),
            ("官方证据页", row["route_evidence_url"]),
            ("官方 ATS 岗位链接", row["official_board_url"]),
        ]
        link_items = "".join(f"<dt>{html.escape(label)}</dt><dd>{_safe_link(url, missing='原始目录未提供' if label == '原始目录中的公司官网' else '暂无')}</dd>"
                             for label, url in links)
        cards.append(f'''<article class="lead" data-stage="{html.escape(stage, quote=True)}"
          data-review="{html.escape(state, quote=True)}" data-search="{search}">
          <div class="lead-head"><div><h2>{name}</h2><small>{key}</small></div>
          <div class="badges"><span class="badge">{html.escape(STAGES.get(stage, stage))}</span>
          <span class="badge review">{html.escape(REVIEW_STATES.get(state, state))}</span></div></div>
          <p class="reason">{html.escape(_reason(row))}</p>
          <p class="hint">ATS 线索：{html.escape(row["provider_hint"] or "未知")}
          {html.escape(row["board_hint"] or "")} · 样本 HTTP：{html.escape(str(row["sample_probe_status"] or "未知"))}</p>
          <details><summary>查看原始链接、官网与核查记录</summary><dl>{link_items}
          <dt>脚本记录</dt><dd>{html.escape(row["last_error"] or "无")}</dd>
          <dt>样本岗位名称／地点</dt><dd>{html.escape(row["sample_title"] or "未提供")} · {html.escape(row["sample_location"] or "未提供")}</dd>
          <dt>AI 核查记录</dt><dd>{html.escape(row["ai_review_note"] or "尚未记录 AI 核查结论")}</dd>
          <dt>最近核查</dt><dd>{html.escape(row["checked_at"] or "尚未核查")}</dd>
          </dl></details></article>''')
    template = TEMPLATE.read_text()
    replacements = {
        "{{generated_at}}": html.escape(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
        "{{total}}": str(snapshot["total"]),
        "{{scanned}}": str(snapshot["scanned"]),
        "{{pending}}": str(snapshot["pending"]),
        "{{route_pending}}": str(snapshot["stages"].get("route_pending", 0)),
        "{{board_pending}}": str(snapshot["stages"].get("board_pending", 0)),
        "{{adapter_pending}}": str(snapshot["stages"].get("adapter_pending", 0)),
        "{{needs_user}}": str(snapshot["review_states"].get("needs_user", 0)),
        "{{cards}}": "\n".join(cards) or '<p class="empty">当前没有待处理公司。</p>',
    }
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template)
    return {"path": str(path), "total": snapshot["total"],
            "scanned": snapshot["scanned"], "pending": snapshot["pending"],
            "needs_user": snapshot["review_states"].get("needs_user", 0)}
