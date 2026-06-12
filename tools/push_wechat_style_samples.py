from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
HERO_IMAGE = ROOT / "assets" / "wechat-style-test-hero-baked.jpg"
HERO_CARD_IMAGE = ROOT / "assets" / "wechat-style-test-hero-card.jpg"
HERO_CARD_PNG = ROOT / "assets" / "wechat-style-test-hero-card.png"
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
    mime_type = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    with image_path.open("rb") as image_file:
        response = httpx.post(
            "https://api.weixin.qq.com/cgi-bin/media/uploadimg",
            params={"access_token": token},
            files={"media": (image_path.name, image_file, mime_type)},
            timeout=30,
        )
    response.raise_for_status()
    data = response.json()
    if data.get("errcode"):
        raise RuntimeError(f"WeChat image upload error: {data}")
    return str(data["url"])


def block(title: str, body: str, *, color: str = "#f6c35b", border: bool = True, compact: bool = False, dark_safe: bool = False) -> str:
    border_style = f"border:1px solid rgba(246,195,91,0.22);" if border else "border-left:3px solid rgba(246,195,91,0.72);"
    pad = "8px 10px 9px" if compact else "17px 16px 18px"
    margin = "7px 0 0" if compact else "12px 0 0"
    radius = "border-radius:10px;" if border else "border-radius:0;"
    background = "#222628" if dark_safe else "rgba(255,255,255,0.052)"
    text_color = "#dce3e0" if dark_safe else "#d7dfdc"
    return f'<section style="margin:{margin};padding:{pad};{border_style}{radius}background:{background};"><p style="margin:0 0 2px;color:{color};font-size:14px;line-height:1.18;font-weight:900;">{title}</p><p style="margin:0;color:{text_color};font-size:14px;line-height:1.58;">{body}</p></section>'


def match_header_a(*, dark_safe: bool = False) -> str:
    meta_color = "#cfd7d4" if dark_safe else "#c9d2cf"
    return f'<section style="margin:0 0 6px;padding:8px 0 3px;"><p style="margin:0 0 1px;white-space:nowrap;color:#ffffff;font-size:17px;line-height:1.2;font-weight:900;"><span style="color:#f6c35b;font-size:21px;font-weight:900;">03:00</span><span style="color:#ffffff;font-size:17px;font-weight:900;">&nbsp;&nbsp;墨西哥 vs 南非</span></p><p style="margin:0 0 0 75px;white-space:nowrap;color:{meta_color};font-size:13px;line-height:1.25;font-weight:700;">A 组 · 墨西哥城</p></section>'


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


def shell(hero_url: str, body: str, *, dark_safe: bool = False) -> str:
    background = "#1b1f21" if dark_safe else "#0f1416"
    disclaimer_background = "#25241f" if dark_safe else "rgba(246,195,91,0.10)"
    return f'<section style="max-width:677px;margin:0 auto;padding:0;background:{background};color:#ffffff;"><img src="{hero_url}" alt="Vibe Football 比赛日重点观察" style="display:block;width:100%;height:auto;margin:0;border:0;" /><section style="padding:0 20px 24px;background:{background};">{body}<section style="margin:12px 0 0;padding:9px 11px;background:{disclaimer_background};border:1px solid rgba(246,195,91,0.24);border-radius:8px;"><p style="margin:0;color:#f6c35b;font-size:13px;line-height:1.65;">本文为赛前数据分析与观赛参考，不构成任何投注、投资或收益建议。</p></section></section></section>'


def sample_a(hero_url: str, *, dark_safe: bool = False) -> str:
    background = "#1b1f21" if dark_safe else "#0f1416"
    body = f'<section style="margin:0 0 14px;padding:0;background:{background};">{match_header_a(dark_safe=dark_safe)}{block("胜负分析", ANALYSIS, compact=True, dark_safe=dark_safe)}{block("比分进球", SCORE, color="#fbbf24", compact=True, dark_safe=dark_safe)}{block("冷门风险", RISK, color="#7dd3c7", compact=True, dark_safe=dark_safe)}</section>'
    return shell(hero_url, body, dark_safe=dark_safe)


def light_block(title: str, body: str, *, color: str = "#c08a24") -> str:
    return f'<section style="margin:9px 0 0;padding:10px 11px;border:1px solid #d8c99a;border-radius:10px;"><p style="margin:0 0 3px;color:{color};font-size:14px;line-height:1.2;font-weight:900;">{title}</p><p style="margin:0;color:#303437;font-size:14px;line-height:1.58;">{body}</p></section>'


def sample_a10(hero_url: str, *, pull_match: bool = False) -> str:
    match_margin = "-116px 0 8px" if pull_match else "0 0 8px"
    match = f'<section style="margin:{match_margin};padding:0 20px 2px;"><p style="margin:0 0 1px;white-space:nowrap;color:#111417;font-size:17px;line-height:1.2;font-weight:900;"><span style="color:#c08a24;font-size:19px;font-weight:900;">03:00</span><span style="color:#111417;font-size:17px;font-weight:900;">&nbsp;&nbsp;墨西哥 vs 南非</span></p><p style="margin:0 0 0 70px;white-space:nowrap;color:#4d5356;font-size:13px;line-height:1.3;">A 组 · 墨西哥城</p></section>'
    body = f'{light_block("胜负分析", ANALYSIS)}{light_block("比分进球", SCORE)}{light_block("冷门风险", RISK)}'
    return f'<section style="max-width:677px;margin:0 auto;padding:0;color:#111417;"><img src="{hero_url}" alt="Vibe Football 比赛日重点观察" style="display:block;width:100%;height:auto;margin:0;border:0;" />{match}<section style="padding:0 20px 22px;">{body}<section style="margin:12px 0 0;padding:9px 11px;border:1px solid #eadcae;border-radius:8px;"><p style="margin:0;color:#6d5b21;font-size:13px;line-height:1.65;">本文为赛前数据分析与观赛参考，不构成任何投注、投资或收益建议。</p></section></section></section>'


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
    variant = sys.argv[1].strip().lower() if len(sys.argv) > 1 else "all"
    if variant in {"a15", "a16", "a17"}:
        hero_path = HERO_CARD_PNG
    elif variant in {"a10", "a11", "a12", "a13", "a14"}:
        hero_path = HERO_CARD_IMAGE
    else:
        hero_path = HERO_IMAGE
    hero_url = upload_content_image(token, hero_path)
    if variant in {"a10", "a11", "a12", "a13", "a14", "a15", "a16", "a17"}:
        title = "样式测试A17｜金色时间大标题图" if variant == "a17" else ("样式测试A16｜金色小标题" if variant == "a16" else ("样式测试A15｜PNG透明圆角" if variant == "a15" else ("样式测试A14｜纯圆角标题图" if variant == "a14" else ("样式测试A13｜A10圆角时间外置" if variant == "a13" else ("样式测试A12｜图片自带圆角" if variant == "a12" else ("样式测试A11｜标题图不包时间" if variant == "a11" else "样式测试A10｜白底圆角标题图"))))))
        samples = [(title, sample_a10(hero_url, pull_match=variant == "a13"))]
    elif variant in {"a", "a2", "a3", "a4", "a5", "a6", "a7", "a8", "a9"}:
        title = "样式测试A9｜深色适配" if variant == "a9" else ("样式测试A8｜时间顶部微调" if variant == "a8" else ("样式测试A7｜压缩HTML空白" if variant == "a7" else ("样式测试A6｜合并分割线" if variant == "a6" else ("样式测试A5｜删除空行" if variant == "a5" else ("样式测试A4｜间距收紧" if variant == "a4" else ("样式测试A3｜线条对齐" if variant == "a3" else "样式测试A2｜目标微调"))))))
        samples = [(title, sample_a(hero_url, dark_safe=variant == "a9"))]
    else:
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
