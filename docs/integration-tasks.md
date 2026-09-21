# 后续接线任务与责任

截至第2批已完成问题理解和独立AgentScope会话入口。原工作目录及完整服务代码未修改，新代码在独立模块目录内，无旧方法兼容层。

| 所属模块/层 | 后续任务 | 验收 |
|---|---|---|
| AgentScope编排/组合根（已完成） | 以框架user/session、目录和可见范围生成context_key；在调用前保存本轮尝试；await UnderstandingPort.run；所有结果保存next_context；在取消/进程中断时完成框架收尾 | 真实框架会话重载可见失败轮次；并发会话隔离；不仅测试JSON序列化 |
| 编排层 | 移除旧QuerySpec补丁、在编排中选择同名人员的规则；将候选、回复交给resolve_followup；恢复QuestionRequest与结果引用 | 编排不含实体选择逻辑；不自建会话数据库 |
| query_execution | 消费QuestionRequest+SqlSemanticContext+服务端范围，完成真实值核实及通用SQL节点 | 多值/集合/动态明细真正执行正确；不调用旧QuerySpec翻译器 |
| query_execution→问题理解 | 将同名候选及固定快照证据通过Candidate/PendingChoice传回；证据引用唯一且不能占用catalog:命名空间 | 人名相同ID不同可选择；候选来源/快照过期时调用方使context_key失效 |
| answer_presentation | 消费动态QueryResult及TurnOutcome理由 | 不依赖固定operation列，不把无数据与能力不支持混为同一说明 |
| 编排层 | 成功SQL执行后更新last_successful_result_ref，失败不更新；next_context不是“已经持久化”的证明 | 已理解、已执行、已呈现三种状态可分别追踪 |
| 语义目录 | 若新证据发现口径缺失，再改其配置；本批没有修改原语义目录 | 不承担运行时值读取或会话逻辑 |

QuestionRequest没有执行权限；服务端不能因status=ready就直接信任任何模型生成SQL。新QuestionRequest与当前旧QueryIntent不同，完整入口迁移在查询/呈现模块齐备后进行，期间不增加兼容适配或静默降级。

纯输入DTO的Schema错误由模块/节点CLI返回明确归属，编排需将它记录为契约错误。用户取消不转换成普通模型失败，框架收尾需单独验证；本批已通过真实SQLite、取消及OS进程重启验证。

第2批实现详见session-runtime.md，实测详见session-validation.md。会话生命周期已完成；完整SQL链路接线仍待查询和呈现模块契约落地。新增理解模块任务：实际百炼追问的证据引用不稳定（classify_outcome识别invalid_evidence），失败后模型结构化输出不稳定（interpret_question内部model_call）。应核对证据Schema、提示与模型原生结构化特性，按通用契约修复，不能改成忽略无效证据或按这三道题写规则。

第3批更新：上述问题理解证据与结构化任务已完成本批验收，含同名范围与一次模型调用优化，见understanding-fix.md。后续先改query_execution。端到端耗时仍有12–22秒样例；若继续优化该部分，由接线/基础设施侧先分别测量模型请求、连接建立及持久化耗时，再决定是否使用框架提供的客户端复用。该项不交给理解节点猜测处理，也不因此增加第二次模型调用。


第4批更新：query_execution六节点与动态QueryOutcome已完成SQLite独立验收，详见query-execution.md。旧QuerySpec查询公共接口已移除；当前在线理解入口仅使用保留的服务端AccessScope，不受影响。后续首先完成answer_presentation的动态结果闭环（默认0模型调用），再改编排：消费QueryOutcome.result、保存PendingChoice、更新last_successful_result_ref。首次模型请求约26秒的问题已归到model_call阶段，具体连接/SDK原因尚未验证，后续由组合根/基础设施负责，不加入理解或SQL业务节点。


第5批：answer_presentation四节点已完成，输入PresentationRequest/输出PresentationOutcome；解释最多一次Flash调用，失败保留已获取结果。模型选择使用AgentScope原生配置/凭证能力和三项业务角色映射，自建ModelFactory已删除。下一步归编排/组合根：把理解、查询、呈现的公开端口串联，框架会话保存pending_choice、last_successful_result_ref与呈现状态；只在查询成功后更新查询引用，解释失败不回头重查。上游单位/指标标签补充归query_execution，当前呈现不猜单位。不要新增第七个业务模块或自建会话/模型管理层。


第6批：原生入口接线和成功查询检查点已完成，135项自动测试通过，4题+重复投递的真实模型/SQLite测试5/5符合预期。呈现重试通过原生消息metadata的retry_presentation动作，仅读会话已保存结果。下一优先任务改为模型调用性能诊断：完整响应约59–68秒，SQL毫秒级，不能误改数据库或再增加模型调用；具体SDK/网络原因需测量后决定。报告见online-validation.md。
