# Bundled LangGraph service

这是控制台使用的本地 LangGraph 服务，图定义和任务快照都位于当前项目内：

- `langgraph.json` 注册 `refactor_dag`
- `graph.py` 构建并编译 LangGraph DAG
- `tasks.json` 保存当前 173 个方案任务定义、依赖、范围和验收属性；实施状态与机器证据保存在 `.project-runtime/projects/default/tasks.json`

运行项目根目录下的 `npm run dev:all` 时，启动脚本会自动创建
`backend/.venv` 并安装 `requirements.txt`，随后启动 LangGraph API（8123）和
Vite 前端（5175）。
