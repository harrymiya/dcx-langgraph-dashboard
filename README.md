# Refactor Control Room

独立的 React + Vite + LangGraph 重构 DAG 控制台。LangGraph 服务已经随项目放在
`backend/` 下，前端通过本地代理访问它：

- POST /assistants/search 动态发现 refactor_dag
- GET /assistants/{assistant_id}/graph 动态读取节点和依赖边
- POST /threads/{thread_id}/runs/wait 同步节点运行状态
- 开发环境通过 Vite /langgraph 代理访问项目内的 http://127.0.0.1:8123
- 开发/预览环境通过 Vite /api/agents/launch 在本机打开 Konsole，并在 APP18 仓库启动 Agent CLI

当前项目内置 131 个业务节点；LangGraph API 会额外返回 `__start__`、`__end__`
两个控制节点。页面会根据接口响应实时计算数量。

## 启动

环境要求：Node.js 20.19+、npm，以及 Python 3.10+。首次启动会自动在
`backend/.venv` 创建 Python 虚拟环境并安装 LangGraph 依赖。

安装前端依赖后，一条命令启动前后端：

    cd /mnt/data/code/dcx-langgraph-dashboard
    npm install
    npm run dev:all

打开 http://127.0.0.1:5175/。按 `Ctrl+C` 会同时停止前端和 LangGraph 服务。

也可以使用别名：

    npm run start

只启动前端（需要自行保证 8123 端口已有 LangGraph 服务）仍可使用：

    npm run dev

`npm run dev:all` 支持以下可选环境变量：

- `LANGGRAPH_PYTHON`：指定 Python 可执行文件
- `LANGGRAPH_BIN`：直接指定 `langgraph` 可执行文件，适合已有虚拟环境
- `LANGGRAPH_PORT`：修改 LangGraph 端口，默认 `8123`
- `FRONTEND_PORT`：修改 Vite 端口，默认 `5175`

如需连接其他 LangGraph 服务：

    LANGGRAPH_API_URL=http://127.0.0.1:8123 npm run dev

## 项目内 LangGraph 服务

- `backend/langgraph.json`：注册 `refactor_dag`
- `backend/graph.py`：构建并编译 DAG
- `backend/tasks.json`：当前任务、依赖、状态和执行属性快照
- `backend/requirements.txt`：LangGraph 服务依赖

手动校验服务配置：

    langgraph validate --config backend/langgraph.json

## 操作

- 点击节点：查看状态、类型、前置依赖和后续节点
- 搜索框：按节点 ID、分组或类型过滤
- 状态标签：快速查看阻塞、进行中、计划中和工程/合同就绪任务
- 重新同步：重新拉取 LangGraph 图定义，并执行一次 refactor_dag
- 缩放按钮：适配完整 DAG 的横向画布；也可以在画布内按住 Ctrl 滚动鼠标滚轮缩放，浏览器页面不会跟着缩放
- 节点详情：点击 OpenCode、Pi、Codex 按钮会直接打开新的 Konsole bash 窗口，在 `/mnt/data/code/dcx-web/dcx-web` 中启动对应 CLI；当前节点、依赖、状态和验证上下文由页面自动注入，不需要复制提示词
- 顶部主题按钮：切换深色/浅色模式，偏好保存在浏览器本地

无 evidence manifest 时，后端会把计划第 6.2.3 节的状态快照作为 `plan-snapshot` 展示投影；有逐任务 evidence manifest 时，仍以 manifest 为严格证据源。看板不会把“节点已入图”误报为“任务已完成”。

Agent 启动器只接受固定的 Agent 类型和固定的 APP18 工作目录，不接受页面传入任意命令或工作目录。它依赖当前桌面环境存在 `/usr/bin/konsole`，以及 PATH 中可用的 `opencode`、`pi`、`codex` 命令。
