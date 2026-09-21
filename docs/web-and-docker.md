# 网页与 Docker 启动

## 启动

在项目根目录执行。机器需要安装 Docker Engine 和 Compose 插件：

```bash
# 本交付包已有配置好的 .env，不需要复制示例。
docker compose up -d --build
docker compose logs -f ai-query
```

电脑打开 `http://localhost:38080`。手机与电脑连接同一局域网后，打开
`http://电脑局域网IP:38080`。远程服务器则使用服务器可达 IP，并开放所配置的端口。
端口可通过 `.env` 中的 `AIQ_HTTP_PORT` 修改。页面入口、静态资源与 API 同源，不需要配置前端 API 地址。

`.env` 中模型密钥只在后端读取，不进入前端构建产物。本次交付按要求在 .env 中附带真实密钥，Compose 在运行时读取；.dockerignore 会将其排除在镜像构建上下文之外。
页面默认使用本地 POC 访问凭证；如修改 `AIQ_API_TOKEN`，在页面“连接设置”填写相同值。

## 数据和持久化

- 本包带真实 Excel 已导入的 `data/chery-excel.db`，不是模拟业务数据。
- 镜像内业务数据只读。问数不会重新导入 Excel，也没有新增上传接口或改动数据准备模块。
- 原生会话、凭证、查询审计和工作区放在 `query-runtime` 命名卷。
- `docker compose down` 后再启动保留该卷；`docker compose down -v` 会删除会话数据。
- 当前原生消息总线和会话运行锁为进程内实现，固定一个 worker；不要通过多 worker 扩容此版本。

## 页面操作

1. 输入自然语言问题或点击示例填入输入框，再点发送。
2. 当前会话支持追问；新建会话会隔离上下文。会话可搜索、重命名，刷新后恢复。
3. 查询阶段读取真实审计摘要。SQL 完成并保存后先展示结果，文字解释随后补齐。
4. 标量突出显示；多列结果按接口列定义展示，支持分页、横向滚动和 CSV 导出。
5. SQL、参数、数据快照和查询编号可展开查看。CSV 仅导出已返回行，截断时明确提示；文本公式前缀作保护。
6. 同名候选通过按钮返回已有候选 ID。历史轮次候选和解释重试按钮不再用于当前轮次。
7. 停止走 AgentScope 原生中断接口。解释失败时只重试解释，不重跑理解和 SQL。
8. 断网不自动重新投递模型请求；恢复后读取后台状态。桌面 Enter 发送、Shift+Enter 换行；手机点按钮发送。

## 目录与责任

| 位置 | 责任 |
|---|---|
| `frontend/src/App.tsx` | 页面、会话切换与交互状态 |
| `frontend/src/components/` | 结果展示、审计进度展示 |
| `frontend/src/api.ts`、`types.ts` | 网页接口客户端与结果类型 |
| `app/web/routes.py` | 网页接入、原生会话适配、审计摘要投影 |
| `app/bootstrap.py` | 注册网页接口 |
| `Dockerfile`、`compose.yaml` | 多阶段构建、单服务同源部署、持久卷 |

`app/web` 是接入层，`frontend` 是客户端，不是新增业务模块。六个业务模块与原有节点 DTO 不变。
接入层通过 AgentScope 原生 HTTP 接口进行会话 CRUD、请求投递和中断，不依赖私有服务方法。
模型参数、路由和调用预算不变，网页轮询不会调用模型。

## 本地开发

Python 3.11 环境：

```bash
pip install -e '.[dev]'
python -m app.main
```

另开终端启动前端（Node 22.12+）：

```bash
cd frontend
npm ci
npm run dev
```

Vite 将 `/ui-api` 转发到本机 8000 端口。生产构建执行 `npm run build`；后端启动时发现
`frontend/dist` 就会提供首页和资源，因此构建后需要重启此前已启动的后端。

## 验证与限制

- 后端完整回归：137 项通过，包括网页接入的真实 SQLite 查询、恢复、凭证不外发与跨用户隔离。
- React DOM + 真实 HTTP 后端联调：用受控模型输出/故障，数据直接查询真实 Excel SQLite。
  验证标量 775、连续追问 656、解释重试不重跑上游、状态恢复、表格分页、停止请求。
  此测试不是浏览器布局测试，也不是新一轮真实百炼模型准确率验收。
- TypeScript 检查与 Vite 生产构建通过。
- 当前执行环境没有 Docker，未完成镜像构建及容器实机启动。
- 当前云浏览器拒绝本地文件访问，截图没有生成；桌面、手机的最终视觉验收仍待真实浏览器完成。
  已提供可下载的自包含 HTML 预览，可切换桌面/手机宽度；预览不连接后端、不包含模拟回答。

可复跑命令：

```bash
pytest -q
# 启动临时真实后端，运行 React DOM 联调；仅模型输出受控。
python examples/validate_web.py --dom
# 在支持浏览器的本机执行截图和浏览器交互验收。
cd frontend
npx playwright install chromium
cd ..
python examples/validate_web.py
```

报告保存在 `validation-web/`。浏览器脚本已提供，但本次未跑通，不能当作通过记录。
