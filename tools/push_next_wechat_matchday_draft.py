from __future__ import annotations

import base64
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from dotenv import dotenv_values

CN_TZ = ZoneInfo("Asia/Shanghai")
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.main import TEAM_PLAYER_PROFILES, default_article_matchday, query_public_matches, real_star_names

OUTPUT_DIR = ROOT / "automation_outputs" / "wechat_drafts"
DB_PATH = ROOT / "data" / "worldcup.db"
DEFAULT_RAW_DRAFT_ENDPOINT = "http://140.143.182.236/worldcup/api/admin/wechat/raw-draft"
DEFAULT_RAW_IMAGE_ENDPOINT = "http://140.143.182.236/worldcup/api/admin/wechat/raw-image"
DISCLAIMER = "本文为赛事信息与观赛视角整理，不提供比赛结果判断。赛程、排名与阵容估值请以官方及发布前公开页面为准。"

FORBIDDEN_TERMS = (
    "比分预测",
    "胜平负",
    "概率",
    "冷门指数",
    "爆冷",
    "投注",
    "竞猜",
    "赔率",
    "盘口",
    "下注",
    "命中率",
    "收益",
    "稳赢",
    "必红",
)

# Supplemental public facts are a cache, not article templates. If a newer local or remote fact
# source is configured, it is merged over this cache at runtime.
SUPPLEMENTAL_TEAM_FACTS: dict[str, dict[str, str]] = {
    "墨西哥": {
        "fifa_rank": "第15位",
        "market_value_million": "191.85",
        "world_cup_record": "第18次参赛，历史最好成绩是1970年和1986年的八强",
    },
    "南非": {
        "fifa_rank": "第60位",
        "market_value_million": "49.25",
        "world_cup_record": "第4次参赛，前三次都停在小组赛，距离上次亮相已经隔了16年",
    },
    "韩国": {
        "fifa_rank": "第25位",
        "market_value_million": "139.05",
        "world_cup_record": "第12次参赛，2002年在本土拿到过四强",
    },
    "捷克": {
        "fifa_rank": "第41位",
        "market_value_million": "188.18",
        "world_cup_record": "独立后第2次参加世界杯；如果把捷克斯洛伐克时代算进去，1962年拿到过亚军",
    },
    "加拿大": {
        "fifa_rank": "第30位",
        "market_value_million": "198.65",
        "world_cup_record": "第3次参加世界杯，前两次都停在小组赛",
    },
    "波黑": {
        "fifa_rank": "第65位",
        "market_value_million": "151.60",
        "world_cup_record": "第2次参加世界杯，上一次亮相是在2014年",
    },
    "美国": {
        "fifa_rank": "第16位",
        "market_value_million": "385.65",
        "world_cup_record": "第12次参加世界杯，最好成绩可追溯到1930年的四强",
    },
    "巴拉圭": {
        "fifa_rank": "第48位",
        "market_value_million": "134.70",
        "world_cup_record": "第9次参加世界杯，2010年曾进入八强",
    },
}

TEAM_PRIORITY = (
    "巴西",
    "德国",
    "荷兰",
    "日本",
    "瑞士",
    "土耳其",
    "澳大利亚",
    "摩洛哥",
    "瑞典",
    "美国",
    "加拿大",
    "墨西哥",
    "韩国",
)


def require_env(values: dict[str, str | None], key: str) -> str:
    value = (values.get(key) or "").strip()
    if not value:
        raise RuntimeError(f"缺少必要环境变量: {key}")
    return value


def next_matchday() -> dict[str, Any]:
    rows = query_public_matches()
    group = default_article_matchday(rows, datetime.now(CN_TZ))
    if not group:
        raise RuntimeError("从今天起没有找到下一个有比赛的自然日")
    return group


def load_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def normalize_fact_mapping(raw: Any) -> dict[str, dict[str, str]]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, str]] = {}
    for team, value in raw.items():
        if not isinstance(value, dict):
            continue
        cleaned = {str(k): str(v).strip() for k, v in value.items() if str(v).strip()}
        if cleaned:
            normalized[str(team).strip()] = cleaned
    return normalized


def load_team_facts(values: dict[str, str | None]) -> dict[str, dict[str, str]]:
    facts = dict(SUPPLEMENTAL_TEAM_FACTS)
    local_path = (values.get("WECHAT_TEAM_FACTS_JSON") or "").strip()
    if local_path:
        facts.update(normalize_fact_mapping(load_json_file(Path(local_path).expanduser())))

    endpoint = (values.get("WECHAT_TEAM_FACTS_ENDPOINT") or "").strip()
    if endpoint:
        try:
            response = httpx.get(endpoint, timeout=30)
            response.raise_for_status()
            facts.update(normalize_fact_mapping(response.json()))
        except Exception:
            # External facts are useful, not required. The article records missing public data
            # instead of inventing it.
            pass
    return facts


def format_cn_date(matchday: str) -> str:
    dt = datetime.fromisoformat(matchday)
    return f"{dt.month}月{dt.day}日"


def match_label(match: dict[str, Any]) -> str:
    return f"{match['home']} vs {match['away']}"


def compact_match_label(match: dict[str, Any]) -> str:
    return f"{match['home']}vs{match['away']}"


def kickoff_dt(match: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(match["kickoff"])).astimezone(CN_TZ)


def kickoff_text(match: dict[str, Any]) -> str:
    return f"北京时间 {kickoff_dt(match):%H:%M}"


def compact_html(value: str) -> str:
    value = re.sub(r">\s+<", "><", value)
    value = re.sub(r"\s{2,}", " ", value)
    return value.strip()


def small_title(text: str, color: str) -> str:
    return (
        f'<h3 style="margin:26px 0 10px;color:{color};font-size:18px;line-height:1.45;'
        f'font-weight:900;">{text}</h3>'
    )


def focus_title(text: str, color: str, teams: list[str]) -> str:
    if any(team and team in text for team in teams):
        raise RuntimeError(f"观赛点小标题不应重复球队名: {text}")
    return small_title(text, color)


def safe_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    if any(term in text for term in FORBIDDEN_TERMS):
        return ""
    return text


def market_value_text(fact: dict[str, str] | None) -> str:
    if not fact or not fact.get("market_value_million"):
        return ""
    value = float(fact["market_value_million"]) / 100
    return f"约{value:.2f}亿欧元"


def open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def jload(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def load_db_context(match_id: str) -> dict[str, Any]:
    with open_db() as conn:
        row = conn.execute(
            """
            select m.id, m.kickoff, m.group_name, m.venue, m.tags_json,
                   ht.id home_id, ht.name home, ht.code home_code, ht.rating home_rating,
                   at.id away_id, at.name away, at.code away_code, at.rating away_rating,
                   hs.form_score home_form, hs.attack_score home_attack, hs.defense_score home_defense,
                   hs.injuries_json home_injuries_json,
                   aw.form_score away_form, aw.attack_score away_attack, aw.defense_score away_defense,
                   aw.injuries_json away_injuries_json
            from matches m
            join teams ht on ht.id=m.home_team_id
            join teams at on at.id=m.away_team_id
            left join team_stats hs on hs.team_id=m.home_team_id
            left join team_stats aw on aw.team_id=m.away_team_id
            where m.id=?
            """,
            (match_id,),
        ).fetchone()
        if not row:
            raise RuntimeError(f"找不到比赛: {match_id}")

        research = conn.execute(
            """
            select title, snippet, fetched_at
            from research_sources
            where match_id=?
            order by fetched_at desc, id desc
            limit 8
            """,
            (match_id,),
        ).fetchall()
        report = conn.execute(
            """
            select content_json
            from reports
            where match_id=? and status='published'
            order by version desc
            limit 1
            """,
            (match_id,),
        ).fetchone()

    data = dict(row)
    data["tags"] = jload(data.pop("tags_json", None), [])
    data["home_injuries"] = jload(data.pop("home_injuries_json", None), [])
    data["away_injuries"] = jload(data.pop("away_injuries_json", None), [])
    data["research"] = [dict(item) for item in research]
    data["report_content"] = jload(report["content_json"], {}) if report else {}
    data["home_profile"] = TEAM_PLAYER_PROFILES.get(data["home_code"], {})
    data["away_profile"] = TEAM_PLAYER_PROFILES.get(data["away_code"], {})
    return data


def enrich_matches(matches: list[dict[str, Any]], team_facts: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for match in matches:
        item = dict(match)
        item["db"] = load_db_context(str(match["id"]))
        item["home_fact"] = team_facts.get(str(match["home"]))
        item["away_fact"] = team_facts.get(str(match["away"]))
        enriched.append(item)
    return enriched


def schedule_rows(matches: list[dict[str, Any]]) -> str:
    rows = []
    for match in matches:
        rows.append(
            (
                '<div style="padding:12px 0;border-bottom:1px solid #e8dfd0;">'
                f'<div style="font-size:15px;line-height:1.7;color:#111417;font-weight:700;">{kickoff_text(match)} · {match["home"]} vs {match["away"]}</div>'
                f'<div style="font-size:13px;line-height:1.65;color:#666c69;">{match["group"]} · {match["venue"]}</div>'
                "</div>"
            )
        )
    return "".join(rows)


def focus_teams(matches: list[dict[str, Any]]) -> list[str]:
    teams = [str(match["home"]) for match in matches] + [str(match["away"]) for match in matches]
    result = [team for team in TEAM_PRIORITY if team in teams]
    for team in teams:
        if team not in result:
            result.append(team)
    return result[:2]


def day_core_angle(matches: list[dict[str, Any]]) -> str:
    teams = [str(match["home"]) for match in matches] + [str(match["away"]) for match in matches]
    if "加拿大" in teams and "美国" in teams:
        return "北美双主场，先看转换和第二点"
    if "巴西" in teams and "摩洛哥" in teams:
        return "巴西摩洛哥同场，边路和中场最抢眼"
    axes = [lead_axis(match) for match in matches]
    joined_labels = "、".join(match_label(match) for match in matches[:2])
    if any("边路" in axis for axis in axes):
        return "边路速度和转换第一脚先看清"
    if any("定位球" in axis or "二点球" in axis for axis in axes):
        return "二点球和定位球会先出味道"
    if len(matches) >= 4:
        return "多组同开，先抓中场和转换"
    if joined_labels:
        return f"{joined_labels}，先抓关键区域"
    return "先抓关键区域和比赛节奏"


def team_heat_score(team: str) -> int:
    try:
        return (len(TEAM_PRIORITY) - TEAM_PRIORITY.index(team)) * 100
    except ValueError:
        return 0


def match_heat_score(match: dict[str, Any]) -> float:
    home = str(match["home"])
    away = str(match["away"])
    score = team_heat_score(home) + team_heat_score(away)
    if team_heat_score(home) and team_heat_score(away):
        score += 150
    db = match.get("db") or {}
    score += float(db.get("home_rating") or 0) / 10
    score += float(db.get("away_rating") or 0) / 10
    return score


def core_match(matches: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not matches:
        return None
    return max(matches, key=match_heat_score)


def article_title(matchday: str, matches: list[dict[str, Any]]) -> str:
    date_label = format_cn_date(matchday)
    featured = core_match(matches)
    prefix = f"{compact_match_label(featured)}领衔，" if featured else ""
    return f"{date_label}世界杯赛前解读：{prefix}{day_core_angle(matches)}"


def article_digest(matches: list[dict[str, Any]]) -> str:
    labels = "、".join(match_label(match) for match in matches[:4])
    suffix = "。" if len(matches) <= 4 else "等比赛。"
    return f"今天按比赛逐场拆开看：{labels}{suffix}不做参数卡，先抓每场的节奏、关键区域和普通观众最容易看懂的细节。"


def poster_copy(matchday: str, matches: list[dict[str, Any]] | None = None) -> tuple[str, str, str]:
    date_line = f"北京时间 {format_cn_date(matchday)}"
    if matches:
        featured = core_match(matches)
        headline = compact_match_label(featured) if featured else "核心看点"
        return date_line, headline, day_core_angle(matches)
    return date_line, "核心看点", "先看关键区域"


def fact_sentence(team: str, fact: dict[str, str] | None, db: dict[str, Any], prefix: str) -> str:
    rating = int(float(db.get(f"{prefix}_rating") or 0))
    form = float(db.get(f"{prefix}_form") or 0)
    attack = float(db.get(f"{prefix}_attack") or 0)
    defense = float(db.get(f"{prefix}_defense") or 0)
    pieces = []
    if fact:
        rank = fact.get("fifa_rank")
        value = market_value_text(fact)
        record = fact.get("world_cup_record")
        if rank:
            pieces.append(f"FIFA排名{rank}")
        if value:
            pieces.append(f"阵容估值{value}")
        if record:
            pieces.append(record)
    else:
        pieces.append("FIFA排名与阵容估值发布前按同一公开页面校准")
    pieces.append(f"基础强度评分{rating}，近期/进攻/防守评分约为{form:.1f}/{attack:.1f}/{defense:.1f}")
    return f"{team}：" + "，".join(pieces)


def profile_line(team: str, profile: dict[str, Any]) -> str:
    strength = safe_text(profile.get("strength"))
    detail = safe_text(profile.get("detail"))
    stars = real_star_names(profile)
    if strength and stars:
        return f"{team}的主要看点在{strength}，{ '、'.join(stars[:3]) }这些名字不用背满，先看他们能不能把各自区域串起来。"
    if detail:
        return detail
    return f"{team}这边先看整体结构：后场第一脚、边路宽度和中场二点球，往往比单个名字更早决定观感。"


def research_notes(match: dict[str, Any]) -> list[str]:
    notes = []
    for item in match["db"].get("research") or []:
        text = safe_text(item.get("snippet"))
        if text and "暂无" not in text:
            notes.append(text)
    return notes[:2]


def report_matchups(match: dict[str, Any]) -> list[str]:
    content = match["db"].get("report_content") or {}
    raw = content.get("key_matchups") or []
    if not isinstance(raw, list):
        return []
    return [text for text in (safe_text(item) for item in raw) if text][:2]


def lead_axis(match: dict[str, Any]) -> str:
    db = match["db"]
    home_attack = float(db.get("home_attack") or 0)
    away_attack = float(db.get("away_attack") or 0)
    home_defense = float(db.get("home_defense") or 0)
    away_defense = float(db.get("away_defense") or 0)
    if max(home_attack, away_attack) >= 7.2:
        return "边路速度和禁区前沿接应"
    if min(home_defense, away_defense) >= 6.4:
        return "中路缝隙和定位球落点"
    if abs(home_attack - away_attack) >= 1.0:
        return "转换第一脚和回防距离"
    return "二点球、肋部接应和节奏耐心"


def secondary_axis(match: dict[str, Any]) -> str:
    db = match["db"]
    home_form = float(db.get("home_form") or 0)
    away_form = float(db.get("away_form") or 0)
    venue = str(match.get("venue") or "")
    kickoff = kickoff_dt(match).strftime("%H:%M")
    if abs(home_form - away_form) >= 1.4:
        return f"{kickoff}开场，先看状态能不能落地"
    if "体育馆" in str(match.get("venue")):
        return "室内场地里，球速和回追会更显眼"
    if "多伦多" in venue:
        return "主场音量起来后，回抢能不能接住"
    if "洛杉矶" in venue:
        return "速度拉满之后，第二脚别断"
    if "纽约" in venue or "新泽西" in venue:
        return "大场面里，边路身后保护更关键"
    if "波士顿" in venue:
        return "连续争抢后，弧顶别漏第二点"
    if "温哥华" in venue:
        return "身体对抗之后，谁能把球踩住"
    return f"{kickoff}这场，回抢五秒和第一接球人"


def match_headline(match: dict[str, Any], axis: str) -> str:
    home = str(match["home"])
    away = str(match["away"])
    if "边路" in axis:
        angle = "边路一开，身后保护就要跟上"
    elif "定位球" in axis:
        angle = "禁区前沿和落点更值得盯"
    elif "转换" in axis:
        angle = "第一脚出球决定回合质量"
    elif "二点球" in axis:
        angle = "二点球和肋部接应先出答案"
    else:
        angle = axis
    return f"{home} vs {away}：{angle}"


def match_section(match: dict[str, Any]) -> str:
    db = match["db"]
    home = str(match["home"])
    away = str(match["away"])
    teams = [home, away]
    group = str(match["group"])
    venue = str(match["venue"])
    notes = research_notes(match)
    matchups = report_matchups(match)
    profile_home = profile_line(home, db.get("home_profile") or {})
    profile_away = profile_line(away, db.get("away_profile") or {})
    first_axis = lead_axis(match)
    second_focus = secondary_axis(match)

    context_note = ""
    if notes:
        context_note = f"赛前资料里还有两个细节可以留意：{notes[0]}" + (f" {notes[1]}" if len(notes) > 1 else "")
    else:
        context_note = "赛前公开资料如果还没有给出完整首发，先别急着把注意力压在某一个名字上，结构比名单更早进入比赛。"

    matchup_note = ""
    if matchups:
        matchup_note = "已有赛前情报里比较实用的观察点是：" + "；".join(matchups)
    else:
        matchup_note = "这场的观察点可以先落在边路推进、后腰保护和定位球二点球上，这些位置最容易把纸面差异踢成真实观感。"

    return "".join(
        [
            small_title(match_headline(match, first_axis), "#b43a31"),
            (
                f'<p style="margin:0 0 14px;color:#303437;font-size:15px;line-height:1.82;">'
                f"这场是{group}，地点在{venue}，开球时间写清楚：{kickoff_text(match)}。"
                f"它不适合被塞进一张四队速览表里带过，最好单独看：一边要把自己的节奏踢出来，另一边要尽量把比赛拖进更熟的回合。"
                "</p>"
            ),
            (
                f'<p style="margin:0 0 14px;color:#303437;font-size:15px;line-height:1.82;">'
                f"公开数据自然嵌进比赛里看：{fact_sentence(home, match.get('home_fact'), db, 'home')}；"
                f"{fact_sentence(away, match.get('away_fact'), db, 'away')}。这些数字不是结论，更像地图，能帮你判断谁更该主动，谁更需要把阵型先站稳。"
                "</p>"
            ),
            (
                f'<p style="margin:0 0 14px;color:#303437;font-size:15px;line-height:1.82;">'
                f"{profile_home}{profile_away}{context_note}"
                "</p>"
            ),
            focus_title(first_axis, "#b98125", teams),
            (
                f'<p style="margin:0 0 14px;color:#303437;font-size:15px;line-height:1.82;">'
                f"{matchup_note} 具体看球时，不用盯满全场数据，先看后场被压时第一脚往哪儿出，"
                f"再看边路推进后禁区前沿有没有人接应。第一脚稳，比赛就能往前走；第一脚慌，后面的跑动很容易变成白跑。"
                "</p>"
            ),
            focus_title(second_focus, "#1f4d43", teams),
            (
                f'<p style="margin:0 0 14px;color:#303437;font-size:15px;line-height:1.82;">'
                f"看球时抓两个画面就够：丢球后的五秒钟有没有形成回抢，以及从守转攻时第一名接球人是不是面向前场。"
                f"前者决定场面能不能持续加温，后者决定反击是不是只剩一次长跑。首发、伤停和临场位置仍以赛前名单为准。"
                "</p>"
            ),
        ]
    )


def group_background(matches: list[dict[str, Any]]) -> str:
    groups: dict[str, list[str]] = {}
    for match in matches:
        groups.setdefault(str(match["group"]), []).append(match_label(match))
    lines = []
    for group, labels in groups.items():
        joined = "、".join(labels)
        lines.append(f"{group}今天涉及{joined}")
    return "；".join(lines) + "。第一轮最重要的不是把故事讲完，而是看每队怎样进入比赛。"


def render_html(matchday: str, hero_url: str, matches: list[dict[str, Any]]) -> tuple[str, str, str]:
    date_label = format_cn_date(matchday)
    title = article_title(matchday, matches)
    digest = article_digest(matches)
    html = "".join(
        [
            '<section style="max-width:677px;margin:0 auto;padding:0 0 28px;background:#fffdf8;color:#111417;">',
            f'<section style="margin:0;"><img src="{hero_url}" alt="{date_label}世界杯核心看点插图" style="display:block;width:100%;height:auto;" /></section>',
            '<section style="padding:0 20px;">',
            f'<p style="margin:0 0 18px;padding:12px 14px;border-left:4px solid #b43a31;background:#fff2ea;color:#4c5550;font-size:15px;line-height:1.82;">{digest}</p>',
            f'<p style="margin:0 0 14px;color:#303437;font-size:15px;line-height:1.82;">北京时间{date_label}的赛程不适合写成一串队名。读者真正需要的是看球抓手：这一场先看哪里，下一场别被什么表象带偏。今天还是按比赛逐场拆开，数据放回段落里，战术观察尽量落到边路、中场、定位球和转换这些能在画面里看见的东西。</p>',
            '<p style="margin:0 0 14px;color:#303437;font-size:15px;line-height:1.82;">资料整理优先使用赛程库、球队基础资料、赛前研究摘要和已发布情报里的非结果判断信息；缺口不硬编，发布前再按官方及公开页面校准。这样写会慢一点，但比把队名和数字硬塞进一张表里更像正常看球。</p>',
            small_title("今日赛程", "#b98125"),
            f'<section style="margin:0 0 22px;">{schedule_rows(matches)}</section>',
            small_title("小组背景先放一层底色", "#1f4d43"),
            f'<p style="margin:0 0 14px;color:#303437;font-size:15px;line-height:1.82;">{group_background(matches)}</p>',
            "".join(match_section(match) for match in matches),
            small_title("写在最后", "#b43a31"),
            f'<p style="margin:0 0 14px;color:#303437;font-size:15px;line-height:1.82;">北京时间{date_label}，看球不用把自己逼成资料库。先记住每场最该盯的区域：第一脚出球、边路推进、二点球、定位球和转换保护。比赛真正变味，往往不是从宏大叙事开始，而是从一次没接住的第二点、一次慢半拍的回防开始。</p>',
            f'<p style="margin:0;color:#6d5b21;font-size:13px;line-height:1.7;padding:10px 12px;border:1px solid #eadcae;border-radius:8px;background:#fff9e8;">{DISCLAIMER}</p>',
            "</section>",
            "</section>",
        ]
    )
    html = compact_html(html)
    validate_article(title, digest, html, matches)
    return title, digest, html


def validate_article(title: str, digest: str, html: str, matches: list[dict[str, Any]] | None = None) -> None:
    if "北京时间" in title:
        raise RuntimeError("外部标题不应包含“北京时间”")
    if "世界杯赛前解读：" not in title:
        raise RuntimeError("外部标题必须使用“X月X日世界杯赛前解读：核心看点”格式")
    if "观赛指南" in title:
        raise RuntimeError("外部标题不再使用“观赛指南”")
    if "<h1" in html.lower():
        raise RuntimeError("正文不应包含 h1，避免和微信外部标题重复")
    validate_heading_style(html)
    content = f"{title}\n{digest}\n{html}"
    for term in FORBIDDEN_TERMS:
        if term in content:
            raise RuntimeError(f"稿件包含禁用表达: {term}")
    validate_encoding_integrity(content)
    if matches:
        validate_matchday_structure(title, html, matches)


def validate_matchday_structure(title: str, html: str, matches: list[dict[str, Any]]) -> None:
    title_labels = {match_label(match) for match in matches} | {compact_match_label(match) for match in matches}
    if not any(label in title for label in title_labels):
        raise RuntimeError("外部标题必须包含今日核心赛事名称，例如“荷兰vs日本领衔”")

    headings = [
        re.sub(r"<[^>]+>", "", heading).strip()
        for heading in re.findall(r"<h3[^>]*>(.*?)</h3>", html, flags=re.I)
    ]
    for match in matches:
        spaced = match_label(match)
        compact = compact_match_label(match)
        if not any(spaced in heading or compact in heading for heading in headings):
            raise RuntimeError(f"每场比赛的主小标题必须包含赛事名称: {spaced}")


def validate_heading_style(html: str) -> None:
    headings = re.findall(r"<h3[^>]*>(.*?)</h3>", html, flags=re.I)
    bad_headings = {
        "关键球员与关键区域",
        "关键球员和区域",
        "比赛节奏与战术观察",
        "节奏与战术观察",
        "普通观众怎么抓重点",
        "普通观众怎么看",
    }
    for heading in headings:
        clean = re.sub(r"<[^>]+>", "", heading).strip()
        if clean in bad_headings:
            raise RuntimeError(f"小标题过于模板化，需要提炼具体内容: {clean}")
    seen: set[str] = set()
    duplicates: set[str] = set()
    for heading in headings:
        clean = re.sub(r"<[^>]+>", "", heading).strip()
        if clean in seen:
            duplicates.add(clean)
        seen.add(clean)
    if duplicates:
        raise RuntimeError(f"正文存在重复小标题: {'、'.join(sorted(duplicates))}")


def validate_encoding_integrity(content: str) -> None:
    suspicious_tokens = ("???", "åŒ", "åŠ", "æ—", "çš", "ç»", "ä¸", "ï¼", "ã€")
    found = [token for token in suspicious_tokens if token in content]
    if found:
        raise RuntimeError(f"稿件疑似发生编码损坏，停止推送: {', '.join(found)}")


def render_poster(matchday: str, matches: list[dict[str, Any]], background_path: Path | None = None) -> Path:
    date_line, headline, subline = poster_copy(matchday, matches)
    matchday_dir = OUTPUT_DIR / matchday
    matchday_dir.mkdir(parents=True, exist_ok=True)
    suffix = "-ai" if background_path else ""
    poster_path = matchday_dir / f"wechat-matchday-{matchday}{suffix}.png"
    script_path = ROOT / "tools" / "render_wechat_matchday_poster.ps1"
    command = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-OutputPath",
        str(poster_path),
        "-DateLine",
        date_line,
        "-Headline",
        headline,
        "-Subline",
        subline,
    ]
    if background_path:
        command.extend(["-BackgroundPath", str(background_path)])
    subprocess.run(command, check=True, cwd=ROOT)
    return poster_path


def configured_ai_hero_path(values: dict[str, str | None], matchday: str) -> Path | None:
    matchday_dir = OUTPUT_DIR / matchday
    candidates = [
        os.getenv("WECHAT_AI_HERO_IMAGE_PATH"),
        values.get("WECHAT_AI_HERO_IMAGE_PATH"),
        str(matchday_dir / "ai-hero.png"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists() and path.is_file():
            return path
    return None


def hero_image_path(values: dict[str, str | None], matchday: str, matches: list[dict[str, Any]]) -> tuple[Path, str]:
    ai_path = configured_ai_hero_path(values, matchday)
    matchday_dir = OUTPUT_DIR / matchday
    matchday_dir.mkdir(parents=True, exist_ok=True)
    if not ai_path:
        raise RuntimeError(
            "缺少 image2.0 生成的正文头图。请先生成当日专属 AI 插图，并保存为 "
            f"{matchday_dir / 'ai-hero.png'}，或设置 WECHAT_AI_HERO_IMAGE_PATH。"
        )
    target = matchday_dir / f"wechat-matchday-{matchday}-ai.png"
    if ai_path.resolve() != target.resolve():
        shutil.copyfile(ai_path, target)
    return target, "image2.0-ai-direct"


def upload_image(values: dict[str, str | None], poster_path: Path, admin_token: str) -> tuple[str, str | None]:
    endpoint = (values.get("WECHAT_RAW_IMAGE_ENDPOINT") or DEFAULT_RAW_IMAGE_ENDPOINT).strip()
    encoded = base64.b64encode(poster_path.read_bytes()).decode("ascii")
    payload = {
        "filename": poster_path.name,
        "content_type": "image/png",
        "base64": encoded,
    }
    try:
        response = httpx.post(
            endpoint,
            headers={"X-Admin-Token": admin_token},
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        url = (data.get("url") or "").strip()
        if not url:
            raise RuntimeError(f"图片接口未返回 url: {data}")
        return url, None
    except Exception as exc:
        raise RuntimeError(f"AI 正文头图上传失败，停止推送: {type(exc).__name__}: {exc}") from exc


def push_draft(values: dict[str, str | None], payload: dict[str, Any], admin_token: str) -> dict[str, Any]:
    endpoint = (values.get("WECHAT_RAW_DRAFT_ENDPOINT") or DEFAULT_RAW_DRAFT_ENDPOINT).strip()
    response = httpx.post(
        endpoint,
        headers={"X-Admin-Token": admin_token},
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def main() -> None:
    values = dotenv_values(ROOT / ".env")
    admin_token = require_env(values, "ADMIN_TOKEN")
    author = require_env(values, "WECHAT_AUTHOR")
    thumb_media_id = require_env(values, "WECHAT_DEFAULT_COVER_MEDIA_ID")

    group = next_matchday()
    matchday = str(group["matchday"])
    raw_matches = list(group["items"])
    if len(raw_matches) < 1:
        raise RuntimeError(f"{matchday} 的比赛场次数量异常: {len(raw_matches)}")

    team_facts = load_team_facts(values)
    matches = enrich_matches(raw_matches, team_facts)
    poster_path, hero_source = hero_image_path(values, matchday, matches)
    image_url, image_error = upload_image(values, poster_path, admin_token)
    title, digest, html = render_html(matchday, image_url, matches)
    validate_article(title, digest, html, matches)

    payload = {
        "articles": [
            {
                "title": title,
                "author": author,
                "digest": digest,
                "content": html,
                "thumb_media_id": thumb_media_id,
                "need_open_comment": 0,
                "only_fans_can_comment": 0,
            }
        ]
    }

    matchday_dir = OUTPUT_DIR / matchday
    matchday_dir.mkdir(parents=True, exist_ok=True)
    (matchday_dir / "draft-payload.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (matchday_dir / "article.html").write_text(html, encoding="utf-8")

    result = push_draft(values, payload, admin_token)
    summary = {
        "title": title,
        "matchday": matchday,
        "media_id": result.get("media_id"),
        "image_url": image_url,
        "image_upload_error": image_error,
        "hero_source": hero_source,
        "payload_file": str((matchday_dir / "draft-payload.json").resolve()),
        "html_file": str((matchday_dir / "article.html").resolve()),
        "poster_file": str(poster_path.resolve()),
        "match_count": len(matches),
        "matches": [match_label(match) for match in matches],
    }
    (matchday_dir / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
