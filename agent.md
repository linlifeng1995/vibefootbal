# Agent Notes

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
- 当前公众号 HTML 样式采用 A17/A15 方向：白底正文、PNG 透明圆角标题图、金色日期时间和金色小标题。不要使用整篇深色背景，微信深色模式会自动改色；不要使用 `background-image`、负边距、table 或大 `min-height` 做公众号正文布局。
- 正文标题图默认使用 `assets/wechat-article-hero-card.png`。后台预览走 `/static/assets/wechat-article-hero-card.png`，推草稿时会调用微信 `media/uploadimg` 上传正文图片并把正文里的本地预览地址替换成微信图片 URL；这和封面 `WECHAT_DEFAULT_COVER_MEDIA_ID` 是两件事，标题图不需要手动上传到素材库。
- 每个比赛日只保留最新一篇公众号每日前瞻。新文章保存成功后，会清理同一 `matchday` 下的旧版本，避免后台长期堆积 v1/v2/v3 调试历史。
- Admin 里的比赛日选择使用 `/api/admin/matchdays` 返回的下拉选项，不要让用户手填日期。内部 `matchday` 仍使用北京时间中午 12:00 到次日 11:59 的赛事日规则。
- 如果某场没有 published report，只能写“报告待更新”，不能编造球员、伤停、赔率、历史战绩或分析。
- fact check 失败时状态为 `fact_failed`，禁止推送微信草稿箱。

## 图片与封面资源

- 当前 Git 仓库没有存放公众号主题图的本地图片文件。
- 微信 HTML 正文顶部主题图现在是远程 Unsplash 足球场图片 URL，写在 `backend/wechat_article.py` 的 `_render_html_poster()` 中。
- 设计预览页 `wechat-style-previews.html` 也使用远程图片 URL，仅用于本地样式对比。
- 微信草稿封面不在代码仓库中，使用 `.env` 的 `WECHAT_DEFAULT_COVER_MEDIA_ID` 指向微信公众号素材库里的固定封面。
- 其他机器拉取代码后，正文远程图能否显示取决于网络和微信端对外链图片的处理。生产发布更稳妥的方案是把封面/正文图上传到微信素材库或自有静态资源，再渲染正式图片地址。

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
