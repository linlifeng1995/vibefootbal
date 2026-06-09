from __future__ import annotations

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
HERO_IMAGE = ROOT / "assets" / "wechat-style-test-hero-baked.jpg"
SOURCE_URL = "http://140.143.182.236/worldcup/"


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def access_token() -> str:
    response = httpx.get(
        "https://api.weixin.qq.com/cgi-bin/token",
        params={"grant_type": "client_credential", "appid": env("WECHAT_APP_ID"), "secret": env("WECHAT_APP_SECRET")},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("errcode"):
        raise RuntimeError(f"WeChat token error: {data}")
    return str(data["access_token"])


def upload_content_image(token: str, image_path: Path) -> str:
    with image_path.open("rb") as image_file:
        response = httpx.post(
            "https://api.weixin.qq.com/cgi-bin/media/uploadimg",
            params={"access_token": token},
            files={"media": (image_path.name, image_file, "image/jpeg")},
            timeout=30,
        )
    response.raise_for_status()
    data = response.json()
    if data.get("errcode"):
        raise RuntimeError(f"WeChat image upload error: {data}")
    return str(data["url"])


def block(title: str, body: str, *, color: str = "#f6c35b", border: bool = True, compact: bool = False) -> str:
    border_style = f"border:1px solid rgba(246,195,91,0.22);" if border else "border-left:3px solid rgba(246,195,91,0.72);"
    pad = "14px 14px 15px" if compact else "17px 16px 18px"
    margin = "10px 0 0" if compact else "12px 0 0"
    radius = "border-radius:10px;" if border else "border-radius:0;"
    return f"""
    <section style="margin:{margin};padding:{pad};{border_style}{radius}background:rgba(255,255,255,0.052);">
      <p style="margin:0 0 8px;color:{color};font-size:14px;line-height:1.45;font-weight:900;">{title}</p>
      <p style="margin:0;color:#c9d2cf;font-size:15px;line-height:1.82;">{body}</p>
    </section>
    """


def match_header_a() -> str:
    return """
    <section style="margin:0 0 14px;padding:0 0 14px;border-bottom:1px solid rgba(255,255,255,0.14);">
      <p style="margin:0 0 6px;color:#f6c35b;font-size:26px;line-height:1.05;font-weight:900;">03:00</p>
      <p style="margin:0;color:#ffffff;font-size:20px;line-height:1.45;font-weight:900;">墨西哥 vs 南非</p>
      <p style="margin:2px 0 0;color:#9faaa7;font-size:13px;line-height:1.6;font-weight:700;">A 组 · 墨西哥城</p>
    </section>
    """


def match_header_b() -> str:
    return """
    <section style="margin:0 0 13px;padding:0;">
      <p style="margin:0 0 5px;color:#f6c35b;font-size:14px;line-height:1.4;font-weight:900;">03:00 · A 组 · 墨西哥城</p>
      <p style="margin:0;color:#ffffff;font-size:21px;line-height:1.42;font-weight:900;">墨西哥 vs 南非</p>
    </section>
    """


def match_header_c() -> str:
    return """
    <section style="margin:0 0 12px;padding:12px 0 0;border-top:1px solid rgba(255,255,255,0.16);">
      <p style="margin:0;color:#f6c35b;font-size:18px;line-height:1.4;font-weight:900;">03:00　墨西哥 vs 南非</p>
      <p style="margin:3px 0 0;color:#aeb8b5;font-size:13px;line-height:1.6;">A 组 · 墨西哥城</p>
    </section>
    """


ANALYSIS = "基础评分差为 +175，近期状态差为 +2.4，进攻对防守匹配差为 +1.6，赛地/主场修正约 +48 点。归一化后得到墨西哥胜 57.6%、平局 22.7%、南非胜 19.7%。"
SCORE = "比分参考 1-0，备选 2-0 / 1-1 / 2-1；进球数倾向偏少。"
RISK = "爆冷指数 49.3%。若墨西哥迟迟无法破门，南非的转换速度和定位球会让比赛进入更胶着的后半段。"


def shell(hero_url: str, body: str) -> str:
    return f"""
    <section style="max-width:677px;margin:0 auto;padding:0;background:#0f1416;color:#ffffff;">
      <img src="{hero_url}" alt="Vibe Football 比赛日重点观察" style="display:block;width:100%;height:auto;margin:0;border:0;" />
      <section style="padding:18px 16px 28px;background:#0f1416;">
        <p style="margin:0 0 14px;color:#ffffff;font-size:22px;line-height:1.45;font-weight:900;">赛事前瞻</p>
        {body}
        <section style="margin:20px 0 0;padding:12px 13px;background:rgba(246,195,91,0.10);border:1px solid rgba(246,195,91,0.24);border-radius:8px;">
          <p style="margin:0;color:#f6c35b;font-size:13px;line-height:1.75;">本文为赛前数据分析与观赛参考，不构成任何投注、投资或收益建议。</p>
        </section>
      </section>
    </section>
    """


def sample_a(hero_url: str) -> str:
    body = f"""
    <section style="margin:0 0 22px;padding:0;background:#0f1416;">
      {match_header_a()}
      {block("胜负分析", ANALYSIS, compact=True)}
      {block("比分进球", SCORE, color="#fbbf24", compact=True)}
      {block("冷门风险", RISK, color="#7dd3c7", compact=True)}
    </section>
    """
    return shell(hero_url, body)


def sample_b(hero_url: str) -> str:
    body = f"""
    <section style="margin:0 0 22px;padding:0;background:#0f1416;">
      {match_header_b()}
      {block("胜负分析", ANALYSIS, border=False)}
      {block("比分进球", SCORE, color="#fbbf24", border=False)}
      {block("冷门风险", RISK, color="#7dd3c7", border=False)}
    </section>
    """
    return shell(hero_url, body)


def sample_c(hero_url: str) -> str:
    body = f"""
    <section style="margin:0 0 20px;padding:0;background:#0f1416;">
      {match_header_c()}
      <p style="margin:0 0 7px;color:#f6c35b;font-size:14px;line-height:1.55;font-weight:900;">胜负分析</p>
      <p style="margin:0 0 14px;color:#cbd5d1;font-size:15px;line-height:1.86;">{ANALYSIS}</p>
      <p style="margin:0 0 7px;color:#fbbf24;font-size:14px;line-height:1.55;font-weight:900;">比分进球</p>
      <p style="margin:0 0 14px;color:#cbd5d1;font-size:15px;line-height:1.86;">{SCORE}</p>
      <p style="margin:0 0 7px;color:#7dd3c7;font-size:14px;line-height:1.55;font-weight:900;">冷门风险</p>
      <p style="margin:0;color:#cbd5d1;font-size:15px;line-height:1.86;">{RISK}</p>
    </section>
    """
    return shell(hero_url, body)


def push_draft(token: str, title: str, content: str) -> str:
    thumb_media_id = env("WECHAT_DEFAULT_COVER_MEDIA_ID")
    if not thumb_media_id:
        raise RuntimeError("WECHAT_DEFAULT_COVER_MEDIA_ID is required")
    payload = {
        "articles": [
            {
                "title": title,
                "author": env("WECHAT_AUTHOR", "世界杯观赛助手"),
                "digest": "公众号样式测试稿，仅用于确认微信编辑器内的手机排版效果。",
                "content": content,
                "content_source_url": env("WECHAT_ARTICLE_SOURCE_URL", SOURCE_URL),
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
    return str(data.get("media_id") or "")


def main() -> None:
    load_dotenv(ROOT / ".env")
    token = access_token()
    hero_url = upload_content_image(token, HERO_IMAGE)
    samples = [
        ("样式测试A｜无表格卡片", sample_a(hero_url)),
        ("样式测试B｜杂志分段", sample_b(hero_url)),
        ("样式测试C｜紧凑列表", sample_c(hero_url)),
    ]
    for title, content in samples:
        media_id = push_draft(token, title, content)
        print(f"{title}: {media_id}")


if __name__ == "__main__":
    main()
