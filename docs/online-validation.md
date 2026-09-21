# 第6批：全链路功能通过，响应速度尚未达标

测试日期：2026-09-15。测试通过AgentScope 2原生Agent Service的HTTP路由，经真实百炼模型访问真实Excel准备库；没有使用模型替身代替本批真实测试。HTTP由FastAPI TestClient在本机ASGI应用中发起，恢复测试重建应用、连接与Agent实例并读取同一个原生SQLite文件；这不是公网部署、压测或真实全链路进程强杀测试。既有受控会话测试仍包含进程退出恢复。

## 真实结果和调用预算

| 场景 | 结果 | 理解/SQL/解释调用 | 完整耗时 |
|---|---|---|---:|
| CHERY有多少人 | 775条报名记录 | 1/1/1 | 58.704秒 |
| 重建服务后重复投递同一消息ID | 返回已保存的775及解释 | 0/0/0 | 0.172秒 |
| 重建服务后追问其中参加主题大会的人数 | 656条，保留CHERY条件及计划出席口径 | 1/1/1 | 67.605秒 |
| 无关写诗请求 | 理解模块拦截，不进入查询 | 1/0/0 | 23.907秒 |
| 邀请国家原值为冰岛的姓名/公司 | 空结果，保留列，不调解释模型 | 1/1/0 | 43.656秒 |

合计4个不同问题+1次重复投递，5/5符合预期。共9次真实模型调用：4次Flash理解、3次Plus SQL、2次Flash解释。查询模块实际执行3次。没有自动模型修复或重试，重复投递不生成SQL、不查库、不重新解释。656的参照由独立SQL在真实库中核算；结构化结果和自然语言中的775、656及计划出席口径已核对。

## 耗时结论

| 阶段 | CHERY首次问题 | 重启后主题大会追问 |
|---|---:|---:|
| 轻量理解模型 | 21.820秒 | 23.139秒 |
| Plus生成SQL | 18.086秒 | 22.952秒 |
| 轻量解释模型 | 17.767秒 | 21.273秒 |
| 实际SQL执行 | 11毫秒 | 20毫秒 |
| 三个显式检查点合计 | 13毫秒 | 14毫秒 |

慢主要集中在模型调用阶段。当前证据不能继续细分为供应商推理、网络连接、SDK事件或流式处理；不能直接归因于SQLite，也不能认为改成Flash就一定达到快速响应。本批功能验收通过，性能目标尚未通过，后续优先诊断模型请求耗时。没有为了定位慢反复重跑整套真实模型题。

## 本轮改动严格限于编排与组合根

只修改app/bootstrap.py及orchestration中的query_agent.py、query_workflow.py、session_state.py；业务模块代码与真实数据库哈希不变。无新顶层业务模块、模型工厂或会话数据库。

正常顺序：原生会话恢复 → 理解 → 若ready则查询 → 先保存查询结果 → 呈现 → 保存最终回复 → 原生消息事件。业务服务仅通过公开DTO和端口串联；理解未ready不进入下游。数据准备仍是查询前的独立流程，问数不会触发Excel导入。

组合根用原生凭证的get_chat_model_class创建SQL模型，理解/解释默认使用Flash，SQL使用Plus。不会创建自研模型注册表或缓存。正常本次运行的SQL客户端通过AsyncExitStack释放；呈现若与理解型号相同，复用框架模型。显式只重试呈现时不创建SQL模型、不连接业务库。

SessionReply保留outcome（理解）、query、presentation、query_trace_id和context_saved，客户端可以区分理解成功、查询成功和呈现失败。SessionEnvelope在原生AgentState中保存last_query、last_reply及inflight；原生SQLite负责持久化，未建立另一套会话表。

查询ok才更新last_successful_result_ref并保存本次结果；query error不更新，clarification保存PendingChoice。save_query_result在呈现之前真实提交。呈现失败或取消不抹掉成功结果，可显式仅重试呈现。最近缓存回复的相同消息ID直接返回缓存，近8轮已识别但不再有完整缓存的ID返回重复轮次提示；不是永久幂等账本。同一ID复用于不同问题会被拒绝。

上下文签名包含用户、会话、目录、权限及SQLite文件修订信息；发生变化时保守地失效旧上下文/候选/结果。当前修订判断为文件mtime/size，适用于本POC；后续采用WAL持续发布、多来源或PG时，应由查询/发布公共端口暴露版本，不把文件属性当通用数据版本协议。

## 故障与独立回归

全套135项自动测试通过（前批130+本批5），ruff检查通过。新增受控测试使用真实AgentScope服务和真实Excel SQLite，仅模型返回或故障可控，未将替身称为真实模型验收：

- 完整查询和呈现，以及应用重建后重复投递零重算；不同请求复用消息ID被拒绝。
- 解释故障后重建应用，只传入呈现端口重试；查询生成和理解计数均保持1，证明未重跑上游。
- 无效SQL被校验节点拦截，成功结果引用保持空，错误不伪装成空结果。
- 同名Autozone产生真实数据库候选，选择“第一个”不再调用理解模型，并只返回所选报名记录。
- 查询完成、解释阻塞期间取消，SQLite仍保留成功结果和引用；重建应用后仅重试呈现。

原有10项会话生命周期测试显式注入隔离端口，只测试理解/会话，不用假凭证误触发新下游。原AgentScope同会话409路径的未await协程警告仍存在，非本批新增；不修改框架私有代码规避。

## API与运行

```bash
pip install -e '.[dev]'
python -m app.main
```

本次没有在用户服务器启动或发布上述端口。默认业务库data/chery-excel.db，只读；原生会话/审计库runtime/ai-query.db。AIQ_BUSINESS_DATABASE可修改业务库路径，AIQ_PRESENTATION_MODE可设data或explain。型号仍用三项阶段配置，凭证通过AgentScope原生/credential/及会话chat_model_config关联。

正常使用原生/agent/、/credential/、/sessions/、/chat/及/sessions/{session_id}/messages接口；正文示例与原生API一致。仅重试呈现仍走/chat/，必须使用新消息ID，并在input.metadata中明确指定：

```json
{
  "action": "retry_presentation",
  "query_trace_id": "本会话已保存的成功查询引用"
}
```

重试请求的input仍需用户文本，如“重试结果解释”。只能使用当前会话、当前上下文中保存的引用，不能传任意SQL或结果让服务执行。业务模型不负责识别此控制动作，也不增加一轮意图模型。

真实测试命令（会产生模型费用）：

```bash
python -m examples.validate_online_query --env-file /path/to/model.env \
  --output validation-online/new-run
```

本批证据在validation-online/real/results.json、acceptance.json、latency.json、audit.db；自动测试在validation-online/pytest.txt；改动边界在change-boundary.json。只导出两张追踪表，临时原生凭证库已清理，不在交付包内。历史测试证据继续保留，不能混为本批新增调用。

下一步优先做模型阶段性能诊断：先分别测量请求/首响应/完成时间及提示长度，检查原生客户端与流式行为，再决定优化；保持每阶段最多一次调用，不以新增复核或自建模型工厂解决延迟。指标标签/单位仍留给查询模块的后续任务，性能诊断不改其业务口径。
