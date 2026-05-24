# LangGraph 轨迹调试台

这是一个用于调试 FastAPI + LangGraph Agent 后端的 Next.js 控制台。默认使用模拟数据，所以后端还没接好时也能先调界面和交互。

## 常用命令

```bash
npm install
npm run dev
npm run test:run
npm run build
```

## 运行模式

默认是模拟数据模式：

```env
NEXT_PUBLIC_AGENT_API_MODE=mock
```

真实后端模式会先请求 Next.js 代理接口 `POST /api/agent/run`，再转发到 FastAPI：

```env
NEXT_PUBLIC_AGENT_API_MODE=real
AGENT_API_BASE_URL=http://localhost:8000
```

FastAPI 需要提供这个接口：

```text
POST /agent/run
```

返回内容建议包含运行 id、状态、输入指令、节点、轨迹事件、工具调用、向量库命中、请求 JSON、响应 JSON 和最终回答。
