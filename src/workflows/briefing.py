"""Briefing quotidien Belfort & Giromagny — recherche d'actualités puis envoi par e-mail."""

import json
from datetime import date, timedelta
from typing import Any

import pydantic

import mistralai.workflows as workflows
from mistralai.workflows import Depends
from mistralai.workflows.plugins.mistralai.connectors import (
    ToolCallClient,
    connector,
    uses_connectors,
)

web_search_connector = connector("web_search")
gmail_connector = connector("gmail")

RECIPIENT = "pascal.gaumez@gmail.com"

NEWS_QUERIES = [
    "Belfort actualité",
    "Giromagny actualité",
    "Territoire de Belfort actualité",
]

WEB_QUERIES = [
    "actualité Belfort 90000",
    "Giromagny mairie actualité",
]

RELEVANT = ("belfort", "giromagny", "90000", "danjoutin", "andelnans", "offemont", "valdoie", "vétrigne", "botans")


class BriefingInput(pydantic.BaseModel):
    recipient: str = RECIPIENT


def _extract_items(raw: Any) -> list:
    """Normalise la réponse d'un outil de recherche en liste d'items."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if isinstance(raw, dict):
        if all(k in raw for k in ("snippets", "rank")):
            candidates = [raw]
        else:
            candidates = [v for v in raw.values() if isinstance(v, dict)]
    elif isinstance(raw, list):
        candidates = raw
    else:
        return []
    items = []
    for c in candidates:
        if not isinstance(c, dict) or "snippets" not in c:
            continue
        items.append(
            {
                "title": c.get("title") or "",
                "url": c.get("url") or "",
                "date": c.get("date") or "",
                "source": c.get("source") or "",
                "snippet": (c.get("snippets") or [""])[0],
            }
        )
    return items


@workflows.activity(name="collect-news")
async def collect_news(
    ws: ToolCallClient = Depends(web_search_connector),
) -> str:
    start = (date.today() - timedelta(days=2)).isoformat()
    end = date.today().isoformat()
    items = []

    for q in NEWS_QUERIES:
        res = await ws.call_tool(
            "news_search",
            {"query": q, "start_date": start, "end_date": end, "lang": "fr", "limit": 10},
        )
        items.extend(_extract_items(res))

    for q in WEB_QUERIES:
        res = await ws.call_tool(
            "web_search",
            {"query": q, "start_date": start, "end_date": end, "limit": 10},
        )
        items.extend(_extract_items(res))

    seen = set()
    local = []
    for it in items:
        key = (it["url"] or it["title"]).strip().lower()
        text = " ".join([it["title"], it["snippet"], it["url"]]).lower()
        if not key or key in seen:
            continue
        if not any(k in text for k in RELEVANT):
            continue
        seen.add(key)
        local.append(it)

    local.sort(key=lambda x: x["date"] or "", reverse=True)
    return json.dumps(local[:15], ensure_ascii=False)


@workflows.activity(name="render-briefing")
async def render_briefing(news_json: str) -> dict:
    try:
        items = json.loads(news_json)
    except json.JSONDecodeError:
        items = []

    today = date.today().strftime("%d/%m/%Y")
    subject = "🗞️ Briefing Belfort & Giromagny — " + today

    md_lines = ["# 🗞️ Briefing Belfort & Giromagny (" + today + ")", ""]
    html_parts = [
        "<div style='font-family:sans-serif;max-width:640px'>",
        "<h2>🗞️ Briefing Belfort &amp; Giromagny (" + today + ")</h2>",
    ]

    if not items:
        md_lines.append("Pas d'actualité locale notable détectée ce matin.")
        html_parts.append("<p>Pas d'actualité locale notable détectée ce matin.</p>")
    else:
        for it in items:
            snippet = (it["snippet"] or "").strip()
            if len(snippet) > 280:
                snippet = snippet[:277] + "…"
            meta = " — ".join(m for m in [it["source"], it["date"]] if m)
            md_lines.append("- **" + it["title"] + "** — " + snippet + " _(" + meta + ")_ [source](" + it["url"] + ")")
            html_parts.append(
                "<p style='margin:10px 0'>"
                "<a href=\"" + it["url"] + "\"><b>" + it["title"] + "</b></a><br>"
                "<span style='color:#333'>" + snippet + "</span><br>"
                "<small style='color:#888'>" + meta + "</small></p>"
            )

    md_lines.append("")
    md_lines.append("<small>Briefing automatique — recherche web et presse sur les dernières 48 h.</small>")
    html_parts.append("<p><small>Briefing automatique — recherche web et presse sur les dernières 48 h.</small></p></div>")

    return {"subject": subject, "markdown": "\n".join(md_lines), "html": "\n".join(html_parts)}


@workflows.activity(name="send-briefing")
async def send_briefing(
    rendered: dict, recipient: str, gmail: ToolCallClient = Depends(gmail_connector)
) -> None:
    await gmail.call_tool(
        "send_email",
        {
            "to": [recipient],
            "subject": rendered["subject"],
            "body": rendered["markdown"],
            "htmlBody": rendered["html"],
        },
    )


@workflows.workflow.define(
    name="belfort-giromagny-briefing",
    workflow_display_name="Briefing Belfort & Giromagny",
    workflow_description="Recherche les actualités de Belfort et Giromagny (48 h) et envoie un briefing par e-mail.",
    on_behalf_of=True,
)
@uses_connectors(web_search_connector, gmail_connector)
class BelfortBriefingWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, input: BriefingInput) -> str:
        news = await collect_news()
        rendered = await render_briefing(news)
        await send_briefing(rendered, input.recipient)
        return rendered["subject"]
