# Agent Notes

## 部署纪律

- 默认只在本地修改、调试和验证代码；不要因为完成了本地修改就自动上传或部署到服务器。
- 只有用户明确发出“更新服务器”“部署”“发布到线上”等指令时，才可以连接服务器执行上传、解压、重启服务等线上操作。
- 用户未明确要求部署时，最多给出本地验证结果和建议的部署步骤，不要主动执行 `scp`、远端解包、`systemctl restart` 或线上数据生成。
- 涉及公众号草稿箱、线上数据库、线上 `.env`、Nginx、证书、systemd 服务等生产状态的操作，都必须先确认用户当前请求确实是在要求更新服务器。

## 服务器部署流程

- 服务器：`140.143.182.236`，SSH 私钥路径通常是 `C:\Users\datamesh-u3d\Downloads\Office.pem`，常用用户是 `ubuntu`。
- 线上项目目录：`/opt/worldcup-assistant`；systemd 服务名：`worldcup-assistant`。
- 部署前先在本地完成必要验证，例如：
  ```powershell
  .\.venv\Scripts\python.exe -m compileall backend
  node --check app.js
  node --check admin.js
  git diff --check
  ```
- 部署时不要上传 `.env`、`data/worldcup.db`、日志、虚拟环境或本地临时脚本；线上 `.env` 和数据库默认保留服务器现状。
- 推荐流程：
  1. 本地确认 `git status --short`，只打包需要上线的代码和静态资源。
  2. 通过 SSH 连接服务器，在 `/opt/worldcup-assistant` 下先备份当前版本或确认可回退版本。
  3. 上传代码包到服务器临时目录，解压/同步到 `/opt/worldcup-assistant`，保留线上 `.env`、数据库和日志目录。
  4. 如依赖文件变更，再在线上虚拟环境安装依赖；没有依赖变更则跳过。
  5. 执行 `sudo systemctl restart worldcup-assistant` 重启服务。
  6. 执行 `sudo systemctl status worldcup-assistant --no-pager` 和 `journalctl -u worldcup-assistant -n 80 --no-pager` 检查服务状态与错误日志。
  7. 访问 `http://140.143.182.236/worldcup/` 和 `http://140.143.182.236/worldcup/admin` 做冒烟验证。
- 当前域名备案完成前，线上访问以 HTTP IP 路径为准；不要主动恢复 443/SSL 配置。等用户明确说域名备案完成并要求恢复证书后，再调整 Nginx/证书。
- 如果部署失败，优先停止继续改动，读取 systemd 日志定位原因；需要回退时恢复部署前备份版本并重启服务。

## DeepSeek 调试规则

- 调试 DeepSeek API 时，可以直接调用真实 DeepSeek API 做验证，不需要刻意节省 token。
- 如果用户要求检查 DeepSeek 使用情况、生成阵容、生成赛前分析或排查模型输出，应优先用真实 API 调试，而不是只用 fallback 或模拟数据。
- 不要打印 `.env` 中的真实 API Key；调用时从后端环境变量读取。
- 批量生成仍要注意范围：默认只生成“赛前情报”最近赛事日内的比赛，不要日常刷新 72 场全量赛程。
- 线上实测：DeepSeek 简单 JSON/单队短分析约 3 秒；把多队或完整单场报告塞进一个大 JSON 会变成 60 到 180 秒。冠军预测应按少量热门球队拆小请求或使用本地 fallback，避免一个大请求生成全部球队。

## 单场报告模型逻辑

- 单场胜平负概率内部仍可使用 `odds_snapshots.market='1x2'` 做概率校准，但这是内部计算细节；前台胜负逻辑不要展示赔率、市场、去水、隐含概率、模型端等说法。
- 前端 `/worldcup` 的分析页顺序是：核心判断、球员分析、胜负逻辑、比分预测/进球数倾向、其他风险与对位。
- 胜负逻辑不能只写“球队基础评分高”。需要体现模型分数计算路径：基础评分差、近期状态差、攻防匹配差、赛地/主场修正、综合校准如何共同推到最终胜平负概率。
- `backend/main.py` 的 `model_logic_note()` 会生成稳定的模型口径说明；`normalize_report_content()` 会使用确定性模板覆盖 DeepSeek 的 `logic`，避免出现外部事实或投注相关词。
- `app.js` 会把 `report.factors` 中的基础评分、近期状态、攻防匹配渲染成模型因子卡片；综合校准只写在逻辑正文中，不单独展示来源和权重。

## 公众号每日前瞻模块

- 公众号能力内置在现有 FastAPI 工程内，不另起独立服务。
- 核心文件是 `backend/wechat_article.py`，负责每日前瞻 source 聚合、DeepSeek 生成、事实校验、微信 HTML 渲染和草稿箱推送。
- `backend/main.py` 负责注册 `wechat_articles` 表、Admin API 和 `wechat_daily_preview` 定时任务。
- Admin 页面在 `admin.html` / `admin.js` / `styles.css` 中新增“公众号文章”区块，可生成、预览 Markdown、预览微信 HTML、推送草稿箱。
- 生成接口：
  - `GET /api/admin/wechat/articles`
  - `GET /api/admin/wechat/articles/{article_id}`
  - `POST /api/admin/wechat/daily-preview/generate`
  - `POST /api/admin/wechat/articles/{article_id}/push-draft`
- 所有公众号 Admin 接口都使用现有 `X-Admin-Token` 鉴权。
- 每日文章的“重点场次”必须优先使用单场报告里的 `logic` 字段，也就是 `/worldcup` 中展示的胜负逻辑。不要让 DeepSeek 自由改写成泛化模板句。
- 每日文章不要采用“先列今日赛程，再分别写重点场次/冷门风险/比分参考”的结构。当前结构是 `赛事前瞻`，按比赛逐场展开，每场固定包含“胜负分析 / 比分进球 / 冷门风险”，避免同一场比赛在多个 section 里重复出现。
- 公众号标题生成逻辑是“DeepSeek 先生成，后端再质检兜底/重写”。如果标题太泛、没有当天球队、没有覆盖最高冷门风险，或使用“首战 / 打头阵 / 打响”等比赛日开始叙事，后端会用本地标题生成器覆盖。
- 标题不要围绕“比赛日开始”。当前策略只保留热点热度：高关注球队 + 最高冷门风险场 + 球队修饰词。可用修饰词包括：`桑巴军团`、`德国战车`、`高卢雄鸡`、`斗牛士军团`、`橙衣军团`、`三狮军团`、`五盾军团`、`潘帕斯雄鹰`、`欧洲红魔`、`格子军团`、`瑞士军刀`、`蓝武士`、`太极虎`、`东道主墨西哥`。
- 标题示例：`6月12日世界杯前瞻：德国战车登场，橙衣军团碰蓝武士，科特迪瓦vs厄瓜多尔最悬`。不要写成 `6月12日赛事世界杯前瞻` 或 `墨西哥打响首战` 这类平标题。
- 当前公众号 HTML 样式采用 A17/A15 方向：白底正文、PNG 透明圆角标题图、金色日期时间和金色小标题。不要使用整篇深色背景，微信深色模式会自动改色；不要使用 `background-image`、负边距、table 或大 `min-height` 做公众号正文布局。
- 正文标题图默认使用 `assets/wechat-article-hero-card.png`。后台预览走 `/static/assets/wechat-article-hero-card.png`，推草稿时优先使用 `.env` 的 `WECHAT_ARTICLE_HERO_IMAGE_WECHAT_URL` 替换正文图片地址；未配置时才调用微信 `media/uploadimg` 现场上传。正文标题图和封面 `WECHAT_DEFAULT_COVER_MEDIA_ID` 是两件事，标题图不能直接使用素材库 `media_id`。
- 每个比赛日只保留最新一篇公众号每日前瞻。新文章保存成功后，会清理同一 `matchday` 下的旧版本，避免后台长期堆积 v1/v2/v3 调试历史。
- Admin 里的比赛日选择使用 `/api/admin/matchdays` 返回的下拉选项，不要让用户手填日期。内部 `matchday` 仍使用北京时间中午 12:00 到次日 11:59 的赛事日规则。
- 如果某场没有 published report，只能写“报告待更新”，不能编造球员、伤停、赔率、历史战绩或分析。
- fact check 失败时状态为 `fact_failed`，禁止推送微信草稿箱。

## 图片与封面资源

- 当前 Git 仓库已存放公众号正文标题图：`assets/wechat-article-hero-card.png`，这是带透明圆角的 PNG，不能替换回 JPG，否则微信草稿里圆角可能失效。
- 微信 HTML 正文顶部标题图由 `backend/wechat_article.py` 的 `_render_html_poster()` 渲染。后台预览使用 `/static/assets/wechat-article-hero-card.png`；推草稿时后端优先复用 `WECHAT_ARTICLE_HERO_IMAGE_WECHAT_URL`，避免每日任务反复上传正文图片。
- 公众号封面图和正文标题图是两件事：封面仍使用 `.env` 的 `WECHAT_DEFAULT_COVER_MEDIA_ID` 指向微信公众号素材库固定封面；正文标题图使用微信正文图片 URL，不使用素材库 `media_id`。
- 其他机器拉取代码后，只要 `assets/wechat-article-hero-card.png` 存在，`.env` 中的 `WECHAT_ARTICLE_HERO_IMAGE_PATH` / `WECHAT_ARTICLE_HERO_IMAGE_PREVIEW_URL` 没有指向不存在的路径，本地预览就能正常加载；若要稳定推草稿，应同步配置 `WECHAT_ARTICLE_HERO_IMAGE_WECHAT_URL`。

## 其他端拉取运行

- Git 只同步代码，不同步 `.env`、`data/worldcup.db`、已生成的公众号文章、日志和本地虚拟环境。
- 新机器拉取后需要复制 `.env.example` 为 `.env`，再填写 `DEEPSEEK_API_KEY`、`ADMIN_TOKEN`、`ADMIN_PAGE_PASSWORD`、微信 `WECHAT_APP_ID` / `WECHAT_APP_SECRET` / `WECHAT_DEFAULT_COVER_MEDIA_ID` 等配置。
- 安装依赖后运行：
  ```powershell
  .venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
  ```
- 本地访问：
  - `/worldcup`：世界杯预测前台。
  - `/admin`：后台管理与公众号文章生成。
- 公众号文章记录保存在本地 SQLite 的 `wechat_articles` 表中。其他端如果没有同一份数据库，需要重新生成文章。
