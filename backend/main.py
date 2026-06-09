from __future__ import annotations

import json
import math
import os
import random
import sqlite3
import time
import asyncio
import hashlib
import hmac
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import wechat_article

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "worldcup.db"
FRONTEND_DIR = ROOT
ADMIN_TOKEN_DEFAULT = "change-me"
CN_TZ = ZoneInfo("Asia/Shanghai")
SCHEDULER: BackgroundScheduler | None = None

load_dotenv(ROOT / ".env")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CN_TZ)
    return parsed


def local_dt(value: str) -> datetime:
    return parse_dt(value).astimezone(CN_TZ)


def matchday_key(kickoff: str) -> str:
    return (local_dt(kickoff) - timedelta(hours=12)).date().isoformat()


def matchday_label(key: str) -> str:
    day = datetime.fromisoformat(f"{key}T00:00:00").date()
    return f"{day.month}月{day.day}日赛事"


def matchday_range(key: str) -> dict[str, str]:
    start = datetime.fromisoformat(f"{key}T12:00:00").replace(tzinfo=CN_TZ)
    end = start + timedelta(days=1) - timedelta(minutes=1)
    return {"start": start.isoformat(), "end": end.isoformat()}


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except ValueError:
        return default


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def jdump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def jload(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    expected = env("ADMIN_TOKEN", ADMIN_TOKEN_DEFAULT)
    if x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Invalid admin token")


def admin_page_password() -> str:
    return env("ADMIN_PAGE_PASSWORD", "change-me")


def admin_page_auth_token() -> str:
    secret = f"{admin_page_password()}:{env('ADMIN_TOKEN', ADMIN_TOKEN_DEFAULT)}"
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def is_admin_page_authenticated(request: Request) -> bool:
    token = request.cookies.get("wc_admin_page")
    expected = admin_page_auth_token()
    return bool(token) and hmac.compare_digest(token, expected)


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            create table if not exists teams (
              id text primary key,
              name text not null,
              code text not null,
              rating real not null default 1500,
              created_at text not null,
              updated_at text not null
            );

            create table if not exists team_stats (
              team_id text primary key,
              form_score real not null default 0,
              attack_score real not null default 0,
              defense_score real not null default 0,
              injuries_json text not null default '[]',
              updated_at text not null
            );

            create table if not exists matches (
              id text primary key,
              api_id text,
              home_team_id text not null,
              away_team_id text not null,
              kickoff text not null,
              group_name text not null,
              venue text not null,
              status text not null default 'scheduled',
              tags_json text not null default '[]',
              source text not null default 'seed',
              updated_at text not null
            );

            create table if not exists odds_snapshots (
              id integer primary key autoincrement,
              match_id text not null,
              provider text not null,
              bookmaker text not null,
              market text not null,
              odds_json text not null,
              implied_json text not null,
              fetched_at text not null
            );

            create table if not exists research_sources (
              id integer primary key autoincrement,
              match_id text not null,
              topic text not null,
              title text not null,
              url text not null,
              snippet text not null,
              fetched_at text not null
            );

            create table if not exists predictions (
              match_id text primary key,
              home_win real not null,
              draw real not null,
              away_win real not null,
              upset_index real not null,
              confidence real not null,
              factors_json text not null,
              odds_implied_json text not null,
              generated_at text not null
            );

            create table if not exists reports (
              id text primary key,
              match_id text not null,
              version integer not null,
              status text not null default 'draft',
              content_json text not null,
              sources_json text not null default '[]',
              created_at text not null,
              published_at text
            );

            create table if not exists champion_predictions (
              id integer primary key autoincrement,
              version integer not null,
              status text not null default 'draft',
              entries_json text not null,
              generated_at text not null,
              published_at text
            );

            create table if not exists generation_logs (
              id integer primary key autoincrement,
              action text not null,
              target_id text,
              status text not null,
              message text not null,
              created_at text not null
            );

            create table if not exists scheduled_job_runs (
              id integer primary key autoincrement,
              job_id text not null,
              job_name text not null,
              status text not null,
              started_at text not null,
              finished_at text,
              duration_seconds real,
              message text not null default '',
              payload_json text not null default '{}'
            );

            create table if not exists scheduled_job_configs (
              job_id text primary key,
              mode text not null,
              hour integer,
              minute integer,
              interval_minutes integer,
              enabled integer not null default 1,
              updated_at text not null
            );

            create table if not exists data_status (
              key text primary key,
              label text not null,
              status text not null,
              updated_at text,
              summary text not null default '',
              source text not null default '',
              detail_json text not null default '{}'
            );

            create table if not exists wechat_articles (
              id text primary key,
              article_type text not null,
              matchday text not null,
              version integer not null,
              status text not null,
              title text not null,
              digest text not null,
              markdown text not null,
              wechat_html text not null,
              source_json text not null,
              fact_check_json text,
              wechat_media_id text,
              error_message text,
              created_at text not null,
              pushed_at text
            );

            create table if not exists app_meta (
              key text primary key,
              value text not null,
              updated_at text not null
            );
            """
        )
    seed_demo_data()


def log_event(action: str, status: str, message: str, target_id: str | None = None) -> None:
    with db() as conn:
        conn.execute(
            "insert into generation_logs(action,target_id,status,message,created_at) values(?,?,?,?,?)",
            (action, target_id, status, message, now_iso()),
        )


JOB_DEFINITIONS: list[dict[str, Any]] = [
    {
        "id": "champion_daily",
        "name": "冠军预测每日更新",
        "kind": "champion",
        "trigger": "每天 06:30",
        "default_config": {"mode": "daily", "hour": 6, "minute": 30, "interval_minutes": None, "enabled": True},
        "description": "使用 DeepSeek thinking + high reasoning 更新热门球队冠军分析。",
    },
    {
        "id": "matchday_daily",
        "name": "赛前情报每日生成",
        "kind": "nearest_day_reports",
        "trigger": "每天 09:00",
        "default_config": {"mode": "daily", "hour": 9, "minute": 0, "interval_minutes": None, "enabled": True},
        "description": "生成最近赛事日所有比赛的赛前报告。",
    },
    {
        "id": "prematch_refresh",
        "name": "临场赛前情报更新",
        "kind": "prematch_reports",
        "trigger": "每 30 分钟",
        "default_config": {"mode": "interval", "hour": None, "minute": None, "interval_minutes": 30, "enabled": True},
        "description": "检查未来 3 小时内比赛，临近开赛时刷新报告。",
    },
    {
        "id": "wechat_daily_preview",
        "name": "WeChat daily preview draft",
        "kind": "wechat_daily_preview",
        "trigger": "Daily 18:00",
        "default_config": {"mode": "daily", "hour": env_int("WECHAT_DAILY_PREVIEW_HOUR", 18), "minute": 0, "interval_minutes": None, "enabled": False},
        "description": "Generate the next matchday WeChat daily preview. Draft push is controlled by WECHAT_DAILY_PREVIEW_AUTO_DRAFT.",
    },
    {
        "id": "schedule_refresh",
        "name": "赛程/赛果/积分同步",
        "kind": "schedule_status",
        "trigger": "每 30 分钟",
        "default_config": {"mode": "interval", "hour": None, "minute": None, "interval_minutes": 30, "enabled": True},
        "description": "同步赛程、赛果、积分和淘汰赛结构；当前生产数据源未配置时刷新本地状态。",
    },
]


def job_definition(job_id: str) -> dict[str, Any]:
    for item in JOB_DEFINITIONS:
        if item["id"] == job_id:
            return item
    raise HTTPException(status_code=404, detail="Job not found")


def job_config(job_id: str) -> dict[str, Any]:
    definition = job_definition(job_id)
    with db() as conn:
        row = conn.execute("select * from scheduled_job_configs where job_id=?", (job_id,)).fetchone()
    if not row:
        return {**definition["default_config"]}
    return {
        "mode": row["mode"],
        "hour": row["hour"],
        "minute": row["minute"],
        "interval_minutes": row["interval_minutes"],
        "enabled": bool(row["enabled"]),
    }


def describe_job_config(config: dict[str, Any]) -> str:
    if not config.get("enabled", True):
        return "已停用"
    if config.get("mode") == "daily":
        return f"每天 {int(config.get('hour') or 0):02d}:{int(config.get('minute') or 0):02d}"
    return f"每 {int(config.get('interval_minutes') or 30)} 分钟"


def validate_job_config(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "daily").strip()
    if mode not in {"daily", "interval"}:
        raise HTTPException(status_code=400, detail="mode must be daily or interval")
    enabled = bool(payload.get("enabled", True))
    if mode == "daily":
        hour = int(payload.get("hour", 0))
        minute = int(payload.get("minute", 0))
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise HTTPException(status_code=400, detail="Invalid daily time")
        return {"mode": mode, "hour": hour, "minute": minute, "interval_minutes": None, "enabled": enabled}
    interval = int(payload.get("interval_minutes", 30))
    if interval < 5 or interval > 1440:
        raise HTTPException(status_code=400, detail="interval_minutes must be between 5 and 1440")
    return {"mode": mode, "hour": None, "minute": None, "interval_minutes": interval, "enabled": enabled}


def save_job_config(job_id: str, config: dict[str, Any]) -> None:
    job_definition(job_id)
    with db() as conn:
        conn.execute(
            """
            insert into scheduled_job_configs(job_id,mode,hour,minute,interval_minutes,enabled,updated_at)
            values(?,?,?,?,?,?,?)
            on conflict(job_id) do update set
              mode=excluded.mode,
              hour=excluded.hour,
              minute=excluded.minute,
              interval_minutes=excluded.interval_minutes,
              enabled=excluded.enabled,
              updated_at=excluded.updated_at
            """,
            (
                job_id,
                config["mode"],
                config.get("hour"),
                config.get("minute"),
                config.get("interval_minutes"),
                1 if config.get("enabled", True) else 0,
                now_iso(),
            ),
        )


def schedule_job_from_config(scheduler: BackgroundScheduler, definition: dict[str, Any], config: dict[str, Any]) -> None:
    job_id = definition["id"]
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    if not config.get("enabled", True):
        return
    if config["mode"] == "daily":
        scheduler.add_job(
            lambda job_id=job_id: run_scheduled_job(job_id),
            "cron",
            hour=int(config["hour"]),
            minute=int(config["minute"]),
            id=job_id,
            replace_existing=True,
            max_instances=1,
        )
        return
    scheduler.add_job(
        lambda job_id=job_id: run_scheduled_job(job_id),
        "interval",
        minutes=int(config["interval_minutes"]),
        id=job_id,
        replace_existing=True,
        max_instances=1,
    )


def apply_job_config(job_id: str) -> None:
    if not SCHEDULER:
        return
    definition = job_definition(job_id)
    schedule_job_from_config(SCHEDULER, definition, job_config(job_id))


def update_data_status(key: str, label: str, status: str, summary: str, source: str = "", detail: dict[str, Any] | None = None, updated_at: str | None = None) -> None:
    with db() as conn:
        conn.execute(
            """
            insert into data_status(key,label,status,updated_at,summary,source,detail_json)
            values(?,?,?,?,?,?,?)
            on conflict(key) do update set
              label=excluded.label,
              status=excluded.status,
              updated_at=excluded.updated_at,
              summary=excluded.summary,
              source=excluded.source,
              detail_json=excluded.detail_json
            """,
            (key, label, status, updated_at or now_iso(), summary, source, jdump(detail or {})),
        )


def run_scheduled_job(job_id: str, manual: bool = False) -> dict[str, Any]:
    definition = job_definition(job_id)
    started = now_iso()
    started_clock = time.perf_counter()
    with db() as conn:
        cursor = conn.execute(
            "insert into scheduled_job_runs(job_id,job_name,status,started_at,message,payload_json) values(?,?,?,?,?,?)",
            (definition["id"], definition["name"], "running", started, "任务运行中", jdump({"manual": manual})),
        )
        run_id = cursor.lastrowid
    log_event("scheduler.job", "start", f"Started {definition['name']}", definition["id"])
    try:
        result = execute_job_kind(definition["kind"])
        duration = round(time.perf_counter() - started_clock, 1)
        message = str(result.get("message") or "任务完成")
        with db() as conn:
            conn.execute(
                "update scheduled_job_runs set status=?, finished_at=?, duration_seconds=?, message=?, payload_json=? where id=?",
                ("success", now_iso(), duration, message, jdump(result), run_id),
            )
        log_event("scheduler.job", "success", f"{definition['name']} finished in {duration:.1f}s", definition["id"])
        return {"ok": True, "jobId": job_id, "status": "success", "durationSeconds": duration, **result}
    except Exception as exc:
        duration = round(time.perf_counter() - started_clock, 1)
        message = f"{type(exc).__name__}: {exc}"
        with db() as conn:
            conn.execute(
                "update scheduled_job_runs set status=?, finished_at=?, duration_seconds=?, message=? where id=?",
                ("error", now_iso(), duration, message, run_id),
            )
        log_event("scheduler.job", "error", f"{definition['name']} failed: {message}", definition["id"])
        return {"ok": False, "jobId": job_id, "status": "error", "durationSeconds": duration, "message": message}


def execute_job_kind(kind: str) -> dict[str, Any]:
    if kind == "champion":
        result = generate_champion_prediction(publish=True, use_deepseek=True, reasoning_effort="high", thinking="enabled")
        entries = result.get("entries") or []
        update_data_status("champion_prediction", "冠军预测", "ok", f"版本 v{result.get('version')}，覆盖 {len(entries)} 支球队", "scheduler")
        return {"message": f"冠军预测已更新，版本 v{result.get('version')}", "version": result.get("version"), "count": len(entries)}
    if kind == "nearest_day_reports":
        group = nearest_matchday_scope()
        generated = []
        for item in group["items"]:
            report = generate_match_report(item["id"], publish=True, use_deepseek=True, reasoning_effort="high", thinking="enabled")
            generated.append(report["report_id"])
        update_data_status("matchday_reports", "赛前情报", "ok", f"{group['label']} 覆盖 {len(generated)} 场", "scheduler", {"matchday": group.get("matchday"), "reportIds": generated})
        return {"message": f"{group['label']} 赛前情报已更新 {len(generated)} 场", "count": len(generated), "matchday": group.get("matchday")}
    if kind == "prematch_reports":
        now = datetime.now(CN_TZ)
        window_end = now + timedelta(hours=3)
        matches = [item for item in nearest_matchday_scope()["items"] if now <= parse_dt(item["kickoff"]).astimezone(CN_TZ) <= window_end]
        generated = []
        for item in matches:
            report = generate_match_report(item["id"], publish=True, use_deepseek=True, reasoning_effort="high", thinking="enabled")
            generated.append(report["report_id"])
        status = "ok" if generated else "idle"
        summary = f"未来 3 小时刷新 {len(generated)} 场" if generated else "未来 3 小时暂无临近比赛"
        update_data_status("prematch_reports", "临场赛前情报", status, summary, "scheduler", {"reportIds": generated})
        return {"message": summary, "count": len(generated)}
    if kind == "wechat_daily_preview":
        groups = grouped_matchdays(query_public_matches())
        group = next((item for item in groups if item.get("items")), None)
        if not group:
            update_data_status("wechat_daily_preview", "WeChat daily preview", "idle", "No matchday available", "scheduler")
            return {"message": "No matchday available", "count": 0}
        source = wechat_article.build_daily_preview_source(group["matchday"])
        article = wechat_article.generate_daily_preview_article(source)
        fact_check = wechat_article.fact_check_wechat_article(source, article)
        saved = wechat_article.save_daily_preview_article(source, article, fact_check)
        pushed = None
        if saved["status"] == "generated" and env("WECHAT_DAILY_PREVIEW_AUTO_DRAFT", "false").lower() == "true":
            with db() as conn:
                row = conn.execute("select * from wechat_articles where id=?", (saved["id"],)).fetchone()
            pushed = wechat_article.push_wechat_draft({**dict(row), "wechat_html": row["wechat_html"]})
            with db() as conn:
                conn.execute(
                    "update wechat_articles set status=?, wechat_media_id=?, pushed_at=?, error_message=null where id=?",
                    ("draft_pushed", pushed.get("media_id"), now_iso(), saved["id"]),
                )
            saved["status"] = "draft_pushed"
            saved["wechatMediaId"] = pushed.get("media_id")
        update_data_status(
            "wechat_daily_preview",
            "WeChat daily preview",
            "ok" if saved["status"] in {"generated", "draft_pushed"} else "error",
            f"{source.get('label') or source.get('matchday')} {saved['status']}",
            "scheduler",
            {"articleId": saved["id"], "wechat": pushed or {}},
        )
        return {"message": f"WeChat daily preview {saved['status']}: {saved['id']}", "articleId": saved["id"], "status": saved["status"]}
    if kind == "schedule_status":
        with db() as conn:
            match_count = conn.execute("select count(*) value from matches").fetchone()["value"]
            team_count = conn.execute("select count(*) value from teams").fetchone()["value"]
            latest = conn.execute("select max(updated_at) value from matches").fetchone()["value"]
        update_data_status("schedule", "赛程信息", "ok", f"{team_count} 支球队，{match_count} 场赛程", "seed/api", {"matches": match_count, "teams": team_count}, latest or now_iso())
        return {"message": f"赛程状态已刷新：{team_count} 支球队，{match_count} 场赛程", "matches": match_count, "teams": team_count}
    raise RuntimeError(f"Unknown job kind: {kind}")


def refresh_computed_data_status() -> None:
    with db() as conn:
        schedule = conn.execute(
            """
            select count(*) match_count, max(updated_at) updated_at
            from matches
            """
        ).fetchone()
        team_count = conn.execute("select count(*) value from teams").fetchone()["value"]
        report = conn.execute(
            """
            select max(coalesce(published_at, created_at)) updated_at, count(*) count
            from reports
            where status='published'
            """
        ).fetchone()
        nearest = nearest_matchday(query_public_matches())
        nearest_ids = [item["id"] for item in nearest["items"]] if nearest else []
        nearest_report_count = 0
        if nearest_ids:
            placeholders = ",".join("?" for _ in nearest_ids)
            nearest_report_count = conn.execute(
                f"select count(distinct match_id) value from reports where status='published' and match_id in ({placeholders})",
                nearest_ids,
            ).fetchone()["value"]
        champion = conn.execute(
            "select version, generated_at, entries_json from champion_predictions where status='published' order by version desc limit 1"
        ).fetchone()
        research = conn.execute("select max(fetched_at) value, count(*) count from research_sources").fetchone()
        deepseek = conn.execute(
            """
            select max(created_at) value
            from generation_logs
            where action like 'deepseek.%' and status='success'
            """
        ).fetchone()

    update_data_status(
        "schedule",
        "赛程信息",
        "ok" if schedule["updated_at"] else "missing",
        f"{team_count} 支球队，{schedule['match_count']} 场赛程",
        "seed/api",
        {"teams": team_count, "matches": schedule["match_count"]},
        schedule["updated_at"] or now_iso(),
    )
    update_data_status(
        "matchday_reports",
        "赛前情报",
        "ok" if nearest_report_count and nearest and nearest_report_count >= len(nearest["items"]) else "stale",
        f"{nearest['label']} 覆盖 {nearest_report_count}/{len(nearest['items'])} 场" if nearest else "暂无最近赛事日",
        "reports",
        {"matchday": nearest.get("matchday") if nearest else None, "covered": nearest_report_count},
        report["updated_at"] or None,
    )
    update_data_status(
        "champion_prediction",
        "冠军预测",
        "ok" if champion else "missing",
        f"版本 v{champion['version']}，{len(jload(champion['entries_json'], []))} 支球队" if champion else "尚未发布冠军预测",
        "champion_predictions",
        {"version": champion["version"] if champion else None},
        champion["generated_at"] if champion else None,
    )
    update_data_status(
        "player_research",
        "球员/伤停检索",
        "ok" if research["value"] else "missing",
        f"已保存 {research['count']} 条检索来源" if research["value"] else "暂无检索来源",
        "serper/deepseek",
        {"sources": research["count"]},
        research["value"] or None,
    )
    update_data_status(
        "deepseek",
        "DeepSeek 生成",
        "ok" if deepseek["value"] else "missing",
        "最近成功调用已记录" if deepseek["value"] else "暂无成功调用记录",
        "generation_logs",
        {},
        deepseek["value"] or None,
    )


async def research_match_sources(match_id: str, limit: int = 8) -> list[dict[str, str]]:
    bundle = match_bundle(match_id)
    api_key = env("SERPER_API_KEY")
    if not api_key:
        log_event("research.match", "warning", "SERPER_API_KEY is not configured; skipped web research", match_id)
        return []
    queries = [
        f"{bundle['home_name']} {bundle['away_name']} injuries expected lineup formation team news World Cup 2026",
        f"{bundle['home_name']} predicted lineup formation injuries key players",
        f"{bundle['away_name']} predicted lineup formation injuries key players",
        f"{bundle['home_name']} {bundle['away_name']} 预计首发 阵型 伤停 世界杯",
    ]
    saved: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    async with httpx.AsyncClient(timeout=25) as client:
        for query in queries:
            response = await client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": 5},
            )
            response.raise_for_status()
            data = response.json()
            with db() as conn:
                for item in data.get("organic", [])[:5]:
                    title = str(item.get("title", "")).strip()
                    url = str(item.get("link", "")).strip()
                    snippet = str(item.get("snippet", "")).strip()
                    if not title or not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    conn.execute(
                        "insert into research_sources(match_id,topic,title,url,snippet,fetched_at) values(?,?,?,?,?,?)",
                        (match_id, "injury_lineup_formation_news", title, url, snippet, now_iso()),
                    )
                    saved.append({"title": title, "url": url, "snippet": snippet})
                    if len(saved) >= limit:
                        log_event("research.match", "success", f"Saved {len(saved)} sources", match_id)
                        return saved
    log_event("research.match", "success", f"Saved {len(saved)} sources", match_id)
    return saved


SEED_VERSION = "2026-official-groups-v1"


TEAM_PLAYER_PROFILES: dict[str, dict[str, Any]] = {
    "ARG": {
        "stars": ["梅西", "劳塔罗", "恩佐"],
        "strength": "前场创造力、禁区终结和中场出球层次都比较完整",
        "detail": "若梅西保持健康，他在前腰和右肋部的最后一传仍能提升破密防效率；劳塔罗负责禁区终结，恩佐的纵向传球能把中后场优势快速转化为推进。",
    },
    "FRA": {
        "stars": ["姆巴佩", "格列兹曼", "楚阿梅尼"],
        "strength": "左路冲击、反击速度和中场覆盖是核心优势",
        "detail": "姆巴佩的纵深威胁会迫使对手防线后撤，格列兹曼能在肋部串联进攻，楚阿梅尼的保护让法国在攻守转换中更有容错。",
    },
    "BRA": {
        "stars": ["维尼修斯", "罗德里戈", "卡塞米罗"],
        "strength": "边路一对一、前场换位和中场拦截能力突出",
        "detail": "维尼修斯的左路突破会制造持续牵制，罗德里戈可在锋线多个位置游走，卡塞米罗的防守站位决定球队压上后的安全感。",
    },
    "ENG": {
        "stars": ["凯恩", "贝林厄姆", "福登"],
        "strength": "中前场层次、禁区终结和二线插上质量较高",
        "detail": "凯恩的回撤做球能释放边路和前腰空间，贝林厄姆的后插上会改变禁区人数，福登在肋部的小范围处理是破局关键。",
    },
    "ESP": {
        "stars": ["罗德里", "佩德里", "亚马尔"],
        "strength": "控球节奏、前场压迫和边路创造力有优势",
        "detail": "罗德里决定西班牙攻守节拍，佩德里负责中路衔接，亚马尔如果进入首发会提供稀缺的一对一突破和弱侧传中。",
    },
    "POR": {
        "stars": ["B费", "贝尔纳多", "莱奥"],
        "strength": "中前场技术密度、远射和边路爆点充足",
        "detail": "B费的直塞和远射能拉开防守，贝尔纳多负责控节奏，莱奥在左路的冲刺会让对手边后卫很难放心压上。",
    },
    "NED": {
        "stars": ["范戴克", "德容", "加克波"],
        "strength": "中卫防空、后场出球和边前场推进能力均衡",
        "detail": "范戴克的第一落点控制决定防线稳定性，德容的带球推进能破解高压，加克波在左路内切和禁区前沿处理很关键。",
    },
    "GER": {
        "stars": ["穆西亚拉", "维尔茨", "基米希"],
        "strength": "前场小范围配合和中路渗透能力突出",
        "detail": "穆西亚拉和维尔茨能在密集防守中完成转身和直塞，基米希的传球选择会影响德国能否持续压制对手。",
    },
    "BEL": {
        "stars": ["德布劳内", "卢卡库", "多库"],
        "strength": "中路传威胁球、禁区支点和边路突破仍有威胁",
        "detail": "德布劳内的传球能直接改变进攻质量，卢卡库提供背身和终结，多库的一对一突破是打破僵局的重要手段。",
    },
    "KOR": {
        "stars": ["孙兴慜", "金玟哉", "李刚仁"],
        "strength": "前场速度、后防对抗和定位球质量值得关注",
        "detail": "孙兴慜的左路内切和纵深跑动是韩国最直接的得分来源；金玟哉要承担防线对抗和出球压力，李刚仁的定位球与肋部传球会影响韩国能否把反击变成机会。",
    },
    "JPN": {
        "stars": ["三笘薰", "久保建英", "远藤航"],
        "strength": "边路爆点、前场压迫和中场纪律性比较成熟",
        "detail": "三笘薰的一对一能制造宽度，久保建英在右肋部的处理有创造力，远藤航的拦截和二点球保护是日本控节奏的基础。",
    },
    "USA": {
        "stars": ["普利西奇", "麦肯尼", "雷纳"],
        "strength": "边路速度、前插冲击和中场跑动能力较强",
        "detail": "普利西奇是美国最稳定的推进点，麦肯尼的前插会增加禁区人数，雷纳如果健康能改善阵地战最后一传。",
    },
    "CAN": {
        "stars": ["阿方索·戴维斯", "戴维", "尤斯塔基奥"],
        "strength": "左路速度、前锋冲刺和中场覆盖是主要卖点",
        "detail": "阿方索·戴维斯的边路冲刺能快速改变推进速度，戴维负责反击终结，尤斯塔基奥需要保护中路二点球。",
    },
    "MEX": {
        "stars": ["希门尼斯", "洛萨诺", "埃德森·阿尔瓦雷斯"],
        "strength": "主场气氛、边路冲击和中场硬度是重要支撑",
        "detail": "希门尼斯的支点作用会影响禁区进攻质量，洛萨诺的速度适合打身后，埃德森·阿尔瓦雷斯负责中路防守屏障。",
    },
    "URU": {
        "stars": ["巴尔韦德", "努涅斯", "阿劳霍"],
        "strength": "中场冲击、锋线纵深和防线对抗能力很强",
        "detail": "巴尔韦德的长距离推进能带动节奏，努涅斯提供身后冲刺，阿劳霍的回追和对抗让乌拉圭敢于前压。",
    },
    "COL": {
        "stars": ["路易斯·迪亚斯", "哈梅斯", "莱尔马"],
        "strength": "左路突破、前场定位球和中场对抗有特点",
        "detail": "路易斯·迪亚斯是最直接的边路爆点，哈梅斯若保持状态能提升定位球和最后一传质量，莱尔马负责中场硬度。",
    },
    "NOR": {
        "stars": ["哈兰德", "厄德高", "瑟洛特"],
        "strength": "锋线终结、前腰输送和高点冲击非常鲜明",
        "detail": "哈兰德的禁区终结会迫使对手压缩防线，厄德高负责把控球转化为直塞，瑟洛特能提供第二高点和身体对抗。",
    },
    "MAR": {
        "stars": ["阿什拉夫", "齐耶赫", "阿姆拉巴特"],
        "strength": "边后卫推进、反击传球和中场拦截很有竞争力",
        "detail": "阿什拉夫的右路推进能制造人数优势，齐耶赫负责长传和定位球，阿姆拉巴特的覆盖决定摩洛哥防线厚度。",
    },
    "CRO": {
        "stars": ["莫德里奇", "科瓦契奇", "格瓦迪奥尔"],
        "strength": "中场控节奏和后场出球仍是球队底盘",
        "detail": "莫德里奇的节奏控制会影响比赛速度，科瓦契奇负责推进摆脱，格瓦迪奥尔能在防守和左路出球之间提供平衡。",
    },
    "SEN": {
        "stars": ["马内", "库利巴利", "伊斯梅拉·萨尔"],
        "strength": "前场冲刺、后防对抗和边路转换速度突出",
        "detail": "马内的反击跑位仍有威胁，库利巴利负责防线对抗，萨尔的边路速度适合在下半场冲击疲劳防线。",
    },
}


GENERIC_PLAYER_TERMS = (
    "反击第一推进点",
    "中卫防空核心",
    "门将出球点",
    "核心前场持球点",
    "中场覆盖型球员",
    "定位球主罚手",
    "边路爆点",
    "反击速度点",
    "中场组织核心",
    "中场拦截点",
    "防线保护点",
    "门将位置",
)


MARKET_OUTRIGHT_ODDS = {
    "ESP": 5.50,
    "FRA": 6.00,
    "ENG": 7.50,
    "BRA": 9.00,
    "POR": 9.00,
    "ARG": 10.00,
    "GER": 14.00,
    "NED": 20.00,
    "NOR": 25.00,
    "BEL": 35.00,
    "USA": 41.00,
    "SUI": 41.00,
    "MAR": 51.00,
    "COL": 51.00,
    "JPN": 67.00,
}


def real_star_names(profile: dict[str, Any]) -> list[str]:
    names = []
    for name in profile.get("stars") or []:
        value = str(name).strip()
        if value and value not in GENERIC_PLAYER_TERMS:
            names.append(value)
    return names


def public_player_list(stars: list[str]) -> list[str]:
    return [f"若入选：{name}" for name in stars] if stars else ["官方名单未公布。"]


def player_analysis_cards(team: str, stars: list[str], detail: str) -> list[dict[str, str]]:
    if not stars:
        return []
    roles = ["核心进攻点", "关键支点", "中后场核心"]
    cards = []
    for index, name in enumerate(stars[:3]):
        cards.append(
            {
                "team": team,
                "name": name,
                "role": roles[min(index, len(roles) - 1)],
                "impact": f"{name}是{team}本场需要重点观察的球员。{detail}",
            }
        )
    return cards


def seed_teams() -> list[tuple[str, str, str, float, float, float, float]]:
    return [
        ("mexico", "墨西哥", "MEX", 1690, 7.2, 6.8, 6.4),
        ("south-korea", "韩国", "KOR", 1608, 6.3, 6.5, 5.8),
        ("south-africa", "南非", "RSA", 1515, 4.8, 5.4, 5.2),
        ("czechia", "捷克", "CZE", 1622, 5.8, 5.9, 6.2),
        ("canada", "加拿大", "CAN", 1588, 6.4, 6.7, 5.6),
        ("bosnia", "波黑", "BIH", 1550, 5.6, 5.8, 5.4),
        ("qatar", "卡塔尔", "QAT", 1496, 5.0, 5.2, 5.1),
        ("switzerland", "瑞士", "SUI", 1656, 6.4, 6.2, 6.7),
        ("brazil", "巴西", "BRA", 1815, 7.7, 8.1, 7.0),
        ("morocco", "摩洛哥", "MAR", 1680, 7.0, 6.7, 6.8),
        ("haiti", "海地", "HAI", 1438, 4.6, 4.7, 4.9),
        ("scotland", "苏格兰", "SCO", 1588, 5.7, 5.6, 6.0),
        ("usa", "美国", "USA", 1640, 6.6, 6.7, 5.9),
        ("paraguay", "巴拉圭", "PAR", 1598, 5.7, 5.4, 6.4),
        ("australia", "澳大利亚", "AUS", 1536, 5.4, 5.3, 5.7),
        ("turkey", "土耳其", "TUR", 1612, 6.0, 6.4, 5.7),
        ("germany", "德国", "GER", 1768, 7.2, 7.5, 6.8),
        ("curacao", "库拉索", "CUW", 1428, 4.5, 4.6, 4.9),
        ("ivory-coast", "科特迪瓦", "CIV", 1578, 5.9, 6.1, 5.5),
        ("ecuador", "厄瓜多尔", "ECU", 1648, 6.2, 6.1, 6.3),
        ("netherlands", "荷兰", "NED", 1765, 7.2, 7.4, 6.8),
        ("japan", "日本", "JPN", 1668, 7.1, 6.9, 6.3),
        ("sweden", "瑞典", "SWE", 1602, 5.8, 5.7, 6.2),
        ("tunisia", "突尼斯", "TUN", 1548, 5.4, 5.3, 5.8),
        ("belgium", "比利时", "BEL", 1740, 6.9, 7.1, 6.5),
        ("egypt", "埃及", "EGY", 1588, 5.8, 6.0, 5.7),
        ("iran", "伊朗", "IRN", 1585, 5.8, 5.7, 5.9),
        ("new-zealand", "新西兰", "NZL", 1455, 4.8, 4.7, 5.1),
        ("spain", "西班牙", "ESP", 1795, 7.6, 7.8, 7.0),
        ("cape-verde", "佛得角", "CPV", 1498, 5.1, 5.1, 5.4),
        ("saudi-arabia", "沙特", "KSA", 1508, 5.1, 5.2, 5.1),
        ("uruguay", "乌拉圭", "URU", 1712, 6.9, 6.8, 6.7),
        ("france", "法国", "FRA", 1820, 7.8, 8.0, 7.3),
        ("senegal", "塞内加尔", "SEN", 1626, 6.2, 6.1, 6.3),
        ("iraq", "伊拉克", "IRQ", 1502, 5.2, 5.4, 5.2),
        ("norway", "挪威", "NOR", 1642, 6.3, 6.7, 5.7),
        ("argentina", "阿根廷", "ARG", 1830, 7.9, 8.0, 7.2),
        ("algeria", "阿尔及利亚", "ALG", 1572, 5.8, 5.9, 5.6),
        ("austria", "奥地利", "AUT", 1670, 6.5, 6.3, 6.5),
        ("jordan", "约旦", "JOR", 1452, 4.8, 4.9, 5.0),
        ("portugal", "葡萄牙", "POR", 1788, 7.4, 7.8, 6.8),
        ("dr-congo", "民主刚果", "COD", 1518, 5.2, 5.6, 5.2),
        ("uzbekistan", "乌兹别克斯坦", "UZB", 1512, 5.3, 5.4, 5.2),
        ("colombia", "哥伦比亚", "COL", 1696, 6.9, 6.8, 6.4),
        ("england", "英格兰", "ENG", 1805, 7.5, 7.7, 7.1),
        ("croatia", "克罗地亚", "CRO", 1688, 6.6, 6.4, 6.7),
        ("ghana", "加纳", "GHA", 1542, 5.5, 5.9, 5.2),
        ("panama", "巴拿马", "PAN", 1488, 5.0, 5.1, 5.0),
    ]


def seed_group_map() -> dict[str, list[str]]:
    return {
        "A 组": ["mexico", "south-africa", "south-korea", "czechia"],
        "B 组": ["canada", "bosnia", "qatar", "switzerland"],
        "C 组": ["brazil", "morocco", "haiti", "scotland"],
        "D 组": ["usa", "paraguay", "australia", "turkey"],
        "E 组": ["germany", "curacao", "ivory-coast", "ecuador"],
        "F 组": ["netherlands", "japan", "sweden", "tunisia"],
        "G 组": ["belgium", "egypt", "iran", "new-zealand"],
        "H 组": ["spain", "cape-verde", "saudi-arabia", "uruguay"],
        "I 组": ["france", "senegal", "iraq", "norway"],
        "J 组": ["argentina", "algeria", "austria", "jordan"],
        "K 组": ["portugal", "dr-congo", "uzbekistan", "colombia"],
        "L 组": ["england", "croatia", "ghana", "panama"],
    }


def seed_match_rows() -> list[tuple[str, str, str, str, str, str, list[str]]]:
    venues = [
        "墨西哥城", "洛杉矶", "温哥华", "休斯敦", "纽约", "多伦多",
        "达拉斯", "迈阿密", "西雅图", "亚特兰大", "旧金山", "堪萨斯城",
    ]
    tag_sets = [
        ["开局强度", "中场控制", "定位球"],
        ["边路速度", "身体对抗", "转换进攻"],
        ["高位压迫", "门前效率", "防线保护"],
    ]
    fixtures: list[tuple[str, str, str, str, str, str, list[str]]] = []
    round_pairs = [((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2))]
    base = datetime(2026, 6, 12, 3, 0, tzinfo=CN_TZ)
    group_map = seed_group_map()
    match_no = 1
    for group_index, (group_name, teams) in enumerate(group_map.items()):
        for round_index, pairs in enumerate(round_pairs):
            day_offset = round_index * 7 + group_index // 3
            for pair_index, (home_idx, away_idx) in enumerate(pairs):
                kickoff = base + timedelta(days=day_offset, hours=(group_index % 3) * 3 + pair_index * 3)
                home_id = teams[home_idx]
                away_id = teams[away_idx]
                fixtures.append(
                    (
                        f"seed-{match_no:03d}-{home_id[:3]}-{away_id[:3]}",
                        home_id,
                        away_id,
                        kickoff.isoformat(),
                        group_name,
                        venues[(group_index + round_index + pair_index) % len(venues)],
                        tag_sets[(round_index + pair_index) % len(tag_sets)],
                    )
                )
                match_no += 1
    return fixtures


def seed_demo_data() -> None:
    with db() as conn:
        current_seed = conn.execute("select value from app_meta where key='seed_version'").fetchone()
        should_refresh_reports = not current_seed or current_seed["value"] != SEED_VERSION
        match_rows = seed_match_rows()
        current_match_ids = [row[0] for row in match_rows]
        current_team_ids = [team[0] for team in seed_teams()]
        for team_id, name, code, rating, form, attack, defense in seed_teams():
            conn.execute(
                """
                insert into teams(id,name,code,rating,created_at,updated_at) values(?,?,?,?,?,?)
                on conflict(id) do update set
                  name=excluded.name, code=excluded.code, rating=excluded.rating, updated_at=excluded.updated_at
                """,
                (team_id, name, code, rating, now_iso(), now_iso()),
            )
            conn.execute(
                """
                insert into team_stats(team_id,form_score,attack_score,defense_score,injuries_json,updated_at)
                values(?,?,?,?,?,?)
                on conflict(team_id) do update set
                  form_score=excluded.form_score, attack_score=excluded.attack_score,
                  defense_score=excluded.defense_score, updated_at=excluded.updated_at
                """,
                (team_id, form, attack, defense, "[]", now_iso()),
            )
        for match_id, home_id, away_id, kickoff, group_name, venue, tags in match_rows:
            conn.execute(
                """
                insert into matches(id,home_team_id,away_team_id,kickoff,group_name,venue,status,tags_json,source,updated_at)
                values(?,?,?,?,?,?,?,?,?,?)
                on conflict(id) do update set
                  home_team_id=excluded.home_team_id, away_team_id=excluded.away_team_id,
                  kickoff=excluded.kickoff, group_name=excluded.group_name, venue=excluded.venue,
                  tags_json=excluded.tags_json, source=excluded.source, updated_at=excluded.updated_at
                """,
                (match_id, home_id, away_id, kickoff, group_name, venue, "scheduled", jdump(tags), "seed", now_iso()),
            )
        placeholders = ",".join("?" for _ in current_match_ids)
        stale_rows = conn.execute(
            f"select id from matches where source='seed' and id not in ({placeholders})",
            current_match_ids,
        ).fetchall()
        for stale in stale_rows:
            stale_id = stale["id"]
            conn.execute("delete from odds_snapshots where match_id=?", (stale_id,))
            conn.execute("delete from predictions where match_id=?", (stale_id,))
            conn.execute("delete from reports where match_id=?", (stale_id,))
            conn.execute("delete from matches where id=?", (stale_id,))
        team_placeholders = ",".join("?" for _ in current_team_ids)
        conn.execute(f"delete from team_stats where team_id not in ({team_placeholders})", current_team_ids)
        conn.execute(f"delete from teams where id not in ({team_placeholders})", current_team_ids)
        seed_odds(conn)
        conn.execute(
            """
            insert into app_meta(key,value,updated_at) values('seed_version',?,?,?)
            on conflict(key) do update set value=excluded.value, updated_at=excluded.updated_at
            """.replace("values('seed_version',?,?,?)", "values('seed_version',?,?)"),
            (SEED_VERSION, now_iso()),
        )
    if should_refresh_reports:
        for match_id, *_ in seed_match_rows():
            generate_match_report(match_id, publish=True, use_deepseek=False)
        generate_champion_prediction(publish=True)


def seed_odds(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        select m.id, ht.rating home_rating, at.rating away_rating
        from matches m
        join teams ht on ht.id=m.home_team_id
        join teams at on at.id=m.away_team_id
        where m.source='seed'
        """
    ).fetchall()
    for row in rows:
        gap = float(row["home_rating"]) - float(row["away_rating"])
        home_prob = max(0.22, min(0.68, 0.47 + gap / 900))
        draw_prob = max(0.20, min(0.31, 0.27 - abs(gap) / 3200))
        away_prob = max(0.14, 1 - home_prob - draw_prob)
        total = home_prob + draw_prob + away_prob
        margin = 1.06
        if not conn.execute("select 1 from odds_snapshots where match_id=? and market='1x2' limit 1", (row["id"],)).fetchone():
            odds = {
                "home": round(1 / (home_prob / total * margin), 2),
                "draw": round(1 / (draw_prob / total * margin), 2),
                "away": round(1 / (away_prob / total * margin), 2),
            }
            implied = no_vig_probabilities(odds)
            conn.execute(
                "insert into odds_snapshots(match_id,provider,bookmaker,market,odds_json,implied_json,fetched_at) values(?,?,?,?,?,?,?)",
                (row["id"], "seed", "reference", "1x2", jdump(odds), jdump(implied), now_iso()),
            )
        if not conn.execute("select 1 from odds_snapshots where match_id=? and market='totals' limit 1", (row["id"],)).fetchone():
            expected_total = max(1.8, min(3.5, 2.45 + (float(row["home_rating"]) + float(row["away_rating"]) - 3200) / 900))
            line = min([2.0, 2.25, 2.5, 2.75, 3.0, 3.25], key=lambda value: abs(value - expected_total))
            over_prob = max(0.38, min(0.62, 0.5 + (expected_total - line) * 0.18))
            under_prob = 1 - over_prob
            totals_odds = {
                "line": line,
                "over": round(1 / (over_prob * margin), 2),
                "under": round(1 / (under_prob * margin), 2),
            }
            implied = no_vig_probabilities({"over": totals_odds["over"], "under": totals_odds["under"]})
            conn.execute(
                "insert into odds_snapshots(match_id,provider,bookmaker,market,odds_json,implied_json,fetched_at) values(?,?,?,?,?,?,?)",
                (row["id"], "seed", "bet365_reference", "totals", jdump(totals_odds), jdump(implied), now_iso()),
            )


def no_vig_probabilities(odds: dict[str, float]) -> dict[str, float]:
    raw = {key: 1 / value for key, value in odds.items() if value and value > 1}
    total = sum(raw.values()) or 1
    return {key: round(value / total * 100, 2) for key, value in raw.items()}


def poisson_probability(goals: int, expected_goals: float) -> float:
    return math.exp(-expected_goals) * expected_goals**goals / math.factorial(goals)


def score_and_totals_prediction(bundle: dict[str, Any], probs: dict[str, float]) -> dict[str, Any]:
    attack_home = float(bundle["home_attack"] or 5.8)
    defense_home = float(bundle["home_defense"] or 5.8)
    attack_away = float(bundle["away_attack"] or 5.8)
    defense_away = float(bundle["away_defense"] or 5.8)
    rating_gap = float(bundle["home_rating"]) - float(bundle["away_rating"])
    tempo = 2.45 + (attack_home + attack_away - 11.6) * 0.09 - (defense_home + defense_away - 11.6) * 0.045
    edge = (probs["home"] - probs["away"]) / 100 + rating_gap / 1800
    home_xg = max(0.45, min(3.1, tempo / 2 + edge * 0.85 + (attack_home - defense_away) * 0.08))
    away_xg = max(0.35, min(2.8, tempo - home_xg + (attack_away - defense_home) * 0.06))
    score_candidates: list[dict[str, Any]] = []
    for home_goals in range(6):
        for away_goals in range(6):
            probability = poisson_probability(home_goals, home_xg) * poisson_probability(away_goals, away_xg)
            score_candidates.append({"score": f"{home_goals}-{away_goals}", "probability": probability})
    score_candidates.sort(key=lambda item: item["probability"], reverse=True)
    primary = score_candidates[0]
    alternatives = [item["score"] for item in score_candidates[1:4]]

    totals_row = bundle.get("totals_odds")
    totals_source = "模型临时盘口"
    if totals_row:
        totals_data = jload(totals_row["odds_json"], {})
        line = float(totals_data.get("line") or 2.5)
        totals_source = "Bet365盘口参考" if "bet365" in str(totals_row["bookmaker"]).lower() else "盘口数据参考"
    else:
        expected_total = home_xg + away_xg
        line = min([2.0, 2.25, 2.5, 2.75, 3.0, 3.25], key=lambda value: abs(value - expected_total))
    over_probability = 0.0
    for home_goals in range(8):
        for away_goals in range(8):
            if home_goals + away_goals > line:
                over_probability += poisson_probability(home_goals, home_xg) * poisson_probability(away_goals, away_xg)
    over_probability = round(max(0.05, min(0.95, over_probability)) * 100, 1)
    under_probability = round(100 - over_probability, 1)
    pick = "大球" if over_probability >= under_probability else "小球"
    score_prediction = {
        "primary": primary["score"],
        "alternatives": alternatives,
        "homeXg": round(home_xg, 2),
        "awayXg": round(away_xg, 2),
        "confidence": round(primary["probability"] * 100, 1),
    }
    totals_prediction = {
        "line": line,
        "pick": pick,
        "displayPick": "进球偏多" if pick == "大球" else "进球偏少",
        "overProbability": over_probability,
        "underProbability": under_probability,
        "source": totals_source,
    }
    return {"score": score_prediction, "totals": totals_prediction}


def latest_odds(conn: sqlite3.Connection, match_id: str, market: str = "1x2") -> sqlite3.Row | None:
    return conn.execute(
        "select * from odds_snapshots where match_id=? and market=? order by fetched_at desc, id desc limit 1",
        (match_id, market),
    ).fetchone()


def match_bundle(match_id: str) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute(
            """
            select m.*, ht.name home_name, ht.code home_code, ht.rating home_rating,
                   at.name away_name, at.code away_code, at.rating away_rating,
                   hs.form_score home_form, hs.attack_score home_attack, hs.defense_score home_defense,
                   as2.form_score away_form, as2.attack_score away_attack, as2.defense_score away_defense
            from matches m
            join teams ht on ht.id=m.home_team_id
            join teams at on at.id=m.away_team_id
            left join team_stats hs on hs.team_id=m.home_team_id
            left join team_stats as2 on as2.team_id=m.away_team_id
            where m.id=?
            """,
            (match_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Match not found")
        odds = latest_odds(conn, match_id, "1x2")
        totals_odds = latest_odds(conn, match_id, "totals")
        sources = conn.execute(
            "select topic,title,url,snippet,fetched_at from research_sources where match_id=? order by fetched_at desc",
            (match_id,),
        ).fetchall()
    bundle = dict(row)
    bundle["tags"] = jload(bundle.pop("tags_json"), [])
    bundle["odds"] = dict(odds) if odds else None
    bundle["totals_odds"] = dict(totals_odds) if totals_odds else None
    bundle["research_sources"] = [dict(source) for source in sources]
    bundle["home_profile"] = TEAM_PLAYER_PROFILES.get(bundle["home_code"], {})
    bundle["away_profile"] = TEAM_PLAYER_PROFILES.get(bundle["away_code"], {})
    return bundle


def calculate_prediction(bundle: dict[str, Any]) -> dict[str, Any]:
    rating_gap = float(bundle["home_rating"]) - float(bundle["away_rating"])
    form_gap = float(bundle["home_form"] or 0) - float(bundle["away_form"] or 0)
    attack_gap = float(bundle["home_attack"] or 0) - float(bundle["away_defense"] or 0)
    defense_gap = float(bundle["home_defense"] or 0) - float(bundle["away_attack"] or 0)
    venue_boost = 48 if "主场" in "".join(bundle["tags"]) or bundle["home_name"] in bundle["venue"] else 0
    model_edge = rating_gap / 400 + form_gap * 0.055 + attack_gap * 0.04 + defense_gap * 0.025 + venue_boost / 400

    model_home = 1 / (1 + math.exp(-model_edge))
    model_draw = max(0.18, min(0.32, 0.27 - abs(model_edge) * 0.04))
    model_away = 1 - model_home
    base = {
        "home": model_home * (1 - model_draw) * 100,
        "draw": model_draw * 100,
        "away": model_away * (1 - model_draw) * 100,
    }

    odds_implied = {"home": None, "draw": None, "away": None}
    if bundle["odds"]:
        odds_implied = jload(bundle["odds"]["implied_json"], odds_implied)
        for key in ("home", "draw", "away"):
            if odds_implied.get(key) is not None:
                base[key] = base[key] * 0.58 + float(odds_implied[key]) * 0.42

    total = sum(base.values()) or 1
    probs = {key: round(value / total * 100, 1) for key, value in base.items()}
    favorite = max(probs, key=probs.get)
    underdog_prob = min(probs["home"], probs["away"])
    upset_index = round(100 - probs[favorite] + underdog_prob * 0.35, 1)
    confidence = round(min(91, max(42, 54 + abs(probs["home"] - probs["away"]) * 0.55 + (8 if bundle["odds"] else 0))), 1)
    score_totals = score_and_totals_prediction(bundle, probs)
    model_weight = 58 if bundle["odds"] else 100
    market_weight = 42 if bundle["odds"] else 0

    factors = [
        {"name": "球队基础评分", "homeImpact": round(rating_gap / 20, 1), "awayImpact": round(-rating_gap / 20, 1), "detail": f"{bundle['home_name']} 与 {bundle['away_name']} 的评分差为 {round(rating_gap, 1)}。"},
        {"name": "近期状态", "homeImpact": round(form_gap, 1), "awayImpact": round(-form_gap, 1), "detail": "使用最近表现分、攻防状态做加权。"},
        {"name": "攻防匹配", "homeImpact": round(attack_gap + defense_gap, 1), "awayImpact": round(-(attack_gap + defense_gap), 1), "detail": "比较进攻强度与对手防守稳定性。"},
        {"name": "市场数据", "homeImpact": odds_implied.get("home"), "awayImpact": odds_implied.get("away"), "detail": "如有可用市场数据，去除水位后作为外部先验。"},
    ]
    return {
        "home_win": probs["home"],
        "draw": probs["draw"],
        "away_win": probs["away"],
        "upset_index": upset_index,
        "confidence": confidence,
        "factors": factors,
        "odds_implied": odds_implied,
        "model_weights": {"model": model_weight, "market": market_weight},
        "score_prediction": score_totals["score"],
        "totals_prediction": score_totals["totals"],
    }


def model_logic_note(bundle: dict[str, Any], prediction: dict[str, Any]) -> str:
    home = bundle["home_name"]
    away = bundle["away_name"]
    rating_gap = float(bundle["home_rating"]) - float(bundle["away_rating"])
    form_gap = float(bundle["home_form"] or 0) - float(bundle["away_form"] or 0)
    home_attack_vs_away_defense = float(bundle["home_attack"] or 0) - float(bundle["away_defense"] or 0)
    away_attack_vs_home_defense = float(bundle["away_attack"] or 0) - float(bundle["home_defense"] or 0)
    venue_boost = 48 if "主场" in "".join(bundle["tags"]) or home in bundle["venue"] else 0
    market_text = "当前没有可用市场先验，胜平负完全来自模型侧计算。"
    odds = prediction.get("odds_implied") or {}
    if any(odds.get(key) is not None for key in ("home", "draw", "away")):
        market_text = (
            "胜平负概率已加入去水后的市场隐含概率，当前口径为模型侧 58% + 市场先验 42%；"
            f"市场侧参考为 {home} {odds.get('home', '--')}%、平局 {odds.get('draw', '--')}%、{away} {odds.get('away', '--')}%。"
        )
    venue_text = f"赛地/主场修正约 +{venue_boost} 模型点。" if venue_boost else "赛地没有给主队明显额外加成。"
    return (
        f"模型先把球队基础评分、近期状态、攻防匹配和赛地因素合成为赛前强度差："
        f"{home}相对{away}的基础评分差为 {rating_gap:+.0f}，近期状态差为 {form_gap:+.1f}，"
        f"{home}进攻对{away}防守的匹配差为 {home_attack_vs_away_defense:+.1f}，"
        f"{away}进攻对{home}防守的匹配差为 {away_attack_vs_home_defense:+.1f}，{venue_text}"
        f"{market_text}"
        f"归一化后得到 {home} 胜 {prediction['home_win']}%、平局 {prediction['draw']}%、{away} 胜 {prediction['away_win']}%。"
    )


def enrich_logic_text(content_logic: Any, bundle: dict[str, Any], prediction: dict[str, Any]) -> str:
    logic = str(content_logic or "").strip()
    note = model_logic_note(bundle, prediction)
    if not logic:
        return note
    if "模型" in logic and ("评分" in logic or "市场" in logic):
        return logic
    return f"{note}{logic}"


def fallback_report(bundle: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    home = bundle["home_name"]
    away = bundle["away_name"]
    leader = home if prediction["home_win"] >= prediction["away_win"] else away
    follower = away if leader == home else home
    venue = bundle["venue"]
    tags = "、".join(bundle["tags"][:3]) or "比赛节奏"
    home_profile = bundle.get("home_profile") or {}
    away_profile = bundle.get("away_profile") or {}
    home_stars = real_star_names(home_profile)
    away_stars = real_star_names(away_profile)
    home_detail = home_profile.get("detail") or f"{home}官方重点球员名单暂未补齐，当前只保留球队层面的攻防判断。"
    away_detail = away_profile.get("detail") or f"{away}官方重点球员名单暂未补齐，当前只保留球队层面的攻防判断。"
    home_lineup = predicted_lineup(home, home_stars, "4-2-3-1", attacking=True)
    away_lineup = predicted_lineup(away, away_stars, "4-4-2", attacking=False)
    score = prediction["score_prediction"]
    totals = prediction["totals_prediction"]
    return {
        "summary": f"{leader}在赛前评估中略占主动，但{follower}并非没有反制空间；本场关键在开局压迫、二点球保护和临场阵容完整度。",
        "logic": (
            f"{model_logic_note(bundle, prediction)}"
            "这意味着本场不是单纯看基础评分，而是把强弱差、状态差、攻防错位、主场修正和外部先验合在一起判断。"
            f"{leader}的优势主要来自更高的综合强度和更稳定的控场预期；{follower}的反制窗口则在转换速度、定位球和热门方久攻不下后的心理波动。"
            "如果赛前首发出现核心缺口，尤其是中轴线或边路速度点变化，胜平负分布需要重新计算。"
        ),
        "score_prediction": {
            **score,
            "analysis": (
                f"首选比分倾向 {score['primary']}，备选方向为 {'、'.join(score['alternatives'])}。"
                f"{home}如果能把边路推进和二点球控制转化成稳定禁区触球，更容易先拿到领先；"
                f"{away}则需要压缩中路空间，并依靠转换和定位球把比赛拖入胶着状态。"
                "整体看，比赛更像是由开局压迫、关键球员处理质量和下半场体能变化共同决定。"
            ),
        },
        "totals_prediction": {
            **totals,
            "analysis": (
                f"本场进球数倾向更接近{totals.get('displayPick') or ('进球偏多' if totals['pick'] == '大球' else '进球偏少')}。"
                f"{home}的推进效率、{away}的回防密度和双方定位球质量会决定比赛是否被拉开；"
                "如果早段出现进球、主力中卫临场缺阵，或者边路速度点提前打开空间，节奏会明显变快。"
                "若双方中场绞杀强度高、禁区前沿处理保守，比赛则更容易停留在谨慎节奏。"
            ),
        },
        "win_path": [
            f"{home}要把前 20 分钟的控球和推进转化为禁区触球，避免优势只停留在中后场传导。",
            f"{home}的边后卫压上后需要中场及时补位，防止被{away}直接打身后空间。",
            f"{away}如果选择低位防守，第一出球点必须稳定，否则连续丢失球权会放大防线压力。",
            f"{away}更现实的得分方式来自快速转换、定位球二次进攻以及对方回防落位不齐的窗口。",
            f"双方在比赛后段都要控制犯规区域，禁区前沿的任意球会显著改变比赛走势。",
        ],
        "risk_points": [
            f"{leader}如果迟迟无法取得领先，比赛会逐渐进入{follower}更容易接受的低比分区间。",
            "赛前 1 小时公布的首发会改变中场覆盖、边路速度和定位球高度，属于必须复核的信息。",
            "早牌、点球和门将临场状态对单场杯赛影响很大，模型只能把它们计入不确定性区间。",
            f"{venue}的草皮、气温和旅途恢复会影响冲刺质量，尤其是下半场 60 分钟后的攻防转换。",
            "如果热门方压上过深且丢球点靠近中路，弱势方的一脚直塞或长传就可能制造单刀机会。",
        ],
        "key_matchups": [
            "边路推进速度 vs 边后卫回追能力：决定反击能否形成真正威胁。",
            "后腰保护面积 vs 对手前腰接球：决定禁区弧顶是否会被连续打穿。",
            "中卫第一落点 vs 中锋背身做球：决定长传和定位球能否延续进攻。",
            "门将出击选择 vs 对方传中质量：决定高空球压力能否被提前化解。",
            "替补席速度点 vs 疲劳防线：比赛末段可能成为胜负手。",
        ],
        "player_spotlight": player_analysis_cards(home, home_stars, home_detail) + player_analysis_cards(away, away_stars, away_detail),
        "player_performance": [
            f"{home}关键观察：{home_detail}",
            f"{home}重点球员：{'、'.join(home_stars) if home_stars else '官方名单未公布'}。",
            f"{away}关键观察：{away_detail}",
            f"{away}重点球员：{'、'.join(away_stars) if away_stars else '官方名单未公布'}。",
            "替补登场的速度型球员可能在 65 分钟后放大体能差异，是本场需要重点观察的临场变量。",
        ],
        "injury_impact": "暂无公布的伤停信息。",
        "player_status": {
            "home": {
                "team": home,
                "injuries": ["暂无公布的伤停信息。"],
                "doubtful": ["暂无公布的疑似缺阵信息。"],
                "key_players": public_player_list(home_stars),
            },
            "away": {
                "team": away,
                "injuries": ["暂无公布的伤停信息。"],
                "doubtful": ["暂无公布的疑似缺阵信息。"],
                "key_players": public_player_list(away_stars),
            },
        },
        "lineup_notes": {
            "home": "官方首发未发布，目前为预测版。",
            "away": "官方首发未发布，目前为预测版。",
            "uncertainty": "官方首发未发布，目前为预测版。",
        },
        "lineups": {
            "home": home_lineup,
            "away": away_lineup,
            "note": "官方首发未发布，目前为预测版。",
        },
        "match_conditions": [
            f"比赛场地：{venue}，赛地适应、旅行距离和恢复周期会影响下半场质量。",
            f"本场标签：{tags}，这些因素会被用于判断比赛节奏和爆冷区间。",
            "天气、草皮速度和风向会在可靠来源确认后进入最终版，当前先按中性条件处理。",
            "开球时间对应中国观赛时段较晚，但对参赛队真正影响取决于当地气温和湿度。",
            "如果裁判尺度偏松，身体对抗强的一方受益；如果尺度偏严，定位球和点球风险上升。",
        ],
        "upset_conditions": [
            f"{leader}久攻不下，射门质量下降，只能依赖远射和传中。",
            f"{follower}先守住前 30 分钟，并通过定位球或反击率先取得进球。",
            "热门方核心球员临场缺阵，导致中场推进和禁区终结同时降档。",
            "比赛进入高犯规、高中断节奏，强队连续进攻被切碎。",
            "门将或中卫出现一次重大失误，让原本清晰的胜负倾向被重置。",
        ],
        "data_confidence_note": "本报告为模型计算和已保存来源生成，赛前阵容公布后建议重新生成最终版。",
    }


def predicted_lineup(team: str, stars: list[str], shape: str, attacking: bool) -> dict[str, Any]:
    front_label = "右边锋" if attacking else "前锋"
    midfield_label = "中前卫"
    defense_label = "中卫"
    attacking_star = stars[0] if stars else "前腰"
    midfield_star = next((name for name in stars if any(token in name for token in ("中场", "后腰", "腰", "恩佐", "罗德里", "贝林厄姆", "阿尔瓦雷斯"))), midfield_label)
    defense_star = next((name for name in stars if any(token in name for token in ("中卫", "防线", "防空", "后卫"))), defense_label)
    keeper_star = next((name for name in stars if "门将" in name), "门将")
    return {
        "team": team,
        "formation": shape,
        "confidence": "预测",
        "players": [
            {"name": keeper_star, "role": "门将", "line": "GK"},
            {"name": "右后卫", "role": "右后卫", "line": "DEF"},
            {"name": defense_star, "role": defense_label, "line": "DEF"},
            {"name": "中卫搭档", "role": "中卫", "line": "DEF"},
            {"name": "左后卫", "role": "左后卫", "line": "DEF"},
            {"name": midfield_star, "role": midfield_label, "line": "MID"},
            {"name": "后腰", "role": "后腰", "line": "MID"},
            {"name": attacking_star, "role": "前腰", "line": "MID"},
            {"name": front_label, "role": front_label, "line": "FWD"},
            {"name": "中锋", "role": "中锋", "line": "FWD"},
            {"name": "左边锋", "role": "左边锋", "line": "FWD"},
        ],
        "note": "官方首发未发布，目前为预测版。",
    }


async def deepseek_report(
    bundle: dict[str, Any],
    prediction: dict[str, Any],
    reasoning_effort: str | None = None,
    thinking: str | None = None,
) -> dict[str, Any]:
    api_key = env("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")
    model = env("DEEPSEEK_MODEL", "deepseek-chat")
    sources = [
        {"topic": s["topic"], "title": s["title"], "snippet": s["snippet"], "url": s["url"]}
        for s in bundle["research_sources"][:8]
    ]
    prompt = {
        "match": {
            "home": bundle["home_name"],
            "away": bundle["away_name"],
            "kickoff": bundle["kickoff"],
            "venue": bundle["venue"],
            "tags": bundle["tags"],
            "home_key_players": bundle.get("home_profile", {}).get("stars", []),
            "away_key_players": bundle.get("away_profile", {}).get("stars", []),
        },
        "prediction": prediction,
        "sources": sources,
        "instruction": "请基于输入数据、模型已有足球知识和 sources 生成中文赛前分析，输出严格 JSON，字段为 summary, logic, score_prediction, totals_prediction, win_path, risk_points, key_matchups, player_spotlight, player_performance, injury_impact, player_status, lineup_notes, lineups, match_conditions, upset_conditions, data_confidence_note。logic 必须写得像模型计算说明，不要只说球队评分；需要具体解释 prediction.factors 中的球队基础评分、近期状态、攻防匹配、市场数据，以及 model_weights 的模型/市场权重如何共同推到最终胜平负概率；如果 odds_implied 有值，要说明胜平负概率已加权去水后的市场隐含概率，但不要写投注建议、赔率套利、收益等表述。score_prediction 包含 primary, alternatives, homeXg, awayXg, confidence, analysis；score_prediction.analysis 可以提到首选比分和备选比分，但不要写期望进球、概率、赔率或盘口，要从球队攻防、关键球员、比赛节奏解释为什么倾向这个比分。totals_prediction 包含 line, pick, displayPick, overProbability, underProbability, source, analysis，其中 line、overProbability、underProbability、source 只作为内部计算字段，analysis 里严禁出现盘口、赔率、Bet365、参考线、概率、大球概率、小球概率等字样，只能从球队攻防、关键球员、比赛节奏、伤停和赛前条件解释进球数倾向。player_spotlight 是数组，每项包含 team,name,role,impact，标题语义是“球员分析”；name 只能是真实球员名，严禁用反击第一推进点、中卫防空核心、门将出球点、边路爆点、核心持球点等位置/能力描述冒充球员名。player_status 中没有明确伤停来源时写“暂无公布的伤停信息。”和“暂无公布的疑似缺阵信息。”，不要写主力框架可用评估、检索不到明确缺口等内部判断。lineups 包含 home, away, note；home/away 各包含 team, formation, confidence, players, note；players 为 8 到 11 项，每项包含 name, role, line，line 只能是 GK/DEF/MID/FWD。阵容如果官方首发已经发布或 sources 明确提到，confidence 写“正式”；否则 confidence 写“预测”，但可以基于模型已有知识给出具体预测球员，不要只用位置名占位。lineups.note 和 home/away.note 要清楚标记“官方首发未发布，目前为预测版。”或“官方首发已发布，当前为正式版。”。未在输入、sources 或模型可靠知识中出现的伤停不得编造。",
    }
    thinking = thinking if thinking is not None else env("DEEPSEEK_THINKING", "enabled")
    reasoning_effort = reasoning_effort or env("DEEPSEEK_MATCH_REASONING_EFFORT", env("DEEPSEEK_REASONING_EFFORT", "medium"))
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是严谨的足球赛前数据分析师。不得编造未给出的事实。"},
            {"role": "user", "content": jdump(prompt)},
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
        "reasoning_effort": reasoning_effort,
    }
    if thinking:
        payload["thinking"] = {"type": thinking}
    async with httpx.AsyncClient(timeout=150) as client:
        response = await client.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        return json.loads(text)


def normalize_report_content(content: dict[str, Any], bundle: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    fallback = fallback_report(bundle, prediction)
    for key, value in fallback.items():
        if key not in content or content[key] in (None, "", [], {}):
            content[key] = value
    for key in ("score_prediction", "totals_prediction", "player_status", "lineup_notes", "lineups"):
        if not isinstance(content.get(key), dict):
            content[key] = fallback[key]
    content["score_prediction"] = {**fallback["score_prediction"], **content.get("score_prediction", {})}
    content["totals_prediction"] = {**fallback["totals_prediction"], **content.get("totals_prediction", {})}
    content["logic"] = enrich_logic_text(content.get("logic"), bundle, prediction)
    content["player_spotlight"] = [
        item
        for item in content.get("player_spotlight", [])
        if isinstance(item, dict) and str(item.get("name", "")).strip() and str(item.get("name", "")).strip() not in GENERIC_PLAYER_TERMS
    ]
    content["player_status"] = sanitize_player_status(content.get("player_status", {}), fallback["player_status"])
    content["lineup_notes"] = sanitize_lineup_notes(content.get("lineup_notes", {}), fallback["lineup_notes"])
    content["lineups"] = {**fallback["lineups"], **content.get("lineups", {})}
    content["lineups"]["note"] = clean_lineup_note(content["lineups"].get("note") or fallback["lineups"]["note"])
    for side in ("home", "away"):
        if not isinstance(content["lineups"].get(side), dict) or not content["lineups"][side].get("players"):
            content["lineups"][side] = fallback["lineups"][side]
        content["lineups"][side]["note"] = clean_lineup_note(content["lineups"][side].get("note") or fallback["lineups"][side]["note"])
        content["lineups"][side]["players"] = normalize_lineup_players(content["lineups"][side].get("players", []), fallback["lineups"][side]["players"])
    return content


def sanitize_lineup_notes(notes: Any, fallback_notes: dict[str, str]) -> dict[str, str]:
    if not isinstance(notes, dict):
        return fallback_notes
    result = {**fallback_notes}
    for key in ("home", "away", "uncertainty"):
        value = str(notes.get(key) or "").strip()
        result[key] = clean_lineup_note(value or fallback_notes.get(key, "官方首发未发布，目前为预测版。"))
    return result


def clean_lineup_note(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "官方首发未发布，目前为预测版。"
    banned = ("后台", "重新生成", "检索来源", "自动覆盖", "主力框架")
    if any(fragment in text for fragment in banned):
        return "官方首发未发布，目前为预测版。"
    return text


def sanitize_player_status(status: Any, fallback_status: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(status, dict):
        return fallback_status
    result = {**fallback_status, **status}
    for side in ("home", "away"):
        side_status = result.get(side) if isinstance(result.get(side), dict) else fallback_status.get(side, {})
        side_status["injuries"] = clean_public_list(side_status.get("injuries"), "暂无公布的伤停信息。")
        side_status["doubtful"] = clean_public_list(side_status.get("doubtful"), "暂无公布的疑似缺阵信息。")
        side_status["key_players"] = clean_public_list(side_status.get("key_players"), "官方名单未公布。")
        result[side] = side_status
    return result


def clean_public_list(values: Any, default: str) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return [default]
    cleaned = []
    banned_fragments = ("主力框架", "可用评估", "未检索到明确", "内部", "搜索来源", "后台")
    for value in values:
        text = str(value).strip()
        if not text or any(fragment in text for fragment in banned_fragments):
            continue
        cleaned.append(text)
    return cleaned or [default]


def normalize_lineup_players(players: Any, fallback_players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(players, list):
        return fallback_players
    normalized = []
    position_to_line = {
        "门将": "GK",
        "守门员": "GK",
        "右后卫": "DEF",
        "左后卫": "DEF",
        "中后卫": "DEF",
        "中卫": "DEF",
        "后卫": "DEF",
        "后腰": "MID",
        "中场": "MID",
        "前腰": "MID",
        "中前卫": "MID",
        "边前卫": "MID",
        "右边锋": "FWD",
        "左边锋": "FWD",
        "中锋": "FWD",
        "前锋": "FWD",
        "边锋": "FWD",
    }
    fallback_by_line = {}
    for fallback_player in fallback_players:
        fallback_by_line.setdefault(fallback_player.get("line", "MID"), []).append(fallback_player)
    used_by_line: dict[str, int] = {}
    for index, player in enumerate(players[:11]):
        if not isinstance(player, dict):
            player = {}
        raw_line = player.get("line")
        position = str(player.get("position") or "").strip()
        line = raw_line if raw_line in {"GK", "DEF", "MID", "FWD"} else position_to_line.get(position, "MID")
        used_by_line[line] = used_by_line.get(line, 0) + 1
        fallback_line = fallback_by_line.get(line, [])
        fallback_player = fallback_line[min(used_by_line[line] - 1, max(0, len(fallback_line) - 1))] if fallback_line else fallback_players[min(index, len(fallback_players) - 1)]
        role = str(player.get("role") or position or fallback_player.get("role") or "位置").strip()
        if role in GENERIC_PLAYER_TERMS:
            role = str(fallback_player.get("role") or line).strip()
        name = str(player.get("name") or fallback_player.get("name") or role).strip()
        if name in GENERIC_PLAYER_TERMS:
            name = role
        normalized.append({"name": name, "role": role, "line": line})
    return normalized or fallback_players


def save_prediction(conn: sqlite3.Connection, match_id: str, prediction: dict[str, Any]) -> None:
    conn.execute(
        """
        insert into predictions(match_id,home_win,draw,away_win,upset_index,confidence,factors_json,odds_implied_json,generated_at)
        values(?,?,?,?,?,?,?,?,?)
        on conflict(match_id) do update set
          home_win=excluded.home_win, draw=excluded.draw, away_win=excluded.away_win,
          upset_index=excluded.upset_index, confidence=excluded.confidence,
          factors_json=excluded.factors_json, odds_implied_json=excluded.odds_implied_json,
          generated_at=excluded.generated_at
        """,
        (
            match_id,
            prediction["home_win"],
            prediction["draw"],
            prediction["away_win"],
            prediction["upset_index"],
            prediction["confidence"],
            jdump(prediction["factors"]),
            jdump(prediction["odds_implied"]),
            now_iso(),
        ),
    )


def next_report_version(conn: sqlite3.Connection, match_id: str) -> int:
    row = conn.execute("select max(version) value from reports where match_id=?", (match_id,)).fetchone()
    return int(row["value"] or 0) + 1


def generate_match_report(
    match_id: str,
    publish: bool = False,
    use_deepseek: bool = True,
    reasoning_effort: str | None = None,
    thinking: str | None = None,
) -> dict[str, Any]:
    bundle = match_bundle(match_id)
    if use_deepseek and len(bundle.get("research_sources") or []) < 3:
        try:
            import anyio

            anyio.run(research_match_sources, match_id)
            bundle = match_bundle(match_id)
        except Exception as exc:
            log_event("research.match", "warning", f"Auto research failed: {exc}", match_id)
    prediction = calculate_prediction(bundle)
    content = None
    if use_deepseek:
        try:
            import anyio

            log_event("deepseek.generate", "start", "Calling DeepSeek for match report", match_id)
            started_at = time.perf_counter()
            content = anyio.run(deepseek_report, bundle, prediction, reasoning_effort, thinking)
            content = normalize_report_content(content, bundle, prediction)
            elapsed = time.perf_counter() - started_at
            log_event("deepseek.generate", "success", f"DeepSeek report generated in {elapsed:.1f}s", match_id)
        except Exception as exc:
            log_event("deepseek.generate", "warning", f"DeepSeek failed, using fallback: {type(exc).__name__}: {exc!r}", match_id)
    if not content:
        content = fallback_report(bundle, prediction)
    with db() as conn:
        save_prediction(conn, match_id, prediction)
        version = next_report_version(conn, match_id)
        report_id = f"{match_id}-v{version}"
        status = "published" if publish else "draft"
        if publish:
            conn.execute("update reports set status='archived' where match_id=? and status='published'", (match_id,))
        conn.execute(
            "insert into reports(id,match_id,version,status,content_json,sources_json,created_at,published_at) values(?,?,?,?,?,?,?,?)",
            (
                report_id,
                match_id,
                version,
                status,
                jdump(content),
                jdump(bundle["research_sources"]),
                now_iso(),
                now_iso() if publish else None,
            ),
        )
    log_event("report.generate", "success", f"Generated report {report_id}", match_id)
    return {"report_id": report_id, "status": status, "prediction": prediction, "content": content}


async def deepseek_champion_analyses(
    entries: list[dict[str, Any]],
    reasoning_effort: str | None = None,
    thinking: str | None = None,
) -> dict[str, str]:
    api_key = env("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")
    model = env("DEEPSEEK_MODEL", "deepseek-chat")
    selected_entries = entries[: int(env("DEEPSEEK_CHAMPION_ANALYSIS_LIMIT", "6"))]
    effort = reasoning_effort or env("DEEPSEEK_CHAMPION_REASONING_EFFORT", "low")
    thinking = thinking if thinking is not None else env("DEEPSEEK_THINKING", "enabled")
    semaphore = asyncio.Semaphore(3)

    async def generate_one(client: httpx.AsyncClient, entry: dict[str, Any]) -> tuple[str, str]:
        prompt = {
            "team": entry["team"],
            "code": entry["code"],
            "championProbability": entry["championProbability"],
            "modelProbability": entry.get("modelProbability"),
            "tier": entry["tier"],
            "modelFactors": entry.get("modelFactors", {}),
            "instruction": "为这支球队生成 4 到 5 句中文冠军前景分析，输出严格 JSON：{\"analysis\":\"...\"}。不要出现高于基准、低于基准、价值、赔率、市场、模型概率、评分、具体数值、小数等词；不要编造具体伤停；260 到 360 个中文字符，基于攻防平衡、近期状态、淘汰赛容错、阵容厚度、优势位置、小组压力和潜在风险展开。评分数字会由页面单独展示，分析只写足球层面的解释。",
        }
        request_payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是面向普通球迷的世界杯赛前分析编辑，表达清楚、克制，不编造事实。"},
                {"role": "user", "content": jdump(prompt)},
            ],
            "response_format": {"type": "json_object"},
            "stream": False,
            "reasoning_effort": effort,
        }
        if thinking:
            request_payload["thinking"] = {"type": thinking}
        async with semaphore:
            response = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=request_payload,
            )
        response.raise_for_status()
        data = json.loads(response.json()["choices"][0]["message"]["content"])
        return entry["code"], str(data.get("analysis", "")).strip()

    async with httpx.AsyncClient(timeout=18) as client:
        results = await asyncio.gather(*(generate_one(client, entry) for entry in selected_entries), return_exceptions=True)
    analyses: dict[str, str] = {}
    for result in results:
        if isinstance(result, Exception):
            continue
        code, analysis = result
        if code and analysis:
            analyses[code] = analysis
    return analyses


def generate_champion_prediction(
    publish: bool = False,
    use_deepseek: bool = False,
    reasoning_effort: str | None = None,
    thinking: str | None = None,
) -> dict[str, Any]:
    with db() as conn:
        teams = conn.execute("select * from teams order by rating desc").fetchall()
        current = conn.execute("select max(version) value from champion_predictions").fetchone()
        version = int(current["value"] or 0) + 1
        raw_entries = []
        for team in teams:
            rating = float(team["rating"])
            stats = conn.execute("select form_score,attack_score,defense_score from team_stats where team_id=?", (team["id"],)).fetchone()
            form = float(stats["form_score"] if stats else 5.5)
            attack = float(stats["attack_score"] if stats else 5.5)
            defense = float(stats["defense_score"] if stats else 5.5)
            balance = 1 + (form - 5.8) * 0.05 + (attack - 5.8) * 0.04 + (defense - 5.8) * 0.035
            knockout_resilience = 1 + min(0.16, max(-0.14, (defense - 5.7) * 0.035 + (rating - 1600) / 2600))
            attacking_ceiling = 1 + min(0.16, max(-0.12, (attack - 5.8) * 0.045))
            volatility_penalty = 1 - min(0.12, max(0, abs(attack - defense) - 1.4) * 0.025)
            rng = random.Random(f"{team['id']}-{version}")
            market_odds = MARKET_OUTRIGHT_ODDS.get(team["code"])
            market = 1 / market_odds if market_odds else math.exp((rating - 1540) / 145) * 0.012
            model_signal = (
                math.exp((rating - 1540) / 102)
                * max(0.68, balance)
                * knockout_resilience
                * attacking_ceiling
                * volatility_penalty
                * rng.uniform(0.96, 1.04)
            )
            raw_entries.append(
                {
                    "team": team["name"],
                    "code": team["code"],
                    "market": market,
                    "modelSignal": model_signal,
                    "marketOdds": market_odds,
                    "modelFactors": {
                        "rating": rating,
                        "form": form,
                        "attack": attack,
                        "defense": defense,
                        "knockoutResilience": round(knockout_resilience, 3),
                        "attackingCeiling": round(attacking_ceiling, 3),
                    },
                }
            )
        market_total = sum(e["market"] for e in raw_entries) or 1
        model_total = sum(e["modelSignal"] for e in raw_entries) or 1
        entries = []
        for entry in raw_entries:
            market = round(entry["market"] / market_total * 100, 1)
            model_probability = entry["modelSignal"] / model_total * 100
            combined = round(model_probability * 0.6 + market * 0.4, 1)
            entries.append(
                {
                    "team": entry["team"],
                    "code": entry["code"],
                    "championProbability": combined,
                    "modelProbability": round(model_probability, 1),
                    "marketImplied": market,
                    "marketOdds": entry["marketOdds"],
                    "edge": round(combined - market, 1),
                    "tag": "热门" if combined >= 8 else ("追赶者" if combined >= 3.5 else "观察"),
                    "tier": champion_tier(combined),
                    "modelFactors": entry["modelFactors"],
                    "modelSummary": champion_model_summary(entry["modelFactors"], round(model_probability, 1), combined),
                    "analysis": champion_analysis(entry["team"], combined, market),
                }
            )
        entries.sort(key=lambda item: item["championProbability"], reverse=True)
        if use_deepseek:
            try:
                import anyio

                log_event("deepseek.champion", "start", "Calling DeepSeek for champion analyses")
                started_at = time.perf_counter()
                analyses = anyio.run(deepseek_champion_analyses, entries, reasoning_effort, thinking)
                for entry in entries:
                    if analyses.get(entry["code"]):
                        entry["analysis"] = analyses[entry["code"]]
                elapsed = time.perf_counter() - started_at
                log_event("deepseek.champion", "success", f"DeepSeek champion analyses generated in {elapsed:.1f}s")
            except Exception as exc:
                log_event("deepseek.champion", "warning", f"DeepSeek failed, using fallback: {type(exc).__name__}: {exc!r}")
        status = "published" if publish else "draft"
        if publish:
            conn.execute("update champion_predictions set status='archived' where status='published'")
        conn.execute(
            "insert into champion_predictions(version,status,entries_json,generated_at,published_at) values(?,?,?,?,?)",
            (version, status, jdump(entries), now_iso(), now_iso() if publish else None),
        )
    log_event("champion.generate", "success", f"Generated champion prediction v{version}")
    return {"version": version, "status": status, "entries": entries}


def champion_analysis(team: str, model: float, baseline: float) -> str:
    profile = next((TEAM_PLAYER_PROFILES.get(seed[2], {}) for seed in seed_teams() if seed[1] == team), {})
    stars = profile.get("stars") or ["核心球员", "中场骨干", "防线核心"]
    strength = (profile.get("strength") or "整体攻防平衡和临场阵容完整度").replace("是核心优势", "")
    detail = profile.get("detail") or f"{stars[0]}、{stars[1]}和{stars[2]}若保持健康，会分别影响进攻发起、中场稳定和防守容错。"
    if model >= 8:
        return f"{team}处在争冠第一梯队，主要底盘来自{strength}。{detail}他们的优势不是单点爆发，而是能在不同比赛节奏里找到解决方案：领先时可以依靠中后场控制局面，落后时也有足够的前场变化制造压力。进入淘汰赛后，阵容厚度和关键球员临场状态会决定他们能否连续处理高强度对抗。真正的风险在于热门球队往往会被针对，如果边路推进或中场衔接被压制，就需要替补席给出新的破局方式。"
    if model >= 5:
        return f"{team}属于稳定争冠区，小组赛路径如果顺利，四强上限值得关注。{detail}这类球队通常不缺比赛计划，关键是把优势位置转化成持续压制，而不是只依赖个别球星的瞬间处理。他们需要减少无谓失误，把优势集中在关键位置的对位质量上。若淘汰赛遇到节奏更慢、防线更密的对手，定位球、二点球保护和替补冲击力会成为决定上限的细节。"
    if model >= 3:
        return f"{team}具备冲击深轮次的基础，但容错率略低于顶级热门。{detail}他们的争冠路径更依赖小组赛开局质量，如果能够尽早拿到主动权，后续淘汰赛压力会明显下降。面对强队时，他们需要把比赛拖进自己熟悉的节奏，减少开放式对攻带来的防线暴露。如果淘汰赛抽签友好，核心球员健康、定位球效率和门前把握能力会显著抬高上限。"
    if model >= 1.5:
        return f"{team}更像潜在搅局者，防守稳定性和定位球效率会决定能走多远。{detail}他们很难长期压制顶级热门，因此更需要控制失误、降低比赛回合数，并把有限的进攻机会打得更直接。小组赛阶段如果能抢到有利排名，淘汰赛就有机会避开过早的强强对话。他们需要先把比赛压到自己舒服的节奏，再等待反击、定位球或关键球员个人能力带来的窗口。"
    if model >= baseline:
        return f"{team}整体机会不高，但晋级路径仍有一定想象空间。{detail}他们需要先保证小组赛不被早早拉开差距，再通过防守组织和转换效率寻找爆冷机会。面对更强对手时，中后场抗压能力和门将表现会被放大，任何一次定位球或反击都可能改变晋级形势。如果小组赛能抢到有利排名，后续才有机会把防守韧性转化为更深轮次的资本。"
    return f"{team}首先要解决小组出线压力，冠军路径需要连续爆冷。{detail}对他们来说，关键不是大开大合，而是尽量降低失误并抓住少数高质量机会。小组赛阶段需要把比赛切成更细的目标：先稳住防守，再争取定位球、反击和替补球员带来的局部优势。只有在前两场拿到足够积分后，他们才有空间把比赛策略从保守推进转向更主动的淘汰赛冲击。"


def champion_model_summary(factors: dict[str, Any], model_probability: float, combined_probability: float) -> list[dict[str, str]]:
    return [
        {"label": "综合概率", "value": f"{combined_probability:.1f}%"},
        {"label": "模型概率", "value": f"{model_probability:.1f}%"},
        {"label": "球队评分", "value": f"{float(factors.get('rating', 0)):.0f}"},
        {"label": "近期状态", "value": f"{float(factors.get('form', 0)):.1f}"},
        {"label": "进攻评分", "value": f"{float(factors.get('attack', 0)):.1f}"},
        {"label": "防守评分", "value": f"{float(factors.get('defense', 0)):.1f}"},
        {"label": "淘汰赛韧性", "value": f"{float(factors.get('knockoutResilience', 1)):.3f}"},
        {"label": "进攻上限", "value": f"{float(factors.get('attackingCeiling', 1)):.3f}"},
    ]


def champion_tier(model: float) -> str:
    if model >= 7:
        return "争冠热门"
    if model >= 4:
        return "四强竞争者"
    if model >= 1.8:
        return "潜在黑马"
    return "小组出线优先"


def public_match(row: sqlite3.Row) -> dict[str, Any]:
    day_key = matchday_key(row["kickoff"])
    return {
        "id": row["id"],
        "home": row["home_name"],
        "away": row["away_name"],
        "homeCode": row["home_code"],
        "awayCode": row["away_code"],
        "kickoff": row["kickoff"],
        "group": row["group_name"],
        "venue": row["venue"],
        "status": row["status"],
        "matchday": day_key,
        "matchdayLabel": matchday_label(day_key),
        "tags": jload(row["tags_json"], []),
        "probabilities": {
            "home": row["home_win"],
            "draw": row["draw"],
            "away": row["away_win"],
        },
        "upsetIndex": row["upset_index"],
        "confidence": row["confidence"],
        "hasPublishedReport": bool(row["report_id"]),
        "updatedAt": row["generated_at"],
    }


def query_public_matches() -> list[sqlite3.Row]:
    with db() as conn:
        return conn.execute(
            """
            select m.*, ht.name home_name, ht.code home_code, at.name away_name, at.code away_code,
                   p.home_win, p.draw, p.away_win, p.upset_index, p.confidence, p.generated_at,
                   r.id report_id
            from matches m
            join teams ht on ht.id=m.home_team_id
            join teams at on at.id=m.away_team_id
            left join predictions p on p.match_id=m.id
            left join reports r on r.match_id=m.id and r.status='published'
            order by m.kickoff asc
            """
        ).fetchall()


def grouped_matchdays(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        item = public_match(row)
        groups.setdefault(item["matchday"], []).append(item)
    return [
        {
            "matchday": key,
            "label": matchday_label(key),
            "range": matchday_range(key),
            "items": groups[key],
        }
        for key in sorted(groups)
    ]


def nearest_matchday(rows: list[sqlite3.Row]) -> dict[str, Any] | None:
    groups = grouped_matchdays(rows)
    if not groups:
        return None
    now = datetime.now(CN_TZ)
    upcoming = [
        group
        for group in groups
        if parse_dt(group["range"]["end"]).astimezone(CN_TZ) >= now
    ]
    return upcoming[0] if upcoming else groups[-1]


def nearest_matchday_scope() -> dict[str, Any]:
    group = nearest_matchday(query_public_matches())
    if not group:
        return {"matchday": None, "label": "暂无赛事", "items": []}
    return group


def schedule_groups() -> list[dict[str, Any]]:
    with db() as conn:
        team_rows = conn.execute("select id,name,code from teams").fetchall()
    team_map = {row["id"]: {"name": row["name"], "code": row["code"]} for row in team_rows}
    return [
        {
            "group": group_name,
            "teams": [
                {
                    "name": team_map[team_id]["name"],
                    "code": team_map[team_id]["code"],
                    "played": 0,
                    "wins": 0,
                    "draws": 0,
                    "losses": 0,
                    "points": 0,
                }
                for team_id in team_ids
                if team_id in team_map
            ],
        }
        for group_name, team_ids in seed_group_map().items()
    ]


def seeded_bracket() -> list[dict[str, Any]]:
    return [
        {
            "round": "32 强",
            "ties": [
                {"slot": f"R32-{index + 1}", "home": home, "away": away}
                for index, (home, away) in enumerate(
                    [
                        ("A组第1", "最佳第三名8"),
                        ("B组第1", "最佳第三名7"),
                        ("C组第1", "D组第2"),
                        ("D组第1", "C组第2"),
                        ("E组第1", "F组第2"),
                        ("F组第1", "E组第2"),
                        ("G组第1", "H组第2"),
                        ("H组第1", "G组第2"),
                    ]
                )
            ],
        },
        {
            "round": "16 强",
            "ties": [{"slot": f"R16-{index + 1}", "home": f"R32-{index * 2 + 1} 胜者", "away": f"R32-{index * 2 + 2} 胜者"} for index in range(4)],
        },
        {
            "round": "8 强",
            "ties": [{"slot": f"QF-{index + 1}", "home": f"R16-{index * 2 + 1} 胜者", "away": f"R16-{index * 2 + 2} 胜者"} for index in range(2)],
        },
        {"round": "半决赛", "ties": [{"slot": "SF-1", "home": "QF-1 胜者", "away": "QF-2 胜者"}]},
        {"round": "决赛", "ties": [{"slot": "Final", "home": "SF-1 胜者", "away": "另一半区胜者"}]},
    ]


def app_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(lambda: log_event("scheduler.tick", "success", "Scheduler heartbeat"), "interval", hours=6, id="scheduler_heartbeat", replace_existing=True)
    for definition in JOB_DEFINITIONS:
        schedule_job_from_config(scheduler, definition, job_config(definition["id"]))
    return scheduler


@asynccontextmanager
async def lifespan(_: FastAPI):
    global SCHEDULER
    init_db()
    scheduler = app_scheduler()
    SCHEDULER = scheduler
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        SCHEDULER = None


app = FastAPI(title="世界杯观赛助手 API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "db": str(DB_PATH),
        "configured": {
            "apiFootball": bool(env("API_FOOTBALL_KEY")),
            "sportmonks": bool(env("SPORTMONKS_API_TOKEN")),
            "serper": bool(env("SERPER_API_KEY")),
            "deepseek": bool(env("DEEPSEEK_API_KEY")),
        },
    }


@app.get("/api/admin/page-session")
def admin_page_session(request: Request) -> dict[str, Any]:
    return {"authenticated": is_admin_page_authenticated(request)}


@app.post("/api/admin/page-login")
def admin_page_login(response: Response, payload: dict[str, str] = Body(default_factory=dict)) -> dict[str, Any]:
    password = str(payload.get("password") or "")
    if not hmac.compare_digest(password, admin_page_password()):
        raise HTTPException(status_code=401, detail="进入密码错误")
    response.set_cookie(
        "wc_admin_page",
        admin_page_auth_token(),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,
    )
    return {"ok": True}


@app.get("/api/matches/today")
def matches_today() -> dict[str, Any]:
    rows = query_public_matches()
    return {"items": [public_match(row) for row in rows]}


@app.get("/api/matches/nearest-day")
def matches_nearest_day() -> dict[str, Any]:
    rows = query_public_matches()
    group = nearest_matchday(rows)
    if not group:
        return {"status": "empty", "matchday": None, "items": []}
    return {"status": "ok", **group}


@app.get("/api/matches/upcoming")
def matches_upcoming() -> dict[str, Any]:
    groups = grouped_matchdays(query_public_matches())
    now = datetime.now(CN_TZ)
    upcoming = [
        group
        for group in groups
        if parse_dt(group["range"]["end"]).astimezone(CN_TZ) >= now
    ]
    return {"items": upcoming}


@app.get("/api/schedule/groups")
def schedule_groups_api() -> dict[str, Any]:
    return {"items": schedule_groups()}


@app.get("/api/schedule/calendar")
def schedule_calendar_api() -> dict[str, Any]:
    return {"items": grouped_matchdays(query_public_matches())}


@app.get("/api/schedule/bracket")
def schedule_bracket_api() -> dict[str, Any]:
    return {"items": seeded_bracket()}


@app.get("/api/matches/{match_id}/report")
def match_report(match_id: str) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute(
            """
            select m.*, ht.name home_name, ht.code home_code, at.name away_name, at.code away_code,
                   p.*, r.id report_id, r.version, r.content_json, r.sources_json, r.published_at
            from matches m
            join teams ht on ht.id=m.home_team_id
            join teams at on at.id=m.away_team_id
            left join predictions p on p.match_id=m.id
            left join reports r on r.match_id=m.id and r.status='published'
            where m.id=?
            """,
            (match_id,),
        ).fetchone()
        odds = latest_odds(conn, match_id)
    if not row:
        raise HTTPException(status_code=404, detail="Match not found")
    if not row["report_id"]:
        return {"status": "unpublished", "match": public_match(row)}
    return {
        "status": "published",
        "match": public_match(row),
        "report": {
            "id": row["report_id"],
            "version": row["version"],
            "publishedAt": row["published_at"],
            "content": jload(row["content_json"], {}),
            "sources": jload(row["sources_json"], []),
            "factors": jload(row["factors_json"], []),
            "oddsImplied": jload(row["odds_implied_json"], {}),
            "odds": jload(odds["odds_json"], {}) if odds else {},
            "bookmaker": odds["bookmaker"] if odds else None,
        },
    }


wechat_article.configure(
    env_func=env,
    db_func=db,
    jdump_func=jdump,
    jload_func=jload,
    now_iso_func=now_iso,
    log_event_func=log_event,
    query_public_matches_func=query_public_matches,
    grouped_matchdays_func=grouped_matchdays,
    match_report_func=match_report,
)


@app.get("/api/tournament/champion-prediction")
def champion_prediction() -> dict[str, Any]:
    with db() as conn:
        row = conn.execute(
            "select * from champion_predictions where status='published' order by version desc limit 1"
        ).fetchone()
    if not row:
        return {"status": "unpublished", "items": []}
    return {
        "status": "published",
        "version": row["version"],
        "generatedAt": row["generated_at"],
        "items": jload(row["entries_json"], []),
    }


@app.get("/api/admin/matches", dependencies=[Depends(require_admin)])
def admin_matches() -> dict[str, Any]:
    with db() as conn:
        rows = conn.execute(
            """
            select m.id, ht.name home, at.name away, m.kickoff, m.status,
                   p.generated_at prediction_generated_at,
                   r.id published_report_id
            from matches m
            join teams ht on ht.id=m.home_team_id
            join teams at on at.id=m.away_team_id
            left join predictions p on p.match_id=m.id
            left join reports r on r.match_id=m.id and r.status='published'
            order by m.kickoff asc
            """
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.get("/api/admin/matchdays", dependencies=[Depends(require_admin)])
def admin_matchdays() -> dict[str, Any]:
    groups = grouped_matchdays(query_public_matches())
    return {
        "items": [
            {
                "matchday": group["matchday"],
                "label": group["label"],
                "range": group["range"],
                "count": len(group.get("items") or []),
            }
            for group in groups
        ]
    }


@app.get("/api/admin/logs", dependencies=[Depends(require_admin)])
def admin_logs(limit: int = 80) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    with db() as conn:
        rows = conn.execute(
            "select action,target_id,status,message,created_at from generation_logs order by id desc limit ?",
            (limit,),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.get("/api/admin/jobs", dependencies=[Depends(require_admin)])
def admin_jobs() -> dict[str, Any]:
    scheduler_jobs = {job.id: job for job in SCHEDULER.get_jobs()} if SCHEDULER else {}
    with db() as conn:
        rows = conn.execute(
            """
            select r.*
            from scheduled_job_runs r
            join (
              select job_id, max(id) id
              from scheduled_job_runs
              group by job_id
            ) latest on latest.id=r.id
            """
        ).fetchall()
    latest_runs = {row["job_id"]: dict(row) for row in rows}
    items = []
    for definition in JOB_DEFINITIONS:
        scheduler_job = scheduler_jobs.get(definition["id"])
        latest = latest_runs.get(definition["id"])
        config = job_config(definition["id"])
        items.append(
            {
                "id": definition["id"],
                "name": definition["name"],
                "trigger": describe_job_config(config),
                "description": definition["description"],
                "config": config,
                "status": latest["status"] if latest else "waiting",
                "lastRunAt": latest["started_at"] if latest else None,
                "lastFinishedAt": latest["finished_at"] if latest else None,
                "lastDurationSeconds": latest["duration_seconds"] if latest else None,
                "lastMessage": latest["message"] if latest else "尚未运行",
                "nextRunAt": scheduler_job.next_run_time.isoformat() if scheduler_job and scheduler_job.next_run_time else None,
            }
        )
    return {"items": items}


@app.put("/api/admin/jobs/{job_id}/config", dependencies=[Depends(require_admin)])
def admin_update_job_config(job_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    config = validate_job_config(payload)
    save_job_config(job_id, config)
    apply_job_config(job_id)
    log_event("scheduler.config", "success", f"Updated schedule: {describe_job_config(config)}", job_id)
    scheduler_job = SCHEDULER.get_job(job_id) if SCHEDULER else None
    return {
        "ok": True,
        "jobId": job_id,
        "config": config,
        "trigger": describe_job_config(config),
        "nextRunAt": scheduler_job.next_run_time.isoformat() if scheduler_job and scheduler_job.next_run_time else None,
    }


@app.post("/api/admin/jobs/{job_id}/run", dependencies=[Depends(require_admin)])
def admin_run_job(job_id: str) -> dict[str, Any]:
    return run_scheduled_job(job_id, manual=True)


@app.get("/api/admin/data-status", dependencies=[Depends(require_admin)])
def admin_data_status() -> dict[str, Any]:
    refresh_computed_data_status()
    with db() as conn:
        rows = conn.execute(
            "select key,label,status,updated_at,summary,source,detail_json from data_status order by key asc"
        ).fetchall()
    return {"items": [{**dict(row), "detail": jload(row["detail_json"], {})} for row in rows]}


@app.get("/api/admin/wechat/articles", dependencies=[Depends(require_admin)])
def admin_wechat_articles() -> dict[str, Any]:
    with db() as conn:
        rows = conn.execute("select * from wechat_articles order by created_at desc limit 80").fetchall()
    return {"items": [wechat_article.article_row_to_dict(row) for row in rows]}


@app.get("/api/admin/wechat/articles/{article_id}", dependencies=[Depends(require_admin)])
def admin_wechat_article_detail(article_id: str) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("select * from wechat_articles where id=?", (article_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="WeChat article not found")
    return wechat_article.article_row_to_dict(row, include_body=True)


@app.post("/api/admin/wechat/daily-preview/generate", dependencies=[Depends(require_admin)])
def admin_generate_wechat_daily_preview(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    matchday = str(payload.get("matchday") or "").strip()
    force = bool(payload.get("force", False))
    if not matchday:
        groups = grouped_matchdays(query_public_matches())
        group = next((item for item in groups if item.get("items")), None)
        if not group:
            raise HTTPException(status_code=404, detail="No matchday available")
        matchday = group["matchday"]
    if not force:
        with db() as conn:
            row = conn.execute(
                """
                select * from wechat_articles
                where article_type='daily_preview' and matchday=? and status in ('generated','draft_pushed')
                order by version desc limit 1
                """,
                (matchday,),
            ).fetchone()
        if row:
            return wechat_article.article_row_to_dict(row, include_body=True)
    try:
        source = wechat_article.build_daily_preview_source(matchday)
        article = wechat_article.generate_daily_preview_article(source)
        fact_check = wechat_article.fact_check_wechat_article(source, article)
        saved = wechat_article.save_daily_preview_article(source, article, fact_check)
        log_event("wechat.article", saved["status"], f"Generated WeChat daily preview {saved['id']}", matchday)
        return saved
    except Exception as exc:
        log_event("wechat.article", "error", f"Generate daily preview failed: {type(exc).__name__}: {exc}", matchday)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/admin/wechat/articles/{article_id}/push-draft", dependencies=[Depends(require_admin)])
def admin_push_wechat_draft(article_id: str) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("select * from wechat_articles where id=?", (article_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="WeChat article not found")
    if row["status"] == "fact_failed":
        raise HTTPException(status_code=400, detail=row["error_message"] or "Fact check failed")
    if row["status"] == "draft_pushed":
        return wechat_article.article_row_to_dict(row, include_body=True)
    try:
        result = wechat_article.push_wechat_draft(dict(row))
        media_id = result.get("media_id")
        with db() as conn:
            conn.execute(
                "update wechat_articles set status=?, wechat_media_id=?, pushed_at=?, error_message=null where id=?",
                ("draft_pushed", media_id, now_iso(), article_id),
            )
            updated = conn.execute("select * from wechat_articles where id=?", (article_id,)).fetchone()
        log_event("wechat.draft", "success", f"Pushed WeChat draft {media_id}", article_id)
        return wechat_article.article_row_to_dict(updated, include_body=True)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        with db() as conn:
            conn.execute("update wechat_articles set status=?, error_message=? where id=?", ("failed", message, article_id))
        log_event("wechat.draft", "error", message, article_id)
        raise HTTPException(status_code=500, detail=message) from exc


@app.post("/api/admin/sync/fixtures", dependencies=[Depends(require_admin)])
async def admin_sync_fixtures() -> dict[str, Any]:
    if not env("API_FOOTBALL_KEY"):
        log_event("sync.fixtures", "error", "API_FOOTBALL_KEY is not configured")
        raise HTTPException(status_code=400, detail="API_FOOTBALL_KEY is not configured")
    log_event("sync.fixtures", "success", "Fixture sync provider is configured; mapping implementation ready")
    return {"ok": True, "message": "API-FOOTBALL provider configured. Extend provider mapping for target competition IDs."}


@app.post("/api/admin/sync/odds", dependencies=[Depends(require_admin)])
async def admin_sync_odds() -> dict[str, Any]:
    if not env("SPORTMONKS_API_TOKEN"):
        log_event("sync.odds", "error", "SPORTMONKS_API_TOKEN is not configured")
        raise HTTPException(status_code=400, detail="SPORTMONKS_API_TOKEN is not configured")
    log_event("sync.odds", "success", "Odds sync provider is configured; mapping implementation ready")
    return {"ok": True, "message": "Sportmonks provider configured. Extend bookmaker/market mapping for production odds."}


@app.post("/api/admin/matches/{match_id}/research", dependencies=[Depends(require_admin)])
async def admin_research_match(match_id: str) -> dict[str, Any]:
    if not env("SERPER_API_KEY"):
        log_event("research.match", "error", "SERPER_API_KEY is not configured", match_id)
        raise HTTPException(status_code=400, detail="SERPER_API_KEY is not configured")
    saved = await research_match_sources(match_id)
    return {"ok": True, "saved": saved}


@app.post("/api/admin/matches/{match_id}/generate", dependencies=[Depends(require_admin)])
def admin_generate_match(
    match_id: str,
    publish: bool = False,
    reasoning_effort: str = "high",
    thinking: str = "enabled",
) -> dict[str, Any]:
    return generate_match_report(match_id, publish=publish, use_deepseek=True, reasoning_effort=reasoning_effort, thinking=thinking)


@app.post("/api/admin/matches/generate-nearest-day", dependencies=[Depends(require_admin)])
def admin_generate_nearest_day(
    publish: bool = False,
    use_deepseek: bool = True,
    reasoning_effort: str = "high",
    thinking: str = "enabled",
) -> dict[str, Any]:
    group = nearest_matchday_scope()
    generated = []
    for item in group["items"]:
        result = generate_match_report(
            item["id"],
            publish=publish,
            use_deepseek=use_deepseek,
            reasoning_effort=reasoning_effort,
            thinking=thinking,
        )
        generated.append({"matchId": item["id"], "reportId": result["report_id"], "status": result["status"]})
    log_event(
        "generate.nearest_day",
        "success",
        f"Generated {len(generated)} reports for {group['label']}",
        group.get("matchday"),
    )
    return {
        "ok": True,
        "scope": "nearest-day",
        "matchday": group.get("matchday"),
        "label": group["label"],
        "count": len(generated),
        "items": generated,
    }


@app.post("/api/admin/matches/generate-all", dependencies=[Depends(require_admin)])
def admin_generate_all_matches(
    publish: bool = False,
    use_deepseek: bool = True,
    limit: int = 72,
    reasoning_effort: str = "high",
    thinking: str = "enabled",
) -> dict[str, Any]:
    match_rows = seed_match_rows()[: max(1, min(limit, 72))]
    generated = []
    for row in match_rows:
        result = generate_match_report(
            row[0],
            publish=publish,
            use_deepseek=use_deepseek,
            reasoning_effort=reasoning_effort,
            thinking=thinking,
        )
        generated.append({"matchId": row[0], "reportId": result["report_id"], "status": result["status"]})
    return {"ok": True, "count": len(generated), "items": generated}


@app.post("/api/admin/tournament/generate-champion-prediction", dependencies=[Depends(require_admin)])
def admin_generate_champion(
    publish: bool = False,
    use_deepseek: bool = True,
    reasoning_effort: str = "high",
    thinking: str = "enabled",
) -> dict[str, Any]:
    return generate_champion_prediction(publish=publish, use_deepseek=use_deepseek, reasoning_effort=reasoning_effort, thinking=thinking)


@app.post("/api/admin/reports/{report_id}/publish", dependencies=[Depends(require_admin)])
def admin_publish_report(report_id: str) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("select * from reports where id=?", (report_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Report not found")
        conn.execute("update reports set status='archived' where match_id=? and status='published'", (row["match_id"],))
        conn.execute("update reports set status='published', published_at=? where id=?", (now_iso(), report_id))
    log_event("report.publish", "success", f"Published {report_id}", report_id)
    return {"ok": True, "reportId": report_id}


@app.post("/api/admin/reports/{report_id}/unpublish", dependencies=[Depends(require_admin)])
def admin_unpublish_report(report_id: str) -> dict[str, Any]:
    with db() as conn:
        conn.execute("update reports set status='draft', published_at=null where id=?", (report_id,))
    log_event("report.unpublish", "success", f"Unpublished {report_id}", report_id)
    return {"ok": True, "reportId": report_id}


@app.get("/admin", response_class=HTMLResponse)
def admin_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "admin.html")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/{path:path}")
def static_fallback(path: str, request: Request) -> FileResponse:
    target = FRONTEND_DIR / path
    if target.is_file():
        return FileResponse(target)
    return FileResponse(FRONTEND_DIR / "index.html")
