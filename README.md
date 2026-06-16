# Insurance Broker AI Agent

这是一个保险产品研究 Agent 项目，包含两个主要部分：

- `经纪人agent/`：FastAPI 后端，负责透明 ReAct 研究流程、记忆系统、工具调用和 Web Acquisition Pipeline。
- 根目录 Next.js 应用：面向调试和演示的 Agent Workbench，默认运行在 `3000` 端口。

项目约定：`3000` 是用户可见前端，`8000` 是后端/API 服务。后端采集、诊断、配置和内部实现细节不直接暴露到前端，除非后续明确要做对应入口。

## 当前能力

### 透明 ReAct 研究主线

后端默认主线不是固定的保险证据流程，而是透明 ReAct loop：

1. 公开锚定用户意图。
2. 拆成可验证假设和任务。
3. 执行工具。
4. 观察结果。
5. 根据新信息修正计划。

主要接口：

```text
POST /agent/research
POST /agent/research/stream
```

如果没有配置 LLM，接口会返回结构化错误，不会伪造答案。

### 记忆与检索

后端使用 SQLite 保存会话、消息、工具事件、项目记忆和证据记忆。

常用接口：

```text
GET    /agent/memory/search
GET    /agent/memory/snapshot
GET    /agent/memory/facts
DELETE /agent/memory/facts/{fact_id}
GET    /agent/memory/project
GET    /agent/memory/evidence
GET    /agent/memory/tool-events
GET    /agent/memory/export
POST   /agent/memory
```

默认数据库路径：

```text
经纪人agent/data/memory/agent_memory.sqlite3
```

### Web Acquisition Pipeline

Web Acquisition Pipeline 用于采集公开保险产品页面和文档。它是后端能力，不是前端控制面板。

采集顺序：

1. Safe HTTP Foundation
2. Deterministic Playwright Browser Layer
3. Browser-use style intelligent fallback
4. Site-specific Harness fallback
5. SQLite persistence and API integration

核心约束：

- 所有 URL 都经过 `SecurityGate`。
- 拒绝 localhost、私网 IP、metadata IP、非 HTTP(S) scheme 和不安全重定向。
- 不登录、不注册、不购买、不支付、不提交表单、不绕过验证码、不进入个人中心。
- 返回统一的 `AcquisitionResult`，包含 steps、errors、links、PDF links、downloaded files、quality score 等。

主要接口：

```text
POST /web-acquisition/run
GET  /web-acquisition/tasks/{task_id}
GET  /web-acquisition/tasks/{task_id}/steps
GET  /web-acquisition/tasks/{task_id}/files
```

默认数据库路径：

```text
经纪人agent/data/web_acquisition/acquisition.sqlite3
```

示例请求：

```bash
curl -X POST http://127.0.0.1:8000/web-acquisition/run ^
  -H "Content-Type: application/json" ^
  -d "{\"url\":\"https://www.example.com/product\",\"goal\":\"查找公开保险资料\",\"allowed_domains\":[\"example.com\"],\"strategy\":\"auto\"}"
```

## 目录结构

```text
.
├─ app/                         # Next.js App Router frontend
├─ components/                  # Workbench UI components
├─ lib/                         # Frontend types, mock data, helpers
├─ 经纪人agent/
│  ├─ app/
│  │  ├─ api/                   # FastAPI routes
│  │  ├─ agents/                # Transparent runtime and planning
│  │  ├─ memory/                # SQLite and Hermes memory
│  │  ├─ tools/                 # Agent tools
│  │  └─ web_acquisition/       # Web Acquisition Pipeline
│  ├─ docs/                     # Backend design and implementation plans
│  └─ tests/                    # Backend pytest suite
└─ rag-backend/                 # Older/separate RAG backend work area
```

## 运行前端

```bash
npm install
npm run dev
```

默认打开：

```text
http://localhost:3000
```

前端默认 mock 模式：

```env
NEXT_PUBLIC_AGENT_API_MODE=mock
```

真实后端模式：

```env
NEXT_PUBLIC_AGENT_API_MODE=real
AGENT_API_BASE_URL=http://localhost:8000
```

注意：当前 Next.js 代理文件仍保留早期 `/agent/run_v2` 路径。后端当前主线接口是 `/agent/research` 和 `/agent/research/stream`。真实联调前需要先确认或更新代理路径。

## 运行后端

进入后端目录：

```bash
cd 经纪人agent
```

当前仓库还没有提交 Python `requirements.txt` 或 `pyproject.toml`。使用已有 Python 环境，或安装运行/测试所需依赖：

```bash
python -m pip install fastapi "uvicorn[standard]" pydantic httpx pytest
```

启动 API：

```bash
python -m uvicorn app.main:app --reload --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

## 后端 LLM 配置

后端通过环境变量连接 chat-completions-compatible LLM provider：

```env
LLM_PROVIDER=llm
LLM_API_BASE_URL=
LLM_API_PATH=/chat/completions
LLM_MODEL=
LLM_API_KEY=
MINIMAX_API_KEY=
AGENT_ENABLE_WEB_SEARCH=1
SUBAGENT_CONTRACTS_DIR=
```

没有配置 `LLM_API_BASE_URL` 或 `LLM_MODEL` 时，透明研究接口会返回 `llm_not_configured`。

## 测试

前端：

```bash
npm run test:run
npm run build
```

后端：

```bash
cd 经纪人agent
pytest -q
```

只跑 Web Acquisition：

```powershell
cd 经纪人agent
$files = Get-ChildItem -LiteralPath tests -Filter 'test_web_acquisition_*.py' | ForEach-Object { $_.FullName }
pytest @files -q
```

## 重要开发边界

- 默认用户调试前端端口：`3000`。
- 后端/API 端口：`8000`。
- 不要把后端-only 控制、诊断、配置或内部实现细节加到前端。
- 默认 Agent 主线是透明 ReAct，不要强制走保险证据评分、官方来源 gate 或 RAG citation gate。
- 保险证据评分、官方来源 gate、证据闭环模板只属于可选领域 workflow。

## 近期状态

已经完成并合并：

- Transparent ReAct runtime and streaming process events
- SQLite memory and Hermes memory helpers
- Web Acquisition Pipeline Stage 1-4
- Backend-only Web Acquisition API and persistence

待整理：

- 为后端补充正式 Python dependency file
- 对齐 Next.js real-mode proxy 与当前 FastAPI `/agent/research` 接口
- 视需要再为 Web Acquisition 增加前端入口
