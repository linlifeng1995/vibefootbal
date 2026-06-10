from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
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
DEFAULT_HERO_IMAGE_PREVIEW_URL = "/static/assets/wechat-article-hero-card.png"
DEFAULT_HERO_IMAGE_PATH = Path(__file__).resolve().parent.parent / "assets" / "wechat-article-hero-card.png"
TEAM_HEADLINE_NAMES = {
    "巴西": "桑巴军团",
    "德国": "德国战车",
    "法国": "高卢雄鸡",
    "西班牙": "斗牛士军团",
    "荷兰": "橙衣军团",
    "英格兰": "三狮军团",
    "葡萄牙": "五盾军团",
    "阿根廷": "潘帕斯雄鹰",
    "比利时": "欧洲红魔",
    "乌拉圭": "南美劲旅",
    "克罗地亚": "格子军团",
    "墨西哥": "东道主墨西哥",
    "瑞士": "瑞士军刀",
    "日本": "蓝武士",
    "韩国": "太极虎",
}

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
        "player_performance": content.get("player_performance"),
        "player_spotlight": content.get("player_spotlight"),
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


def _source_date_label(source: dict[str, Any]) -> str:
    label = str(source.get("label") or "").strip()
    if label:
        return label.replace("赛事", "").strip()
    matchday = str(source.get("matchday") or "").strip()
    try:
        dt = datetime.fromisoformat(matchday)
        return f"{dt.month}月{dt.day}日"
    except ValueError:
        return matchday or "今日"


def _match_pair(match: dict[str, Any]) -> str:
    home = str(match.get("home") or "待定").strip()
    away = str(match.get("away") or "待定").strip()
    return f"{home}vs{away}"


def _headline_team_name(team: str) -> str:
    return TEAM_HEADLINE_NAMES.get(team, team)


def _sorted_source_matches(source: dict[str, Any]) -> list[dict[str, Any]]:
    matches = [item for item in (source.get("matches") or []) if isinstance(item, dict)]
    return sorted(matches, key=lambda item: str(item.get("kickoff") or ""))


def _focus_teams(matches: list[dict[str, Any]]) -> list[str]:
    priority = (
        "巴西",
        "阿根廷",
        "法国",
        "英格兰",
        "德国",
        "西班牙",
        "葡萄牙",
        "荷兰",
        "比利时",
        "乌拉圭",
        "克罗地亚",
        "墨西哥",
        "美国",
        "瑞士",
        "韩国",
        "日本",
    )
    teams: list[str] = []
    for match in matches:
        teams.extend(str(match.get(key) or "").strip() for key in ("home", "away"))
    return [team for team in priority if team in teams]


def _match_for_team(matches: list[dict[str, Any]], team: str) -> dict[str, Any] | None:
    for match in matches:
        if team in {str(match.get("home") or "").strip(), str(match.get("away") or "").strip()}:
            return match
    return None


def _opponent_name(match: dict[str, Any], team: str) -> str:
    home = str(match.get("home") or "").strip()
    away = str(match.get("away") or "").strip()
    return away if home == team else home


def _focus_hook(match: dict[str, Any], team: str, index: int) -> str:
    opponent = _opponent_name(match, team)
    if opponent and opponent in TEAM_HEADLINE_NAMES:
        return f"{_headline_team_name(team)}碰{_headline_team_name(opponent)}"
    action = ("登场", "亮相", "出击")[index % 3]
    return f"{_headline_team_name(team)}{action}"


def _highest_risk_match(matches: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not matches:
        return None

    def risk_value(match: dict[str, Any]) -> float:
        try:
            return float(match.get("upsetIndex") or 0)
        except (TypeError, ValueError):
            return 0.0

    return max(matches, key=risk_value)


def _is_generic_article_title(title: str, source: dict[str, Any]) -> bool:
    compact = re.sub(r"\s+", "", title)
    if not compact:
        return True
    generic_terms = ("世界杯前瞻", "赛事前瞻", "今日前瞻", "每日前瞻", "比赛日前瞻")
    has_only_generic = any(term in compact for term in generic_terms) and "：" not in compact and ":" not in compact
    if has_only_generic:
        return True
    teams = {
        str(match.get(key) or "").strip()
        for match in source.get("matches") or []
        if isinstance(match, dict)
        for key in ("home", "away")
    }
    teams.discard("")
    if not any(team in title for team in teams):
        return True
    if any(term in title for term in ("首战", "打头阵", "打响")):
        return True

    risk = _highest_risk_match(_sorted_source_matches(source))
    if risk:
        try:
            risk_value = float(risk.get("upsetIndex") or 0)
        except (TypeError, ValueError):
            risk_value = 0.0
        risk_teams = {str(risk.get(key) or "").strip() for key in ("home", "away")}
        risk_teams.discard("")
        suspense_terms = ("最悬", "悬念", "冷门", "爆冷", "变数", "能否", "看点")
        if risk_value >= 60 and not any(team in title for team in risk_teams) and not any(term in title for term in suspense_terms):
            return True

    return False


def _build_article_title(source: dict[str, Any], raw_title: Any = "") -> str:
    title = str(raw_title or "").strip()
    if title and not _is_generic_article_title(title, source):
        return title[:64]

    matches = _sorted_source_matches(source)
    date_label = _source_date_label(source)
    if not matches:
        return f"{date_label}世界杯前瞻：赛程与观赛重点速览"[:64]

    risk = _highest_risk_match(matches)
    hooks: list[str] = []
    used_matches: set[int] = set()

    for team in _focus_teams(matches):
        match = _match_for_team(matches, team)
        if not match or match is risk or id(match) in used_matches:
            continue
        hooks.append(_focus_hook(match, team, len(hooks)))
        used_matches.add(id(match))
        if len(hooks) >= 2:
            break

    risk_hook = ""
    if risk:
        focus_risk_team = next((team for team in _focus_teams([risk]) if team), "")
        if focus_risk_team:
            opponent = _opponent_name(risk, focus_risk_team)
            risk_hook = f"{_headline_team_name(focus_risk_team)}碰{opponent}最悬" if opponent else f"{_headline_team_name(focus_risk_team)}最悬"
        else:
            risk_hook = f"{_match_pair(risk)}最悬"

    if risk_hook:
        hooks.append(risk_hook)

    if len(hooks) >= 3:
        return f"{date_label}世界杯前瞻：{hooks[0]}，{hooks[1]}，{hooks[2]}"[:64]
    if len(hooks) == 2:
        return f"{date_label}世界杯前瞻：{hooks[0]}，{hooks[1]}，悬念拉满"[:64]
    if len(hooks) == 1:
        return f"{date_label}世界杯前瞻：{hooks[0]}，今日{len(matches)}场看点拆解"[:64]

    return f"{date_label}世界杯前瞻：{_match_pair(matches[0])}领衔，今日{len(matches)}场看点拆解"[:64]


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
    title = _build_article_title(source, raw.get("title"))
    digest = str(raw.get("digest") or "基于赛程、模型概率、比分预测和赛前条件，整理今日观赛重点。").strip()[:120]
    return {"title": title, "digest": digest, "markdown": markdown}


def _format_pct(value: Any) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "--"


def _match_probability_text(match: dict[str, Any], bold: bool = False) -> str:
    probs = match.get("probabilities") or {}
    home = str(match.get("home") or "主队")
    away = str(match.get("away") or "客队")
    parts = [
        f"{home}胜 {_format_pct(probs.get('home'))}",
        f"平局 {_format_pct(probs.get('draw'))}",
        f"{away}胜 {_format_pct(probs.get('away'))}",
    ]
    text = " / ".join(parts)
    return f"**{text}**" if bold else text


def _bold_text(value: str, enabled: bool = True) -> str:
    return f"**{value}**" if enabled else value


def _strip_score_template_repetition(text: Any) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return ""
    patterns = [
        r"首选比分(?:参考|倾向)?\s*[0-9]+-[0-9]+[，,、；;。\s]*",
        r"备选(?:方向|比分)?(?:为|：|:)?\s*[0-9]+-[0-9]+(?:[、/]\s*[0-9]+-[0-9]+)*[，,、；;。\s]*",
        r"进球数倾向(?:更接近|为)?\s*进球偏[多少][，,、；;。\s]*",
        r"本场进球数倾向(?:更接近|为)?\s*进球偏[多少][，,、；;。\s]*",
    ]
    for pattern in patterns:
        value = re.sub(pattern, "", value)
    return value.strip(" ，,。；;")


def _format_time(value: Any) -> str:
    if not value:
        return "时间待定"
    try:
        dt = datetime.fromisoformat(str(value))
        return dt.strftime("%m-%d %H:%M")
    except ValueError:
        return str(value)


def _format_match_datetime(value: Any) -> str:
    if not value:
        return "时间待定"
    try:
        dt = datetime.fromisoformat(str(value))
        return f"{dt.month}月{dt.day}日 {dt:%H:%M}"
    except ValueError:
        return str(value)


def _list_text(value: Any) -> str:
    def clean_item(item: Any) -> str:
        return str(item or "").strip().rstrip("。；;")

    if isinstance(value, list):
        return "；".join(clean_item(item) for item in value if clean_item(item))
    if isinstance(value, dict):
        return "；".join(clean_item(item) for item in value.values() if clean_item(item))
    return str(value or "")


TEMPLATE_RISK_FRAGMENTS = (
    "本场需要重点观察",
    "草皮、气温和旅途恢复会影响冲刺质量",
    "赛地适应、旅行距离和恢复周期会影响下半场质量",
    "模型只能把它们计入不确定性区间",
)


def _list_items(value: Any) -> list[str]:
    if isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        items = list(value.values())
    elif value:
        items = [value]
    else:
        items = []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip().rstrip("。；;")
        if not text or any(fragment in text for fragment in TEMPLATE_RISK_FRAGMENTS):
            continue
        signature = re.sub(r"[，。；：、\s\dA-Za-z%-]+", "", text)[:40]
        if signature in seen:
            continue
        seen.add(signature)
        cleaned.append(text)
    return cleaned


def _match_player_text(match: dict[str, Any]) -> str:
    spotlight = []
    for item in match.get("player_spotlight") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        impact = _clip_text(item.get("impact"), 92).rstrip("。；; ")
        if name and impact:
            spotlight.append(f"{name}：{impact}")
        if len(spotlight) >= 2:
            break
    if spotlight:
        return "；".join(spotlight).rstrip("。；; ") + "。"
    performance = "；".join(_list_items(match.get("player_performance"))[:2])
    return _clip_text(performance, 220) if performance else "关键球员表现待官方首发和临场状态确认后更新。"


def _clip_text(value: Any, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    sentences = re.split(r"(?<=[。！？!?])", text)
    output = ""
    for sentence in sentences:
        if len(output) + len(sentence) > limit:
            break
        output += sentence
    return output.strip() or f"{text[:limit].rstrip()}..."


def _match_logic_text(match: dict[str, Any]) -> str:
    if match.get("reportMissing"):
        return "报告待更新，先关注赛程、基础概率和临场首发。"
    logic = _clip_text(match.get("logic") or match.get("summary") or "胜负分析待更新。", 230)
    return f"胜平负概率：{_match_probability_text(match, bold=True)}。{logic}"


def _match_score_text(match: dict[str, Any]) -> str:
    if match.get("reportMissing"):
        return "报告待更新，比分预测暂不展开。"

    score = match.get("score_prediction") or {}
    totals = match.get("totals_prediction") or {}
    primary = score.get("primary") or "--"
    alternatives = " / ".join(str(item) for item in score.get("alternatives") or [] if item)
    total_pick = totals.get("displayPick") or totals.get("pick") or "--"
    score_analysis = _clip_text(_strip_score_template_repetition(score.get("analysis")), 160)
    totals_analysis = _clip_text(_strip_score_template_repetition(totals.get("analysis")), 130)
    parts = [f"首选比分 {_bold_text(primary)}"]
    if alternatives:
        parts.append(f"备选 {_bold_text(alternatives)}")
    if total_pick and total_pick != "--":
        parts.append(f"进球数倾向 {_bold_text(total_pick)}")
    headline = "，".join(parts) + "。"
    detail_parts = []
    if score_analysis:
        detail_parts.append(score_analysis.rstrip("。；; "))
    if totals_analysis:
        detail_parts.append(totals_analysis.rstrip("。；; "))
    detail_text = "。".join(part for part in detail_parts if part)
    if detail_text:
        detail_text = _clip_text(detail_text, 260).rstrip("。；; ") + "。"
    return headline + detail_text


def _match_risk_text(match: dict[str, Any]) -> str:
    risk_points = "；".join(_list_items(match.get("risk_points"))[:2])
    risk_prefix = f"爆冷指数 {_format_pct(match.get('upsetIndex'))}"
    return f"{risk_prefix}。{_clip_text(risk_points, 180) if risk_points else '主要风险来自临场阵容、比赛节奏和关键失误。'}"


def _match_preview_section_markdown(source: dict[str, Any]) -> str:
    lines = ["## 赛事前瞻"]
    for match in source.get("matches") or []:
        lines.extend(
            [
                "",
                f"### {_format_time(match.get('kickoff')).split(' ')[-1]} {match.get('home')} vs {match.get('away')}",
                f"- 胜负分析：{_match_logic_text(match)}",
                f"- 比分预测：{_match_score_text(match)}",
                f"- 关键球员表现：{_match_player_text(match)}",
                f"- 冷门风险：{_match_risk_text(match)}",
            ]
        )
    return "\n".join(lines)


def _extract_intro(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    intro: list[str] = []
    for line in lines:
        if line.startswith("## "):
            break
        if line.strip():
            intro.append(line.strip())
    return "\n\n".join(intro).strip()


def _extract_section(markdown_text: str, heading: str) -> str:
    lines = markdown_text.splitlines()
    output: list[str] = []
    collecting = False
    for line in lines:
        if line.strip() == heading:
            collecting = True
            continue
        if collecting and line.startswith("## "):
            break
        if collecting:
            output.append(line)
    return "\n".join(output).strip()


def _stabilize_markdown_with_source(markdown_text: str, source: dict[str, Any]) -> str:
    title = f"# {source.get('label') or source.get('matchday')}世界杯前瞻"
    first_line = next((line.strip() for line in markdown_text.splitlines() if line.startswith("# ")), "")
    if first_line:
        title = first_line

    intro = _extract_intro(markdown_text) or "今天的比赛从模型分数、比分预测和冷门风险三个角度来观察。以下内容基于本站已发布的赛前报告整理。"
    observation = _extract_section(markdown_text, "## 赛前观察") or "多场比赛仍需要结合官方首发、伤停信息和临场节奏再做最终判断。模型概率适合帮助梳理观赛重点，不适合被理解为确定性结论。"
    return "\n\n".join(
        [
            title,
            intro,
            _match_preview_section_markdown(source),
            "## 赛前观察\n" + observation,
            "## 风险提示\n" + DISCLAIMER,
        ]
    )


def _fallback_markdown(source: dict[str, Any]) -> str:
    lines = [
        f"# {source.get('label') or source.get('matchday')}世界杯前瞻",
        "",
        "今天的比赛从模型分数、比分预测和冷门风险三个角度来观察。以下内容基于本站已发布的赛前报告整理。",
        "",
        _match_preview_section_markdown(source),
        "",
        "## 赛前观察",
        "多场比赛仍需要结合官方首发、伤停信息和临场节奏再做最终判断。模型概率适合帮助梳理观赛重点，不适合被理解为确定性结论。",
        "",
        "## 风险提示",
        DISCLAIMER,
    ]
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
            "赛事前瞻",
            "赛前观察",
            "风险提示",
        ],
        "forbidden_terms": list(FORBIDDEN_TERMS),
        "disclaimer": DISCLAIMER,
        "rules": [
            "只使用 source 中出现的事实，不新增球员、伤停、赔率、历史战绩。",
            "如果 reportMissing=true，只能写报告待更新，不得编造分析。",
            "title 必须包含日期和当天至少一场具体比赛或球队，优先突出高关注球队和最高冷门风险比赛，不要围绕“首战、打头阵、比赛日开始”写标题。",
            "title 控制在 26-42 个中文字符左右，可以使用冒号；可使用已知球队修饰词，如德国战车、桑巴军团、高卢雄鸡、斗牛士军团、橙衣军团、三狮军团、蓝武士、太极虎，但不能编造输入外事实或夸大确定性。",
            "赛事前瞻必须按比赛逐场展开，每场固定包含胜负分析、比分预测、冷门风险三项，不要先罗列赛程再单独写重点场次。",
            "胜负分析必须优先使用每场的 logic 字段；比分预测必须使用 score_prediction 和 totals_prediction，并尽量展开其中的 analysis 内容；冷门风险只使用 upsetIndex 和 risk_points。",
            "同一天多场比赛不能重复使用相同句架；禁止批量复用“需要重点观察”“草皮、气温和旅途恢复”“赛地适应、旅行距离和恢复周期”等模板化表达。",
            "如果 source 中多场比赛的某些风险点或赛前条件高度相似，需要合并、改写或舍弃，只保留对该场比赛最具体的内容。",
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


def _hero_image_preview_url() -> str:
    return _env_value("WECHAT_ARTICLE_HERO_IMAGE_PREVIEW_URL", DEFAULT_HERO_IMAGE_PREVIEW_URL)


def _hero_image_path() -> Path:
    configured = _env_value("WECHAT_ARTICLE_HERO_IMAGE_PATH", "")
    if not configured:
        return DEFAULT_HERO_IMAGE_PATH
    path = Path(configured)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    return path


def _render_html_poster(source: dict[str, Any] | None) -> str:
    hero_url = html.escape(_hero_image_preview_url(), quote=True)
    return f'<section style="margin:0 0 0;padding:0;"><img src="{hero_url}" alt="Vibe Football 比赛日重点观察" style="display:block;width:100%;max-width:100%;height:auto;margin:0;border:0;" /></section>'


def _render_preview_item(label: str, value: str, color: str) -> str:
    return f'<section style="margin:7px 0 0;padding:8px 10px 9px;border:1px solid #d8c99a;border-radius:10px;"><p style="margin:0 0 2px;color:{color};font-size:14px;line-height:1.18;font-weight:900;">{html.escape(label)}</p><p style="margin:0;color:#303437;font-size:14px;line-height:1.58;">{html.escape(value)}</p></section>'


def _inline_markdown_to_wechat_html(value: str) -> str:
    escaped = html.escape(str(value or ""))
    return re.sub(r"\*\*(.+?)\*\*", r'<strong style="font-weight:900;color:#111417;">\1</strong>', escaped)


def _render_preview_item_rich(label: str, value: str, color: str) -> str:
    return f'<section style="margin:7px 0 0;padding:8px 10px 9px;border:1px solid #d8c99a;border-radius:10px;"><p style="margin:0 0 2px;color:{color};font-size:14px;line-height:1.18;font-weight:900;">{html.escape(label)}</p><p style="margin:0;color:#303437;font-size:14px;line-height:1.58;">{_inline_markdown_to_wechat_html(value)}</p></section>'


def _render_match_previews(source: dict[str, Any] | None) -> str:
    matches = list((source or {}).get("matches") or [])
    if not matches:
        return ""
    rows = []
    for match in matches:
        group = str(match.get("group") or "").strip()
        venue = str(match.get("venue") or "").strip()
        meta = " · ".join(item for item in (group, venue) if item)
        time_label = html.escape(_format_match_datetime(match.get("kickoff")))
        title = f"{html.escape(str(match.get('home') or '待定'))} vs {html.escape(str(match.get('away') or '待定'))}"
        rows.append(
            f'<section style="display:block;margin:0 0 14px;padding:0;background:#ffffff;"><section style="margin:0 0 6px;padding:8px 0 3px;"><p style="margin:0 0 1px;white-space:nowrap;color:#111417;font-size:17px;line-height:1.2;font-weight:900;"><span style="color:#c08a24;font-size:19px;font-weight:900;">{time_label}</span><span style="color:#111417;font-size:17px;font-weight:900;">&nbsp;&nbsp;{title}</span></p><p style="margin:0 0 0 108px;white-space:nowrap;color:#4d5356;font-size:13px;line-height:1.3;">{html.escape(meta)}</p></section>{_render_preview_item_rich("胜负分析", _match_logic_text(match), "#c08a24")}{_render_preview_item_rich("比分预测", _match_score_text(match), "#c08a24")}{_render_preview_item("关键球员表现", _match_player_text(match), "#c08a24")}{_render_preview_item("冷门风险", _match_risk_text(match), "#c08a24")}</section>'
        )
    return f'<section style="margin:0 0 18px;padding:0 20px 0;color:#111417;">{"".join(rows)}</section>'


def _drop_title_and_schedule(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    output: list[str] = []
    skip = False
    for line in lines:
        if line.strip() in {"## 今日赛程", "## 赛事前瞻", "## 重点场次", "## 冷门风险", "## 比分预测", "## 比分与进球数参考"}:
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
        "h1": 'style="font-size:22px;font-weight:900;line-height:1.45;margin:8px 0 14px;color:#111417;"',
        "h2": 'style="font-size:19px;font-weight:900;line-height:1.45;margin:24px 0 10px;color:#111417;"',
        "h3": 'style="font-size:17px;font-weight:900;line-height:1.45;margin:20px 0 8px;color:#111417;"',
        "p": 'style="font-size:15px;line-height:1.82;margin:0 0 12px;color:#303437;"',
        "ul": 'style="list-style:none;padding-left:0;margin:0 0 16px;color:#303437;"',
        "ol": 'style="padding-left:20px;margin:0 0 16px;color:#303437;"',
        "li": 'style="font-size:15px;line-height:1.75;margin:0 0 10px;border-bottom:1px solid #eee5d2;padding:0 0 10px;color:#303437;"',
        "blockquote": 'style="border-left:4px solid #c08a24;padding:9px 11px;margin:14px 0;background:#fffaf0;color:#303437;"',
        "strong": 'style="font-weight:900;color:#111417;"',
        "em": 'style="font-style:normal;color:#c08a24;font-weight:700;"',
    }
    styled = cleaned
    for tag, style in style_map.items():
        styled = re.sub(fr"<{tag}>", f"<{tag} {style}>", styled)
    styled = styled.replace(
        DISCLAIMER,
        f'<span style="display:block;padding:9px 11px;border-radius:8px;border:1px solid #eadcae;color:#6d5b21;font-size:13px;line-height:1.65;">{DISCLAIMER}</span>',
    )
    poster = _render_html_poster(source)
    previews = _render_match_previews(source)
    return f'<section style="max-width:677px;margin:0 auto;padding:0 0 22px;color:#111417;">{poster}{previews}<section style="padding:0 20px;">{styled}</section></section>'


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


def upload_wechat_content_image(access_token: str) -> str:
    image_path = _hero_image_path()
    if not image_path.exists():
        raise RuntimeError(f"WeChat hero image not found: {image_path}")
    mime_type = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    with image_path.open("rb") as image_file:
        response = httpx.post(
            "https://api.weixin.qq.com/cgi-bin/media/uploadimg",
            params={"access_token": access_token},
            files={"media": (image_path.name, image_file, mime_type)},
            timeout=30,
        )
    response.raise_for_status()
    data = response.json()
    if data.get("errcode"):
        raise RuntimeError(f"WeChat content image upload error: {data}")
    url = str(data.get("url") or "")
    if not url:
        raise RuntimeError(f"WeChat content image upload did not return url: {data}")
    return url


def prepare_wechat_draft_content(content: str, access_token: str) -> str:
    preview_url = _hero_image_preview_url()
    if preview_url not in content:
        return content
    wechat_image_url = upload_wechat_content_image(access_token)
    return content.replace(preview_url, wechat_image_url).replace(html.escape(preview_url, quote=True), html.escape(wechat_image_url, quote=True))


def push_wechat_draft(article: dict[str, Any]) -> dict[str, Any]:
    thumb_media_id = _env_value("WECHAT_DEFAULT_COVER_MEDIA_ID")
    if not thumb_media_id:
        raise RuntimeError("WECHAT_DEFAULT_COVER_MEDIA_ID is required")
    token = get_wechat_access_token()
    content = prepare_wechat_draft_content(article["wechat_html"], token)
    payload = {
        "articles": [
            {
                "title": article["title"],
                "author": _env_value("WECHAT_AUTHOR", "世界杯观赛助手"),
                "digest": article["digest"],
                "content": content,
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


def prune_old_daily_preview_articles(matchday: str, keep_id: str) -> int:
    _require_context()
    with _db() as conn:  # type: ignore[misc]
        cursor = conn.execute(
            """
            delete from wechat_articles
            where article_type='daily_preview'
              and matchday=?
              and id<>?
            """,
            (matchday, keep_id),
        )
        return int(cursor.rowcount or 0)


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
    pruned = prune_old_daily_preview_articles(str(source["matchday"]), article_id)
    if pruned:
        _log("wechat.article", "success", f"Pruned {pruned} older daily preview article(s)", str(source["matchday"]))
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
