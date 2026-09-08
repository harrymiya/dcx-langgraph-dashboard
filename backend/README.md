# Bundled LangGraph service

这是控制台使用的本地 LangGraph 服务，图定义和任务快照都位于当前项目内：

- `langgraph.json` 注册 `refactor_dag`
- `graph.py` 构建并编译 LangGraph DAG
- `tasks.json` 保存当前 131 个业务节点、依赖、状态和任务属性

运行项目根目录下的 `npm run dev:all` 时，启动脚本会自动创建
`backend/.venv` 并安装 `requirements.txt`，随后启动 LangGraph API（8123）和
Vite 前端（5175）。
