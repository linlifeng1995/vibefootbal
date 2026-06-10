# 世界杯观赛助手工程上下文

这份文档面向后续会话和自动化 Agent，用来快速识别项目结构、运行方式、数据流和当前约束。

## 项目定位

这是一个世界杯赛前预测 H5 工具。当前形态是：

- FastAPI 后端负责生成数据、预测、报告、冠军榜和管理接口。
- 纯静态 H5 前端负责展示已发布结果。
- SQLite 存储赛程、球队、赔率快照、检索来源、预测、报告、冠军预测和生成日志。
- 线上部署在同一台 Ubuntu 服务器的 `/worldcup/` 路径下，不占用已有根站点。

线上访问：

- 前台：`http://140.143.182.236/worldcup/`
- 后台：`http://140.143.182.236/worldcup/admin`
- 服务：`worldcup-assistant.service`
- 服务器路径：`/opt/worldcup-assistant`
- 服务内网端口：`127.0.0.1:8010`

## 本地结构

根目录：`C:\Users\64469\Documents\世界杯观赛助手`

关键文件：

- `backend/main.py`：FastAPI 应用、SQLite schema、seed 数据、预测计算、DeepSeek 调用、Admin API。
- `index.html`：前台页面结构。
- `app.js`：前台数据加载、视图切换、比赛报告、赛程、冠军预测渲染。
- `styles.css`：全部前台和后台样式。
- `admin.html` / `admin.js`：简易后台。
- `assets/worldcup-2026-icon.svg`：顶部品牌图标。
- `.env.example`：环境变量模板，不能放真实密钥。
- `.env`：本地真实密钥文件，不要提交或输出内容。
- `data/worldcup.db`：本地 SQLite 数据库。
- `requirements.txt`：Python 依赖。

## 本地运行

```powershell
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

访问：

- 前台：`http://127.0.0.1:8000/`
- 后台：`http://127.0.0.1:8000/admin`

常用检查：

```powershell
node --check app.js
node --check admin.js
.venv\Scripts\python.exe -m compileall backend
```

## 环境变量

`.env.example` 当前字段：

```env
API_FOOTBALL_KEY=
SPORTMONKS_API_TOKEN=
SERPER_API_KEY=
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_THINKING=enabled
DEEPSEEK_REASONING_EFFORT=high
ADMIN_TOKEN=change-me
ADMIN_PAGE_PASSWORD=change-me
WECHAT_APP_ID=
WECHAT_APP_SECRET=
WECHAT_AUTHOR=世界杯观赛助手
WECHAT_DEFAULT_COVER_MEDIA_ID=
WECHAT_ARTICLE_SOURCE_URL=http://140.143.182.236/worldcup/
WECHAT_ARTICLE_HERO_IMAGE_PATH=assets/wechat-article-hero-card.png
WECHAT_ARTICLE_HERO_IMAGE_PREVIEW_URL=/static/assets/wechat-article-hero-card.png
WECHAT_ARTICLE_HERO_IMAGE_WECHAT_URL=
WECHAT_DAILY_PREVIEW_AUTO_DRAFT=false
WECHAT_DAILY_PREVIEW_HOUR=18
DEEPSEEK_WECHAT_REASONING_EFFORT=medium
DEEPSEEK_WECHAT_THINKING=enabled
```

当前线上已知状态：

- `DEEPSEEK_API_KEY` 需要在本地 `.env` 配置，不能提交真实 token。
- `ADMIN_PAGE_PASSWORD` 是管理端进入密码，建议只在本地 `.env` 配置。
- `SERPER_API_KEY` 未配置时，后端不能做真实网页检索；管理端“检索”和生成赛前情报会回退为 DeepSeek 赛前伤停/阵容动态摘要，并保存到 `research_sources` 供报告生成使用。DeepSeek 摘要必须保守标记“待官方确认/暂无公开确认”，不能当作官方伤停来源。
- `API_FOOTBALL_KEY`、`SPORTMONKS_API_TOKEN` 当前同步实现还是占位，未接完整生产映射。

不要在响应、日志、文档里打印 `.env` 里的真实 token。

## 数据与生成流程

### Seed 数据

`backend/main.py` 内置正式 2026 分组 seed：

- `seed_teams()`：48 支球队、中文名、队码、评分和攻防状态。
- `seed_group_map()`：12 个小组，每组 4 队。
- `seed_match_rows()`：按小组生成 72 场小组赛。
- `SEED_VERSION`：seed 版本号；改分组或 seed 数据时需要升级，让 `init_db()` 刷新旧数据。

当前 seed 版本：

```python
SEED_VERSION = "2026-official-groups-v1"
```

### 预测计算

单场预测入口：

- `calculate_prediction(bundle)`

当前计算方式：

- 先组合 Elo/基础评分、近期状态、攻防匹配和赛地因素，形成赛前强度差。
- 再用 Poisson/Dixon-Coles 比分矩阵校验进球分布，并反推比分候选、胜平负概率和进球数倾向。
- 多模型输出会计算分歧度，用于控制置信度；前台概率应理解为赛前分数分布，不是确定性结论。
- 外部赔率/盘口类信号只作为后端概率稳定器，不作为普通用户侧的单独结论展示。

输出：

- 主胜、平局、客胜概率
- 爆冷指数
- 置信度
- 模型因子
- 比分预测
- 进球数倾向

赔率只作为后端计算辅助，不在普通前台展示盘口、赔率、参考线、大/小概率。

前台展示约束：

- `胜负分析` 要保留模型评比和分数比较，但移除“模型如何计算”的长篇理论论证。
- 计算方法说明集中到小问号提示，不要在每场正文里重复展示。
- 胜负逻辑需要针对每场比赛展开具体球队、打法、节奏和风险，不要只写通用模板。
- `比分预测` 需要包含首选比分、备选比分、进球数倾向和具体原因。

### 冠军预测

入口：

- `generate_champion_prediction(publish=False, use_deepseek=False)`

当前逻辑：

- 优先使用 `MARKET_OUTRIGHT_ODDS` 作为冠军赔率先验。
- 赔率隐含概率占主要权重，球队评分模拟只做轻微修正。
- 因此西班牙当前会排第一，符合 Bet365 截图中西班牙赔率最低的逻辑。

当前顶部冠军赔率 seed：

```python
MARKET_OUTRIGHT_ODDS = {
    "ESP": 5.50,
    "FRA": 6.00,
    "ENG": 7.50,
    "BRA": 9.00,
    "POR": 9.00,
    "ARG": 10.00,
}
```

如果接入 Sportmonks/Bet365 bookmaker odds，应该用真实 outright odds 覆盖这个 seed 表。

### DeepSeek

单场报告入口：

- `deepseek_report(bundle, prediction)`
- `generate_match_report(match_id, publish=False, use_deepseek=True)`

冠军分析入口：

- `deepseek_champion_analyses(entries)`

注意：

- DeepSeek 只负责中文内容生成，不直接编概率。
- DeepSeek 标准 Chat Completions 不会自动全网搜索。
- 如果需要伤停、正式名单、预计首发，必须先通过 Serper/API-FOOTBALL/Sportmonks/FIFA 等数据源检索或同步，再把来源传给 DeepSeek。
- 当前 prompt 明确禁止把盘口、赔率、参考线、大球概率、小球概率写到前台分析里。
- 当前 prompt 明确禁止把“反击第一推进点”“中卫防空核心”等占位词当球员名。

### Serper 搜索

检索入口：

- `research_match_sources(match_id, limit=8)`
- Admin API：`POST /api/admin/matches/{match_id}/research`

没有 `SERPER_API_KEY` 时：

- 记录日志：`SERPER_API_KEY is not configured; skipped web research`
- 前台球员状态显示“暂无公布的伤停信息。”等简短用户可读文案。

## 前台信息架构

顶部品牌：

- 标题：`世界杯观赛助手`
- 图标：`assets/worldcup-2026-icon.svg`

顶部导航：

- `赛前情报`
- `赛程信息`
- `冠军预测`

赛前情报：

- 左侧最近赛事日比赛列表。
- 中间单场详情、胜平负概率、胜负分析、球员状态、赛前条件。
- 比分预测和进球数倾向只展示结论与球队分析，不展示盘口/赔率底层数据。

球员状态：

- `球员分析`
- 预测布阵图
- 伤停、疑似缺阵、关键球员
- 没有来源时用“暂无公布的伤停信息。”，不要写内部推断话术。

赛程信息：

- 顶部 summary card：小组、球队、已排赛程。
- 小组赛分组显示积分榜列：`总赛 / 胜 / 平 / 负 / 积分`。
- 国旗使用真实图片：`https://flagcdn.com/w40/{country}.png`，不要再手绘渐变。

冠军预测：

- 顶部 summary card：参评球队、当前榜首、冠军概率。
- 各队按概率分层展示。

## 公开 API

前台：

- `GET /api/health`
- `GET /api/matches/today`
- `GET /api/matches/nearest-day`
- `GET /api/matches/upcoming`
- `GET /api/matches/{match_id}/report`
- `GET /api/tournament/champion-prediction`
- `GET /api/schedule/groups`
- `GET /api/schedule/calendar`
- `GET /api/schedule/bracket`

后台，需要 `X-Admin-Token`：

- `GET /api/admin/matches`
- `GET /api/admin/logs?limit=60`
- `POST /api/admin/sync/fixtures`
- `POST /api/admin/sync/odds`
- `POST /api/admin/matches/generate-nearest-day?publish=true`
- `POST /api/admin/matches/{match_id}/research`
- `POST /api/admin/matches/{match_id}/generate?publish=true`
- `POST /api/admin/matches/generate-all?publish=true&limit=72`，仅明确需要全量批处理时使用。
- `POST /api/admin/tournament/generate-champion-prediction?publish=true`
- `POST /api/admin/reports/{report_id}/publish`
- `POST /api/admin/reports/{report_id}/unpublish`

## 部署流程

打包：

```powershell
$archive = Join-Path $env:TEMP 'worldcup-assistant.tgz'
if (Test-Path $archive) { Remove-Item -LiteralPath $archive -Force }
tar -czf $archive --exclude=.git --exclude=.venv --exclude=data --exclude=logs --exclude=__pycache__ --exclude=*.pyc .
scp "$archive" ubuntu@140.143.182.236:/tmp/worldcup-assistant.tgz
```

远端部署：

```bash
cd /opt/worldcup-assistant
tar --exclude=.env --exclude=data -xzf /tmp/worldcup-assistant.tgz
.venv/bin/python -m compileall backend
sudo systemctl restart worldcup-assistant
sudo systemctl is-active worldcup-assistant
```

如果 seed 数据、报告结构、冠军预测逻辑变了，部署后默认只刷新“赛前情报”的最近赛事日：

```bash
cd /opt/worldcup-assistant
.venv/bin/python -c "import os,httpx; from pathlib import Path; from dotenv import load_dotenv; load_dotenv(Path('.env')); token=os.getenv('ADMIN_TOKEN', 'change-me'); r=httpx.post('http://127.0.0.1:8010/api/admin/matches/generate-nearest-day?publish=true&use_deepseek=false', headers={'X-Admin-Token': token}, timeout=120); print(r.status_code); print(r.text[:500])"
sudo systemctl restart worldcup-assistant
```

不要把日常刷新写成 72 场全量生成。前台“赛前情报”只展示最近一个赛事日，所以默认只更新这个赛事日涉及的比赛和队伍；`generate-all` 仅用于显式全量重建或离线批处理。

如果要真实调用 DeepSeek 生成某场：

```bash
cd /opt/worldcup-assistant
.venv/bin/python -c "import os,httpx; from pathlib import Path; from dotenv import load_dotenv; load_dotenv(Path('.env')); token=os.getenv('ADMIN_TOKEN', 'change-me'); r=httpx.post('http://127.0.0.1:8010/api/admin/matches/seed-001-mex-sou/generate?publish=true', headers={'X-Admin-Token': token}, timeout=180); print(r.status_code); print(r.text[:500])"
```

## 已知约束与注意事项

- 不要直接爬 Bet365 页面。当前采用截图/公开赔率作为 seed；生产版应该用 Sportmonks Odds 或其他合规 odds feed 获取 Bet365 bookmaker odds。
- 前台不要显示盘口、赔率、参考线、大/小概率等底层市场信息。
- DeepSeek 失败时必须 fallback，不覆盖已发布报告是更安全的生产策略；当前 Admin 生成会发布新报告，失败则使用 fallback。
- 调试 DeepSeek API 时，可以直接调用真实 DeepSeek API 做验证，不需要刻意节省 token；但不要打印 `.env` 中的真实 API Key。
- DeepSeek 性能结论：简单 JSON/单队短分析约 3 秒；冠军预测不要一次让 DeepSeek 写全量球队。当前后端只对前 6 支热门球队并发生成 DeepSeek 分析，其余使用本地模板，避免 60 到 180 秒的大请求。
- 冠军预测不是纯赔率反推。当前计算使用球队评分、近期状态、攻防平衡、淘汰赛容错等模型信号生成模型概率，再与市场隐含概率加权融合；赔率只作为校准项，不直接决定榜单。
- 浏览器端国旗依赖 flagcdn 外链；如果网络慢，可以后续改为本地缓存 WebP/PNG。
- `.env` 不能被覆盖，部署命令必须保留 `--exclude=.env`。
- `data/` 线上数据库不能随便覆盖，部署命令必须保留 `--exclude=data`。
- 当前 Git 工作区看起来大多文件未跟踪，不能依赖 `git diff` 判断改动范围。

## 最近重要产品决策

- 品牌名：`世界杯观赛助手`。
- 不展示付费、广告、90 秒口播。
- `AI 分析` 改为 `胜负分析`。
- `模型因子`、`赔率反推` 不在普通前台展示。
- 冠军预测是顶层栏目，不放在单场赛事内。
- 今日无比赛时，赛前情报展示最近一个有比赛的赛事日。
- 小组赛使用北京时间中午 12:00 到次日 11:59 归为同一赛事日。
- 球员状态里没有公开数据时，只写“暂无公布的伤停信息。”，不要写内部分析描述。

## 公众号每日前瞻 V1

新增后台模块用于生成微信公众号每日前瞻文章，并推送到公众号草稿箱。

后端文件：

- `backend/wechat_article.py`：聚合比赛日 source、生成文章、事实校验、Markdown 转微信 HTML、微信草稿箱 API。
- `backend/main.py`：注册 `wechat_articles` 表、Admin API、`wechat_daily_preview` 定时任务。

后台 API，均需要 `X-Admin-Token`：

- `GET /api/admin/wechat/articles`
- `GET /api/admin/wechat/articles/{article_id}`
- `POST /api/admin/wechat/daily-preview/generate`
- `POST /api/admin/wechat/articles/{article_id}/push-draft`

配置项：

- `WECHAT_APP_ID`
- `WECHAT_APP_SECRET`
- `WECHAT_AUTHOR`
- `WECHAT_DEFAULT_COVER_MEDIA_ID`
- `WECHAT_ARTICLE_SOURCE_URL`
- `WECHAT_ARTICLE_HERO_IMAGE_PATH`
- `WECHAT_ARTICLE_HERO_IMAGE_PREVIEW_URL`
- `WECHAT_ARTICLE_HERO_IMAGE_WECHAT_URL`
- `WECHAT_DAILY_PREVIEW_AUTO_DRAFT`
- `WECHAT_DAILY_PREVIEW_HOUR`
- `DEEPSEEK_WECHAT_REASONING_EFFORT`
- `DEEPSEEK_WECHAT_THINKING`

V1 约束：

- 只做“每日前瞻”，不做单场前瞻、冠军预测文章和自动发布。
- DeepSeek 只负责公众号化表达，不允许创造输入 source 以外的事实。
- fact check 失败时状态为 `fact_failed`，禁止推送草稿箱。
- 定时任务 `公众号每日前瞻生成并推草稿` 会生成文章并自动推送到微信公众号草稿箱；后台公众号模块的“生成每日前瞻”按钮仍只生成文章，预览后可手动点“推送草稿箱”。
- 草稿封面使用 `WECHAT_DEFAULT_COVER_MEDIA_ID`，第一版不动态生成封面。
- 正文标题图使用仓库内固定 PNG：`assets/wechat-article-hero-card.png`。后台预览走 `/static/assets/wechat-article-hero-card.png`；推草稿时优先使用 `.env` 的 `WECHAT_ARTICLE_HERO_IMAGE_WECHAT_URL`，未配置时才调用微信 `media/uploadimg` 现场上传并替换正文 URL。封面才使用 `WECHAT_DEFAULT_COVER_MEDIA_ID`，正文标题图不能直接使用素材库 `media_id`。
- 微信正文样式采用 A17/A15 方向：白底、PNG 透明圆角标题图、金色日期时间、金色小标题、无分割线、无 table、无整篇深色背景。
- 赛事前瞻必须按比赛逐场展开，每场固定包含 `胜负分析`、`比分预测`、`冷门风险`。
- 公众号里统一使用 `比分预测`，不要再使用 `比分进球`。
- `比分预测` 使用 `score_prediction` 和 `totals_prediction`，需要展开其中的 analysis 内容，不能只写一句比分参考。
- 如果当天文章已存在，管理端“生成每日前瞻”会传 `force: true` 强制生成新版本；旧稿不会自动改写，需要重新生成。
- 公众号标题由 DeepSeek 先生成，再由后端做质量判断；如果标题太泛、缺少当天球队、缺少最高冷门风险，或使用“首战 / 打头阵 / 打响”等比赛日开始叙事，会被本地标题生成器覆盖。
- 标题策略只保留热点热度：高关注球队 + 最高冷门风险场 + 球队修饰词。可用修饰词包括 `桑巴军团`、`德国战车`、`高卢雄鸡`、`斗牛士军团`、`橙衣军团`、`三狮军团`、`五盾军团`、`潘帕斯雄鹰`、`欧洲红魔`、`格子军团`、`瑞士军刀`、`蓝武士`、`太极虎`、`东道主墨西哥`。
- 标题示例：`6月12日世界杯前瞻：德国战车登场，橙衣军团碰蓝武士，科特迪瓦vs厄瓜多尔最悬`。
