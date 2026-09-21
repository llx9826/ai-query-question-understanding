# AI 问数平台

该服务负责用户与空间权限、AgentScope 会话、Excel 数据集、不可变发布版本和管理页面。自然语言理解、语义检索、SQL 规划、查询执行和答案生成全部通过 HTTP 交给独立的 `WrenAI/services/wren-http` 服务。

当前 [迁移计划](plan.md) 的 S0–S5 已全部完成并通过验收。平台问数入口只有一条调用链：

```text
AgentScope 会话 → 活动 publication → Wren HTTP → Wren Agent/Toolkit → DuckDB
```

平台不读取百炼 API Key，也不直接调用模型。百炼的 Key、Base URL 和模型名只配置在 Wren HTTP 服务。

## 阅读顺序

1. `app/main.py`：读取配置并启动服务。
2. `app/bootstrap.py`：显式创建控制库、会话仓储、数据发布器和 Wren 客户端。
3. `app/orchestration/query_workflow.py`：加载会话、绑定发布、调用一次 Wren、保存结果。
4. `app/infrastructure/wren_http.py`：平台与 Wren 服务之间的 HTTP 契约。
5. `app/modules/datasets/api.py`：上传、版本和回滚入口。
6. `app/modules/datasets/service.py`：Excel 转 DuckDB、Wren Project 和两阶段激活。

## 数据布局

- `runtime/control.duckdb`：数据集、发布、AgentScope 会话、幂等结果和审计。
- `runtime/datasets/published/<workspace>/<publication>/data.duckdb`：不可变业务发布。
- `runtime/datasets/published/<workspace>/<publication>/`：同版本标准 Wren Project。

每个请求绑定 `workspace_id + publication_id`。上传并激活新版本后，新一轮问数使用新版本；历史轮次保留实际使用的版本号。

## 运行

复制 `.env.example` 为 `.env` 并填写三个 Token 与百炼 API Key，然后按
[Docker 部署说明](DEPLOY.md) 启动。管理端默认地址为
`http://127.0.0.1:30001/`，Wren 健康检查为 `http://127.0.0.1:30002/health`。

## 验证

```powershell
python -m ruff check app tests
python -m pytest -q
```

阶段证据位于 `validation-wren/S0-*` 至 `validation-wren/S5-*`。S5 已完成真实大会
Excel、多个文件、关系、版本化移除、回滚、空间隔离和浏览器闭环。

PostgreSQL 保留为后续部署选项。飞书本阶段只保留来源适配入口。
