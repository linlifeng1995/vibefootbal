# 世界杯观赛助手

世界杯赛前预测 H5 真实版雏形：FastAPI 后端生成预测和报告，H5 前端只展示已发布结果。

> 后续会话或 Agent 接手时，请先阅读 [`PROJECT_CONTEXT.md`](./PROJECT_CONTEXT.md)，里面包含项目结构、部署路径、API、数据生成逻辑和当前约束。

## 本地运行

```powershell
uv venv --clear .venv
uv pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

打开：

- 前台：http://127.0.0.1:8000/
- 后台：http://127.0.0.1:8000/admin

默认后台 Token 是 `change-me`。生产或真实测试时请复制 `.env.example` 为 `.env` 并修改 `ADMIN_TOKEN`。

## 数据与生成流程

- `API_FOOTBALL_KEY`：主赛程、球队和基础赛事数据。
- `SPORTMONKS_API_TOKEN`：赔率数据，优先用于 Bet365 bookmaker odds。
- `SERPER_API_KEY`：伤停、阵容、新闻等缺失数据检索。
- `DEEPSEEK_API_KEY`：根据结构化预测结果生成中文赛前分析。
- `DEEPSEEK_MODEL=deepseek-v4-pro`：使用 DeepSeek V4 Pro。
- `DEEPSEEK_THINKING=enabled`、`DEEPSEEK_REASONING_EFFORT=high`：默认使用高推理模式生成赛前报告。

没有外部 API Key 时，系统会自动 seed 一组本地示例数据，方便前端、后台和预测展示流程跑通。外部同步接口会返回清晰的缺少配置错误。

## 预测与内容生成

- 单场胜平负按 Elo/基础评分、近期状态、攻防匹配、赛地因素和比分矩阵分层合成。
- 前台保留模型分数比较，但不在正文里反复展示方法论描述；计算说明集中在问号提示里。
- 比分预测使用首选比分、备选比分和进球数倾向，并补充球队攻防节奏分析。
- 公众号每日前瞻按比赛逐场输出胜负分析、比分预测和冷门风险，内容来自已发布赛前报告，DeepSeek 只做公众号化表达。

## 当前范围

- 已移除可见的付费、广告解锁、90 秒口播功能。
- 已预留后续变现/广告服务扩展位置，但第一版不在 UI 展示。
- 概率由后端预测引擎计算，DeepSeek 只负责解释文案。
