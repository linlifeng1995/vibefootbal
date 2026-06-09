from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

try:
    import bleach
except ImportError:  # pragma: no cover - dependency is declared, fallback keeps app importable.
    bleach = None

try:
    import markdown as markdown_lib
except ImportError:  # pragma: no cover - dependency is declared, fallback keeps app importable.
    markdown_lib = None


DISCLAIMER = "本文为赛前数据分析与观赛参考，不构成任何投注、投资或收益建议。"
FORBIDDEN_TERMS = ("稳赚", "必红", "投注建议", "下注", "赔率套利", "收益", "推荐买入")

_env: Callable[[str, str], str] | None = None
_db: Callable[[], Any] | None = None
_jdump: Callable[[Any], str] | None = None
_jload: Callable[[str | None, Any], Any] | None = None
_now_iso: Callable[[], str] | None = None
_log_event: Callable[[str, str, str, str | None], None] | None = None
_query_public_matches: Callable[[], list[Any]] | None = None
_grouped_matchdays: Callable[[list[Any]], list[dict[str, Any]]] | None = None
_match_report: Callable[[str], dict[str, Any]] | None = None

_ACCESS_TOKEN_CACHE: dict[str, Any] = {"token": "", "expires_at": 0.0}


def configure(
    *,
    env_func: Callable[[str, str], str],
    db_func: Callable[[], Any],
    jdump_func: Callable[[Any], str],
    jload_func: Callable[[str | None, Any], Any],
    now_iso_func: Callable[[], str],
    log_event_func: Callable[[str, str, str, str | None], None],
    query_public_matches_func: Callable[[], list[Any]],
    grouped_matchdays_func: Callable[[list[Any]], list[dict[str, Any]]],
    match_report_func: Callable[[str], dict[str, Any]],
) -> None:
    global _env, _db, _jdump, _jload, _now_iso, _log_event, _query_public_matches, _grouped_matchdays, _match_report
    _env = env_func
    _db = db_func
    _jdump = jdump_func
    _jload = jload_func
    _now_iso = now_iso_func
    _log_event = log_event_func
    _query_public_matches = query_public_matches_func
    _grouped_matchdays = grouped_matchdays_func
    _match_report = match_report_func


def _require_context() -> None:
    if not all((_env, _db, _jdump, _jload, _now_iso, _log_event, _query_public_matches, _grouped_matchdays, _match_report)):
        raise RuntimeError("wechat_article.configure() has not been called")


def _env_value(name: str, default: str = "") -> str:
    _require_context()
    return _env(name, default)  # type: ignore[misc]


def _json_dump(value: Any) -> str:
    _require_context()
    return _jdump(value)  # type: ignore[misc]


def _json_load(value: str | None, default: Any) -> Any:
    _require_context()
    return _jload(value, default)  # type: ignore[misc]


def _now() -> str:
    _require_context()
    return _now_iso()  # type: ignore[misc]


def _log(action: str, status: str, message: str, target_id: str | None = None) -> None:
    _require_context()
    _log_event(action, status, message, target_id)  # type: ignore[misc]


def _extract_report_fields(report_payload: dict[str, Any]) -> dict[str, Any]:
    content = (report_payload.get("report") or {}).get("content") or {}
    return {
        "summary": content.get("summary"),
        "logic": content.get("logic"),
        "score_prediction": content.get("score_prediction"),
        "totals_prediction": content.get("totals_prediction"),
        "risk_points": content.get("risk_points"),
        "key_matchups": content.get("key_matchups"),
        "match_conditions": content.get("match_conditions"),
        "data_confidence_note": content.get("data_confidence_note"),
    }


def build_daily_preview_source(matchday: str) -> dict[str, Any]:
    _require_context()
    grouped = _grouped_matchdays(_query_public_matches())  # type: ignore[misc]
    group = next((item for item in grouped if item.get("matchday") == matchday), None)
    if not group:
        raise ValueError(f"Matchday not found: {matchday}")

    matches: list[dict[str, Any]] = []
    for match in group.get("items") or []:
        item = dict(match)
        try:
            report_payload = _match_report(item["id"])  # type: ignore[misc]
        except Exception as exc:
            item.update({"reportMissing": True, "reportError": str(exc)})
            matches.append(item)
            continue

        item["reportMissing"] = report_payload.get("status") != "published"
        if item["reportMissing"]:
            item["reportNote"] = "报告待更新"
        else:
            item.update(_extract_report_fields(report_payload))
        matches.append(item)

    return {
        "matchday": group.get("matchday"),
        "label": group.get("label"),
        "range": group.get("range"),
        "matches": matches,
    }


def _normalize_article_payload(raw: Any, source: dict[str, Any]) -> dict[str, str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {"markdown": raw}
    if not isinstance(raw, dict):
        raw = {}

    markdown = str(raw.get("markdown") or "").strip()
    if DISCLAIMER not in markdown:
        markdown = f"{markdown.rstrip()}\n\n## 风险提示\n{DISCLAIMER}" if markdown else _fallback_markdown(source)
    markdown = _stabilize_markdown_with_source(markdown, source)
    title = str(raw.get("title") or f"{source.get('label') or source.get('matchday')}世界杯前瞻").strip()[:64]
    digest = str(raw.get("digest") or "基于赛程、模型概率、比分预测和赛前条件，整理今日观赛重点。").strip()[:120]
    return {"title": title, "digest": digest, "markdown": markdown}


def _format_pct(value: Any) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "--"


def _format_time(value: Any) -> str:
    if not value:
        return "时间待定"
    try:
        dt = datetime.fromisoformat(str(value))
        return dt.strftime("%m-%d %H:%M")
    except ValueError:
        return str(value)


def _list_text(value: Any) -> str:
    if isinstance(value, list):
        return "；".join(str(item) for item in value if item)
    return str(value or "")


def _focus_matches(source: dict[str, Any]) -> list[dict[str, Any]]:
    matches = list(source.get("matches") or [])
    return sorted(matches, key=lambda item: float(item.get("confidence") or 0), reverse=True)[:3]


def _match_focus_line(match: dict[str, Any]) -> str:
    matchup = f"{match.get('home')} vs {match.get('away')}"
    if match.get("reportMissing"):
        return f"- {matchup}：报告待更新，先关注赛程和基础概率。"

    score = match.get("score_prediction") or {}
    totals = match.get("totals_prediction") or {}
    logic = str(match.get("logic") or match.get("summary") or "胜负分析待更新。").strip()
    extras: list[str] = []
    if score.get("primary"):
        extras.append(f"比分参考 {score['primary']}")
    if totals.get("displayPick") or totals.get("pick"):
        extras.append(f"进球数倾向 {totals.get('displayPick') or totals.get('pick')}")
    suffix = f"（{'，'.join(extras)}）" if extras else ""
    return f"- {matchup}：{logic}{suffix}"


def _focus_section_markdown(source: dict[str, Any]) -> str:
    lines = ["## 重点场次"]
    for match in _focus_matches(source):
        lines.append(_match_focus_line(match))
    return "\n".join(lines)


def _replace_markdown_section(markdown_text: str, heading: str, replacement: str) -> str:
    lines = markdown_text.splitlines()
    output: list[str] = []
    index = 0
    replaced = False
    while index < len(lines):
        if lines[index].strip() == heading:
            replacement_lines = replacement.splitlines()
            output.extend(replacement_lines)
            index += 1
            while index < len(lines) and not lines[index].startswith("## "):
                index += 1
            replaced = True
            continue
        output.append(lines[index])
        index += 1

    if replaced:
        return "\n".join(output).strip()

    insert_at = next((i for i, line in enumerate(output) if line.strip() == "## 冷门风险"), len(output))
    output[insert_at:insert_at] = ["", *replacement.splitlines(), ""]
    return "\n".join(output).strip()


def _stabilize_markdown_with_source(markdown_text: str, source: dict[str, Any]) -> str:
    return _replace_markdown_section(markdown_text, "## 重点场次", _focus_section_markdown(source))


def _fallback_markdown(source: dict[str, Any]) -> str:
    matches = list(source.get("matches") or [])
    upset_matches = sorted(matches, key=lambda item: float(item.get("upsetIndex") or 0), reverse=True)[:3]
    focus_matches = _focus_matches(source)

    lines = [
        f"# {source.get('label') or source.get('matchday')}世界杯前瞻",
        "",
        "今天的赛程可以从模型概率、比分参考和临场不确定性三个角度来观察。以下内容基于本站已发布的赛前报告整理。",
        "",
        "## 今日赛程",
    ]
    for match in matches:
        probs = match.get("probabilities") or {}
        lines.append(
            f"- {_format_time(match.get('kickoff'))} {match.get('home')} vs {match.get('away')}，"
            f"{match.get('group')}，{match.get('venue')}；"
            f"胜平负：{_format_pct(probs.get('home'))} / {_format_pct(probs.get('draw'))} / {_format_pct(probs.get('away'))}。"
        )

    lines.extend(["", "## 重点场次"])
    for match in focus_matches:
        lines.append(_match_focus_line(match))

    lines.extend(["", "## 冷门风险"])
    for match in upset_matches:
        lines.append(
            f"- {match.get('home')} vs {match.get('away')}：爆冷指数 {_format_pct(match.get('upsetIndex'))}。"
            f"{_list_text(match.get('risk_points')) or '主要风险来自临场阵容和比赛节奏变化。'}"
        )

    lines.extend(["", "## 比分与进球数参考"])
    for match in matches:
        score = match.get("score_prediction") or {}
        totals = match.get("totals_prediction") or {}
        if match.get("reportMissing"):
            lines.append(f"- {match.get('home')} vs {match.get('away')}：报告待更新。")
        else:
            lines.append(
                f"- {match.get('home')} vs {match.get('away')}：比分参考 {score.get('primary') or '--'}，"
                f"进球数倾向 {totals.get('displayPick') or totals.get('pick') or '--'}。"
            )

    lines.extend(
        [
            "",
            "## 赛前观察",
            "多场比赛仍需要结合官方首发、伤停信息和临场节奏再做最终判断。模型概率适合帮助梳理观赛重点，不适合被理解为确定性结论。",
            "",
            "## 风险提示",
            DISCLAIMER,
        ]
    )
    return "\n".join(lines)


async def _deepseek_daily_preview(source: dict[str, Any]) -> dict[str, str]:
    api_key = _env_value("DEEPSEEK_API_KEY")
    if not api_key:
        return _normalize_article_payload({}, source)

    model = _env_value("DEEPSEEK_MODEL", "deepseek-chat")
    effort = _env_value("DEEPSEEK_WECHAT_REASONING_EFFORT", _env_value("DEEPSEEK_REASONING_EFFORT", "medium"))
    thinking = _env_value("DEEPSEEK_WECHAT_THINKING", _env_value("DEEPSEEK_THINKING", "enabled"))
    payload = {
        "source": source,
        "required_structure": [
            "标题",
            "导语",
            "今日赛程",
            "重点场次",
            "冷门风险",
            "比分与进球数参考",
            "赛前观察",
            "风险提示",
        ],
        "forbidden_terms": list(FORBIDDEN_TERMS),
        "disclaimer": DISCLAIMER,
        "rules": [
            "只使用 source 中出现的事实，不新增球员、伤停、赔率、历史战绩。",
            "如果 reportMissing=true，只能写报告待更新，不得编造分析。",
            "重点场次必须优先使用每场的 logic 字段展开胜负分析，不要照抄 summary，也不要让多场比赛使用同一套泛化句式。",
            "如果 logic 信息有限，也要结合 probabilities、score_prediction、totals_prediction 和 risk_points 写出每场不同的判断。",
            "输出严格 JSON，字段为 title、digest、markdown。",
        ],
    }
    request_payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是世界杯公众号编辑，只做事实整理和公众号化表达，不提供投注建议，不创造输入外事实。",
            },
            {"role": "user", "content": _json_dump(payload)},
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
        "reasoning_effort": effort,
    }
    if thinking:
        request_payload["thinking"] = {"type": thinking}

    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=request_payload,
        )
    response.raise_for_status()
    data = json.loads(response.json()["choices"][0]["message"]["content"])
    return _normalize_article_payload(data, source)


def generate_daily_preview_article(source: dict[str, Any]) -> dict[str, str]:
    try:
        import anyio

        _log("wechat.deepseek", "start", "Calling DeepSeek for daily preview", source.get("matchday"))
        started_at = time.perf_counter()
        article = anyio.run(_deepseek_daily_preview, source)
        _log("wechat.deepseek", "success", f"Daily preview generated in {time.perf_counter() - started_at:.1f}s", source.get("matchday"))
        return article
    except Exception as exc:
        _log("wechat.deepseek", "warning", f"DeepSeek failed, using fallback: {type(exc).__name__}: {exc}", source.get("matchday"))
        return _normalize_article_payload({}, source)


def _allowed_fact_tokens(source: dict[str, Any]) -> set[str]:
    tokens = {str(source.get("matchday") or ""), str(source.get("label") or "")}
    for match in source.get("matches") or []:
        for key in ("home", "away", "group", "venue", "kickoff"):
            if match.get(key):
                tokens.add(str(match[key]))
        score = match.get("score_prediction") or {}
        if score.get("primary"):
            tokens.add(str(score["primary"]))
        for alt in score.get("alternatives") or []:
            tokens.add(str(alt))
        probs = match.get("probabilities") or {}
        for value in (probs.get("home"), probs.get("draw"), probs.get("away"), match.get("upsetIndex"), match.get("confidence")):
            tokens.add(_format_pct(value))
    return {token for token in tokens if token}


def fact_check_wechat_article(source: dict[str, Any], article: dict[str, Any]) -> dict[str, Any]:
    text = f"{article.get('title', '')}\n{article.get('digest', '')}\n{article.get('markdown', '')}"
    policy_text = text.replace(DISCLAIMER, "")
    issues: list[str] = []
    for term in FORBIDDEN_TERMS:
        if term in policy_text:
            issues.append(f"Forbidden term: {term}")
    if DISCLAIMER not in text:
        issues.append("Missing disclaimer")

    allowed = _allowed_fact_tokens(source)
    score_like = sorted(set(re.findall(r"\b\d{1,2}-\d{1,2}\b", text)))
    for score in score_like:
        left, right = score.split("-", 1)
        if int(left) > 9 or int(right) > 9:
            continue
        if score not in allowed:
            issues.append(f"Score not in source: {score}")

    percent_like = sorted(set(re.findall(r"\d+(?:\.\d+)?%", text)))
    for percent in percent_like:
        if percent not in allowed:
            issues.append(f"Percent not in source: {percent}")

    return {"status": "PASS" if not issues else "FAIL", "issues": issues}


def _poster_meta(source: dict[str, Any] | None) -> dict[str, str]:
    source = source or {}
    matches = list(source.get("matches") or [])
    first = matches[0] if matches else {}
    risk = sorted(matches, key=lambda item: float(item.get("upsetIndex") or 0), reverse=True)
    risk_match = risk[0] if risk else {}
    return {
        "label": str(source.get("label") or source.get("matchday") or "世界杯赛事日前瞻"),
        "match_count": str(len(matches)),
        "main_match": f"{first.get('home', '待定')} vs {first.get('away', '待定')}",
        "risk_match": f"{risk_match.get('home', '待定')} vs {risk_match.get('away', '待定')}",
        "risk_value": _format_pct(risk_match.get("upsetIndex")),
    }


def _render_html_poster(source: dict[str, Any] | None) -> str:
    meta = _poster_meta(source)
    return f"""
    <section style="margin:0 0 26px;overflow:hidden;border-radius:18px;padding:16px 16px 22px;background:#101518;color:#ffffff;">
      <section style="min-height:250px;border-radius:14px;background:#1f2937;background-image:linear-gradient(180deg,rgba(16,21,24,0.02) 0%,rgba(16,21,24,0.58) 100%),url('https://images.unsplash.com/photo-1577223625816-7546f13df25d?auto=format&fit=crop&w=1200&q=80');background-position:center;background-size:cover;"></section>
      <p style="margin:20px 0 10px;color:#f6c35b;font-size:13px;line-height:1.4;font-weight:900;">VIBE FOOTBALL</p>
      <h1 style="margin:0 0 12px;color:#ffffff;font-family:Georgia,'Times New Roman','Songti SC',SimSun,serif;font-size:31px;font-weight:900;line-height:1.16;">比赛日<br />重点观察</h1>
      <p style="margin:0;border-left:4px solid #f6c35b;padding-left:12px;color:#dbe5e2;font-size:15px;line-height:1.85;">不是只看胜负，而是看节奏、风险和关键场面。</p>
      <section style="margin-top:18px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.18);">
        <p style="margin:0 0 6px;font-size:13px;color:#dbe5e2;"><strong style="color:#ffffff;">{html.escape(meta["label"])}</strong> · 今日 {html.escape(meta["match_count"])} 场</p>
        <p style="margin:0;font-size:13px;color:#dbe5e2;">冷门观察：{html.escape(meta["risk_match"])} · {html.escape(meta["risk_value"])}</p>
      </section>
    </section>
    """


def _timeline_summary(match: dict[str, Any]) -> str:
    if match.get("reportMissing"):
        return "报告待更新，先关注赛程、基础概率和临场首发。"
    score = match.get("score_prediction") or {}
    logic = str(match.get("logic") or "").strip()
    if logic:
        first_sentence = re.split(r"[。！？!?]", logic, maxsplit=1)[0].strip()
        if first_sentence:
            return f"{first_sentence}，比分参考 {score.get('primary') or '--'}。"
    summary = str(match.get("summary") or "").strip()
    if summary:
        first_sentence = re.split(r"[。！？!?]", summary, maxsplit=1)[0].strip()
        if first_sentence:
            return f"{first_sentence}，比分参考 {score.get('primary') or '--'}。"
    probs = match.get("probabilities") or {}
    home = _format_pct(probs.get("home"))
    draw = _format_pct(probs.get("draw"))
    away = _format_pct(probs.get("away"))
    return f"胜平负概率 {home} / {draw} / {away}，比分参考 {score.get('primary') or '--'}。"


def _render_schedule_timeline(source: dict[str, Any] | None) -> str:
    matches = list((source or {}).get("matches") or [])
    if not matches:
        return ""
    rows = []
    for match in matches:
        rows.append(
            f"""
            <section style="display:block;margin:0 0 18px;border-bottom:1px solid #e7dfd2;padding:0 0 18px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">
                <tr>
                  <td width="78" valign="top" style="width:78px;color:#9a3412;font-family:Georgia,'Times New Roman',serif;font-size:20px;font-weight:900;line-height:1.2;">{html.escape(_format_time(match.get("kickoff")).split(" ")[-1])}</td>
                  <td valign="top">
                    <strong style="display:block;margin:0 0 6px;color:#1c1917;font-size:17px;font-weight:900;line-height:1.45;">{html.escape(str(match.get("home") or "待定"))} vs {html.escape(str(match.get("away") or "待定"))}</strong>
                    <p style="margin:0;color:#57534e;font-size:15px;line-height:1.85;">{html.escape(_timeline_summary(match))}</p>
                  </td>
                </tr>
              </table>
            </section>
            """
        )
    return f"""
    <section style="margin:0 0 26px;">
      <h2 style="margin:0 0 18px;color:#1c1917;font-family:Georgia,'Times New Roman','Songti SC',SimSun,serif;font-size:21px;font-weight:900;line-height:1.45;">今日赛程</h2>
      {''.join(rows)}
    </section>
    """


def _drop_title_and_schedule(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    output: list[str] = []
    skip = False
    for line in lines:
        if line.strip() == "## 今日赛程":
            skip = True
            continue
        if skip and line.startswith("## "):
            skip = False
        if not skip:
            output.append(line)
    return "\n".join(output).strip()


def render_wechat_html(markdown_text: str, source: dict[str, Any] | None = None) -> str:
    markdown_text = _drop_title_and_schedule(markdown_text)
    if markdown_lib:
        raw_html = markdown_lib.markdown(markdown_text, extensions=["extra", "sane_lists"])
    else:
        raw_html = "<p>" + html.escape(markdown_text).replace("\n\n", "</p><p>").replace("\n", "<br />") + "</p>"

    if bleach:
        cleaned = bleach.clean(
            raw_html,
            tags=["p", "br", "strong", "em", "ul", "ol", "li", "h1", "h2", "h3", "blockquote"],
            attributes={},
            strip=True,
        )
    else:
        cleaned = re.sub(r"<\s*script[^>]*>.*?<\s*/\s*script\s*>", "", raw_html, flags=re.I | re.S)
        cleaned = re.sub(r"\s+on\w+\s*=\s*(['\"]).*?\1", "", cleaned, flags=re.I | re.S)

    style_map = {
        "h1": 'style="font-family:Georgia,\'Times New Roman\',\'Songti SC\',SimSun,serif;font-size:23px;font-weight:900;line-height:1.45;margin:8px 0 18px;color:#1c1917;"',
        "h2": 'style="font-family:Georgia,\'Times New Roman\',\'Songti SC\',SimSun,serif;font-size:21px;font-weight:900;line-height:1.5;margin:30px 0 14px;color:#1c1917;"',
        "h3": 'style="font-family:Georgia,\'Times New Roman\',\'Songti SC\',SimSun,serif;font-size:18px;font-weight:900;line-height:1.5;margin:24px 0 10px;color:#1c1917;"',
        "p": 'style="font-size:15px;line-height:1.9;margin:0 0 14px;color:#57534e;"',
        "ul": 'style="list-style:none;padding-left:0;margin:0 0 18px;color:#57534e;"',
        "ol": 'style="padding-left:20px;margin:0 0 18px;color:#57534e;"',
        "li": 'style="font-size:15px;line-height:1.85;margin:0 0 12px;border-bottom:1px solid #e7dfd2;padding:0 0 12px;color:#57534e;"',
        "blockquote": 'style="border-left:4px solid #111827;padding:10px 12px;margin:16px 0;background:#f7f3ea;color:#374151;"',
        "strong": 'style="font-weight:900;color:#1c1917;"',
        "em": 'style="font-style:normal;color:#9a3412;font-weight:700;"',
    }
    styled = cleaned
    for tag, style in style_map.items():
        styled = re.sub(fr"<{tag}>", f"<{tag} {style}>", styled)
    styled = styled.replace(
        DISCLAIMER,
        f'<span style="display:block;padding:12px 14px;border-radius:10px;background:#fff7ed;border:1px solid #fed7aa;color:#9a3412;font-size:14px;line-height:1.75;">{DISCLAIMER}</span>',
    )
    poster = _render_html_poster(source)
    timeline = _render_schedule_timeline(source)
    return f"""
    <section style="max-width:677px;margin:0 auto;padding:16px 12px 22px;background:#f7efe0;color:#1c1917;">
      {poster}
      {timeline}
      <section style="padding:2px 2px 0;">
        {styled}
      </section>
    </section>
    """


def get_wechat_access_token() -> str:
    app_id = _env_value("WECHAT_APP_ID")
    app_secret = _env_value("WECHAT_APP_SECRET")
    if not app_id or not app_secret:
        raise RuntimeError("WECHAT_APP_ID and WECHAT_APP_SECRET are required")
    if _ACCESS_TOKEN_CACHE["token"] and float(_ACCESS_TOKEN_CACHE["expires_at"]) > time.time() + 120:
        return str(_ACCESS_TOKEN_CACHE["token"])
    response = httpx.get(
        "https://api.weixin.qq.com/cgi-bin/token",
        params={"grant_type": "client_credential", "appid": app_id, "secret": app_secret},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("errcode"):
        raise RuntimeError(f"WeChat token error: {data}")
    token = str(data["access_token"])
    _ACCESS_TOKEN_CACHE.update({"token": token, "expires_at": time.time() + int(data.get("expires_in", 7200))})
    return token


def push_wechat_draft(article: dict[str, Any]) -> dict[str, Any]:
    thumb_media_id = _env_value("WECHAT_DEFAULT_COVER_MEDIA_ID")
    if not thumb_media_id:
        raise RuntimeError("WECHAT_DEFAULT_COVER_MEDIA_ID is required")
    token = get_wechat_access_token()
    payload = {
        "articles": [
            {
                "title": article["title"],
                "author": _env_value("WECHAT_AUTHOR", "世界杯观赛助手"),
                "digest": article["digest"],
                "content": article["wechat_html"],
                "content_source_url": _env_value("WECHAT_ARTICLE_SOURCE_URL", "http://140.143.182.236/worldcup/"),
                "thumb_media_id": thumb_media_id,
                "need_open_comment": 0,
                "only_fans_can_comment": 0,
            }
        ]
    }
    response = httpx.post(
        "https://api.weixin.qq.com/cgi-bin/draft/add",
        params={"access_token": token},
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("errcode"):
        raise RuntimeError(f"WeChat draft error: {data}")
    return data


def next_wechat_article_version(matchday: str) -> int:
    _require_context()
    with _db() as conn:  # type: ignore[misc]
        row = conn.execute("select max(version) value from wechat_articles where article_type='daily_preview' and matchday=?", (matchday,)).fetchone()
    return int(row["value"] or 0) + 1


def save_daily_preview_article(source: dict[str, Any], article: dict[str, str], fact_check: dict[str, Any]) -> dict[str, Any]:
    version = next_wechat_article_version(str(source["matchday"]))
    article_id = f"wechat-daily-{source['matchday']}-v{version}"
    status = "generated" if fact_check.get("status") == "PASS" else "fact_failed"
    wechat_html = render_wechat_html(article["markdown"], source)
    with _db() as conn:  # type: ignore[misc]
        conn.execute(
            """
            insert into wechat_articles(
              id, article_type, matchday, version, status, title, digest, markdown, wechat_html,
              source_json, fact_check_json, wechat_media_id, error_message, created_at, pushed_at
            ) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                article_id,
                "daily_preview",
                source["matchday"],
                version,
                status,
                article["title"],
                article["digest"],
                article["markdown"],
                wechat_html,
                _json_dump(source),
                _json_dump(fact_check),
                None,
                None if status == "generated" else "; ".join(fact_check.get("issues") or []),
                _now(),
                None,
            ),
        )
    return {"id": article_id, "status": status, "title": article["title"], "digest": article["digest"], "version": version}


def article_row_to_dict(row: Any, include_body: bool = False) -> dict[str, Any]:
    item = {
        "id": row["id"],
        "articleType": row["article_type"],
        "matchday": row["matchday"],
        "version": row["version"],
        "status": row["status"],
        "title": row["title"],
        "digest": row["digest"],
        "wechatMediaId": row["wechat_media_id"],
        "errorMessage": row["error_message"],
        "createdAt": row["created_at"],
        "pushedAt": row["pushed_at"],
    }
    if include_body:
        item.update(
            {
                "markdown": row["markdown"],
                "wechatHtml": row["wechat_html"],
                "source": _json_load(row["source_json"], {}),
                "factCheck": _json_load(row["fact_check_json"], {}),
            }
        )
    return item
