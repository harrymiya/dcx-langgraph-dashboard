# Refactor Control Room

独立的 React + Vite 重构 DAG 控制台。页面不内置节点数量或依赖数据，以当前
LangGraph API 为唯一图结构来源：

- POST /assistants/search 动态发现 refactor_dag
- GET /assistants/{assistant_id}/graph 动态读取节点和依赖边
- POST /threads/{thread_id}/runs/wait 同步节点运行状态
- 开发环境通过 Vite /langgraph 代理访问 http://127.0.0.1:8123

当前后端接口返回 133 个图节点：131 个业务节点，以及 __start__、__end__
两个控制节点。页面会根据接口响应实时计算数量，不依赖固定数字。

## 启动

先启动现有 LangGraph 后端：

    /mnt/data/code/.venvs/dcx-web-langgraph/bin/langgraph dev \
      --config /mnt/data/code/dcx-web/dcx-web/langgraph.json \
      --host 127.0.0.1 --port 8123 --no-browser

再启动本项目：

    cd /mnt/data/code/dcx-langgraph-dashboard
    pnpm install
    pnpm dev

打开 http://127.0.0.1:5175/。

如需连接其他 LangGraph 服务：

    LANGGRAPH_API_URL=http://127.0.0.1:8123 pnpm dev

## 操作

- 点击节点：查看状态、类型、前置依赖和后续节点
- 搜索框：按节点 ID、分组或类型过滤
- 状态标签：快速查看阻塞、进行中、计划中和工程/合同就绪任务
- 重新同步：重新拉取 LangGraph 图定义，并执行一次 refactor_dag
- 缩放按钮：适配完整 DAG 的横向画布；也可以在画布内按住 Ctrl 滚动鼠标滚轮缩放，浏览器页面不会跟着缩放
- 节点详情：在 OpenCode、Pi、Codex 之间选择处理 Agent，复制带有当前节点、依赖、状态和验证上下文的提示词
- 顶部主题按钮：切换深色/浅色模式，偏好保存在浏览器本地

无 evidence manifest 时，后端会把计划第 6.2.3 节的状态快照作为 `plan-snapshot` 展示投影；有逐任务 evidence manifest 时，仍以 manifest 为严格证据源。看板不会把“节点已入图”误报为“任务已完成”。
