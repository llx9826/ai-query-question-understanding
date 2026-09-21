# AgentScope 2 会话运行入口

本批接通独立问题理解服务：原生会话API → 恢复上下文 → 保存调用前检查点 → 问题理解四节点 → 保存结果 → 框架回复事件。业务节点仍只接收UnderstandingRequest、返回TurnOutcome，不依赖数据库或会话API。

## 组件与数据位置

| 内容 | 实现 | 位置 |
|---|---|---|
| Agent配置、模型凭证、会话、消息、AgentState | AgentScope 2.0.8 AsyncSQLAlchemyStorage | runtime/ai-query.db 原生表 |
| 最近尝试、确认问题、待选实体、运行中轮次 | SessionEnvelope作为AgentState.middle_context.ai_query载荷 | 同一个SQLite文件 |
| 请求与节点输入输出、故障归属 | 既有SqlTraceStore | 同文件query_trace_requests、query_trace_stages |
| 运行锁、通知及流事件传递 | 原生InMemoryMessageBus | 进程内，重启不保留通知队列 |

没有自建会话CRUD或SQLite会话表，没有Redis依赖。SQLAlchemy负责驱动与连接，原生AgentScope存储负责持久化机制。SQLite启用WAL，数据库父目录自动创建；只有一个AIQ_SQLITE_PATH配置。

**当前只启动一个worker、一个服务实例。** 进程内总线不提供多进程锁及跨实例通知。已落盘会话和消息在重启后可查；重启前未发完的SSE片段不重放。中断的模型任务不会自动续跑，下次提问读取检查点并要求明确目标。

## 启动

在本包根目录安装README所列依赖后：

```bash
export AIQ_API_TOKEN='replace-with-your-own-local-token'
export AIQ_SQLITE_PATH='./runtime/ai-query.db'
python -m app.main
```

SQLite路径可省略。启动后的`http://127.0.0.1:8000/docs`是框架原生接口说明。使用Authorization: Bearer对应的API Token；它是服务访问凭证，与百炼模型Key不同。模型凭证通过框架原生credential接口配置，不能把服务Token当模型Key。

| 顺序 | 原生接口 | 必要输入/用途 |
|---|---|---|
| 1 | POST /agent/ | `{"name":"AI问数"}`，保存返回agent_id |
| 2 | POST /credential/ | 下方模型凭证对象，保存返回credential_id |
| 3 | POST /sessions/ | 指定agent_id、名称、chat_model_config，保存session_id |
| 4 | POST /chat/ | 指定agent_id、session_id、用户Msg，异步受理 |
| 5 | GET /sessions/{session_id}/messages?agent_id=… | 查询已存消息及is_running |
| 可选 | GET /sessions/{session_id}/stream?agent_id=… | 原生事件流 |
| 可选 | POST /sessions/{session_id}/interrupt?agent_id=… | 取消正在运行的轮次 |

模型凭证请求体（Key用你自己的值）：

```json
{"data":{"type":"openai_credential","api_key":"YOUR_BAILIAN_KEY","base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1"}}
```

会话请求体（模型名使用百炼账号当前可调用的实际model ID）：

```json
{"agent_id":"AGENT_ID","name":"峰会问数","chat_model_config":{"type":"openai_credential","credential_id":"CREDENTIAL_ID","model":"YOUR_MODEL_ID","parameters":{}}}
```

为会话指定名称可避免框架另外调用模型自动命名。新服务复用该会话创建的AgentScope模型，问题理解适配器仍用原来的结构化输出策略及总时限。

提问请求体：

```json
{"agent_id":"AGENT_ID","session_id":"SESSION_ID","input":{"id":"UNIQUE_MESSAGE_ID","name":"user","role":"user","content":[{"type":"text","text":"CHERY有多少人？"}]}}
```

客户端为每个新轮次生成独立消息ID。近期同ID再次提交会复用保存结果或提示已中断；这不是无限期幂等账本，识别窗口与业务上下文一致为8轮。同一会话忙碌时框架返回409，等完成或取消后再提交。

## 固定接线契约

- SessionEnvelope：契约版本agentscope-session-v1，context、inflight、last_outcome、last_interruption。inflight记录本轮问题、消息ID、reply_id和trace_id，调用模型前真正落盘。
- UnderstandingRequest → TurnOutcome：沿用理解模块契约，无旧QuerySpec转换。
- SessionReply：契约版本session-reply-v1，trace_id、outcome或编排failure、context_saved。经原生DataBlock返回，名称turn-outcome.json；原生messages接口中的数据体为base64 JSON。
- context_saved只确认理解上下文已写库，不代表SQL已执行。last_successful_result_ref由后续查询执行成功后的编排节点更新，本批保持原值。

bootstrap负责配置与依赖装配；QueryBinding负责给Agent传入可信作用域、存储端口及业务端口；QueryAgent通过原生PipelineProtocol接入QueryWorkflow。PipelineProtocol是流接口，本批没有新增通用DAG调度器。

## 恢复与失败行为

正常结果先存next_context再发回复；超时等理解错误也存本轮尝试。用户取消时记录失败尝试、限时保护一次必要写入、发interrupted结束事件，并继续向框架传播取消。若进程被强杀、来不及收尾，下次调用识别inflight，将该轮标记为未完成，再调用理解模块处理新问题。失败后的省略追问由理解模块决定澄清，编排不猜条件。

调用前写库失败不调用模型；调用后写库失败不把ready作为成功回复。编排故障写orchestration归属，模型超时仍归question_understanding/interpret_question。框架负责锁、消息保存及生命周期最后收尾。

身份、会话、目录版本、数据准备快照或服务端范围变化都会改变context_key。身份由服务端Bearer认证解析，不信任请求自己指定user_id。业务SQL范围控制属于后续查询执行，本批没有对名单执行查询。

## 验证与边界

`tests/test_sessions.py`、`tests/test_session_failures.py`使用真实SQLite文件及原生HTTP接口，模型输出和故障可控。跨进程测试实际启动uvicorn，分别发送SIGTERM和SIGKILL，再启动新进程检查恢复。没有构造假Excel记录或伪装真实模型成绩。

真实百炼验收可运行：

```bash
python -m examples.validate_session_model --env-file /path/to/model.env --output validation-session-new
```

此驱动需开发依赖，创建临时原生会话库，真实调用后重建服务续聊，导出回复和仅含追踪表的SQLite证据；不把模型凭证库打入交付包。真实业务SQL仍为0次。

进程强杀时，原请求的审计span可能留在running；后续恢复请求会记录recover_context及原trace_id。本批不回写或伪造崩溃前的结束时间。SDK 2.0.8同会话409拒绝路径可出现未await协程的RuntimeWarning；已验证请求被拒绝且不影响其他会话，没有修改SDK私有实现。

当前问题理解已完成后续修复，原session-validation.md保留第2批历史结果。最新验收见understanding-fix.md：自然语言理解一次模型调用；同名范围与决策在同一结构化输出中处理，代码验证证据，不另发模型复核。
