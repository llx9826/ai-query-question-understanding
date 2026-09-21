# 第2批会话验收 · 2026-09-15

会话层已完成；真实模型三轮业务验收未全部通过。测试与真实模型结果分别记录，不合并为“问数全链路通过”。

## 自动测试

最终39项通过：原问题理解29项 + 新增会话10项。证据：validation-session/pytest.txt、pytest.xml。

新增测试使用AgentScope 2.0.8原生HTTP/SQL存储和实际SQLite文件；模型端口输出及故障为明确注入，不返回虚构业务记录。

| 场景 | 结果 |
|---|---|
| 保存后关闭app、重新创建app，继续两轮追问 | 通过，消息和已确认目标恢复 |
| 模型超时后重建app，追问不得回退旧条件 | 通过，要求澄清 |
| 调用原生interrupt接口 | 通过，interrupted结束事件及失败尝试保存 |
| 用户隔离及近期重复消息ID | 通过，越权接口404，重复消息不再次调用模型 |
| 调用前检查点写入失败 | 通过，模型0次调用，不返回ready |
| 调用后检查点写入失败 | 通过，模型已调用1次，失败状态收尾，不返回ready |
| 同会话忙碌与另一会话并行 | 通过，同会话409，另一会话独立上下文 |
| 服务端可见范围改变 | 通过，旧业务上下文失效 |
| SIGTERM结束uvicorn进程后启动新进程 | 通过，恢复失败轮次，追问澄清 |
| SIGKILL强杀uvicorn进程后启动新进程 | 通过，识别磁盘inflight后收尾，追问澄清 |

实际进程重启不是JSON序列化回放。强杀恢复发生在下一次用户提问，不自动续跑被中断模型任务。测试产生的SDK警告见pytest.txt及session-runtime.md，未隐藏警告。

## 本次真实百炼调用

由examples/validate_session_model.py通过原生agent、credential、sessions、chat接口进入实际模型，无替身；第一轮后关闭app，重新创建app和连接池读取同一个SQLite文件。

| 问题 | 实际结果 | 主责任 |
|---|---|---|
| CHERY有多少人？ | ready，context_saved=true | 正常 |
| 其中参加主题大会的呢？ | invalid_evidence，context_saved=true | question_understanding/classify_outcome |
| 改成EXEED。 | model_output_invalid，context_saved=true | question_understanding/interpret_question；内部审计span为model_call |

证据：validation-session/real-session-results.json、session-audit.db、persistence-evidence.json。共3请求24阶段，日志失败0。数据库仅含原有两张追踪表，不含模型凭证。

load_context与interpret_question的记录证明：第二轮恢复了第一轮的完整QuestionRequest并交给理解节点；第三轮读取到第二轮的失败尝试。故障已经正确归属、保存且未被伪装成SQL成功。本次真实模型业务断言失败，保留失败记录；不能把这3次调用描述为“三轮理解全部通过”。

理解模块15个文件SHA256与本批前完全一致。本次不修改模型提示或放松证据校验。后续应由问题理解模块检查通用证据引用契约与结构化输出约束，针对正常、歧义、失败后追问分别验证；不要按本题写条件，也不要通过重复调用挑出成功结果。

本批SQL执行0次，没有读写真实名单数据库。语义输入沿用真实Excel的数据准备报告及目录。查询执行和结果呈现是后续独立模块任务。
