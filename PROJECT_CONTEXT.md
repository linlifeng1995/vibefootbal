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
ADMIN_PAGE_PASSWORD=Aa51685845
```

当前线上已知状态：

- `DEEPSEEK_API_KEY` 已配置。
- `ADMIN_PAGE_PASSWORD` 是管理端进入密码，当前默认 `Aa51685845`。
- `SERPER_API_KEY` 未配置时，后端不能做真实网页检索，只能用 seed 数据和 DeepSeek 基于已知结构化数据生成。
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

输出：

- 主胜、平局、客胜概率
- 爆冷指数
- 置信度
- 模型因子
- 比分预测
- 进球数倾向

赔率只作为后端计算辅助，不在普通前台展示盘口、赔率、参考线、大/小概率。

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
