# AI Quant Trader Pro Start/End Skill 设计

## 目标

创建项目级 Codex Skill `ai-quant-trader-pro-start-end`，统一指导本项目的本地启动、停止、重启、状态检查和验收。Skill 只处理运维流程，不修改业务代码、数据库结构或交易权限。

## 结构

```text
.codex/skills/ai-quant-trader-pro-start-end/
  SKILL.md
  agents/openai.yaml
  scripts/stop-project.ps1
```

## 工作流

- 启动：复用 `scripts/start-local.ps1`，成功后运行 `scripts/verify_local_env.ps1`。
- 停止：调用 Skill 内的 `stop-project.ps1`，只停止 `logs/local-services.json` 登记的进程及本项目 Docker Compose 服务。
- 重启：先停止，再启动，最后验收。
- 状态检查：运行统一环境验收，并保留真实失败原因。

## 安全边界

- 不按端口号终止未知进程。
- 不删除 PostgreSQL、Redis 数据卷。
- 不使用 `docker compose down -v`。
- 不静默忽略启动、停止或验收失败。
- 不修改环境变量、发布锁或交易权限。

## 验证

- 使用 Codex Skill 规范校验器验证目录和 Frontmatter。
- 静态验证启动、停止、重启和状态检查场景。
- 对停止脚本执行语法检查；不在 Skill 创建任务中实际停止当前运行项目。

