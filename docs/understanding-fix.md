# 问题理解模块修复 · 2026-09-15

本批只改question_understanding业务模块及相关测试/说明，其他44个app文件的SHA256保持不变，包括SQLite会话、编排、组合根与其他业务模块。模块和节点的公开输入输出不变，仍为UnderstandingRequest → TurnOutcome；没有增加业务模块、旧接口兼容层或新框架。

## 证据与调整

| 发现 | 根因证据 | 本批修改 |
|---|---|---|
| 活动证据引用失败 | 旧模型返回catalog:e48…，合法ID实际为catalog:event_e48…；旧Schema只声明string，没有可选值 | 统一evidence_index；直接提供完整白名单，同时用Pydantic Literal生成本轮枚举，模型不再拼接前缀 |
| 结构化输出失败 | 旧审计仅有StructuredOutputError→ValidationError，缺少字段细节；提示包含并不存在的clarification类别，非ready字段限制未反映到Schema | 修正类别用语；用Pydantic判别联合区分ready/非ready，及new/followup，限制非法字段组合 |
| 同名活动被擅自合并 | 第一轮扩展测试中，两天的同名活动被模型默认为任意一场，用户没有确认 | 显式列出目录同名活动组及日期，要求明确日期/场次或合并范围；用户已明确日期或任意/全部时继续处理 |
| 值别名方向容易误读 | 模型在assumptions中把用户别名描述为数据库原值 | 模型内部输出移除自由assumptions，不再重复生成目录解释；完整问题保留用户原词和合并要求，字段映射仍由目录及查询模块负责 |
| 模型校验与服务端各建证据集合 | 原classify_outcome与提示各自处理候选、历史和目录证据；重名ID可能被字典更新覆盖 | 输入构建、模型适配、结果核验共用同一索引；冲突证据直接拒绝，不让新候选覆盖历史事实 |

第二次旧失败的具体字段不可从历史记录还原，不能声称已经找回该次原始错误。现在只记录安全的校验路径和错误类型，写入既有model_call审计span；不记录异常正文、密钥或未经筛选的错误输入。

## 职责与文件

- nodes/build_understanding_context.py：调用统一证据索引检查输入一致性。
- adapters/agentscope_model.py：显式证据/目录歧义投影，调用AgentScope原生结构化输出，并记录安全校验诊断。
- adapters/decision_schema.py：使用Pydantic create_model、Literal及判别联合产生本轮模型Schema，转换为既有ModelDecision。
- nodes/classify_outcome.py：继续严格核验模型返回证据，复用同一索引；不自动修正拼错的ID，不静默丢弃非法实体。
- evidence.py：模块内部纯函数，统一当前目录、候选、历史实体及历史轮次的引用集合。
- prompts/understand.txt：清楚区分可查询、澄清、拒绝、缺数据及失败追问；同名范围不能靠模型自定。

没有自行实现JSON解析器、会话存储、条件DSL或模型重试循环。继续复用AgentScope 2.0.8的generate_structured_output，以及[Pydantic判别联合](https://docs.pydantic.dev/latest/concepts/unions/#discriminated-unions-with-str-discriminators)和[动态模型](https://docs.pydantic.dev/latest/concepts/models/#dynamic-model-creation)。模型Schema仅是适配器内部传输结构，不传给SQL模块，也不改变公开业务契约。

合法ID只能证明引用存在，不能单凭这一点证明语义选择正确；同名消歧仍需真实模型语义验收。后续查询执行必须自行核实真实值及只读SQL，不把理解ready当成权限或执行成功。

## 回归证据

自动测试、独立回放和实际模型结果见validation-understanding-fix。旧失败记录validation-session保留；本批第一轮扩展测试module中的同名歧义失败也保留，不能将其中的ready记为语义通过。final-module/final-session为第二次验证，仍暴露附加说明中别名方向错误；release-module/release-session为移除模型assumptions后的第三次验证，出现已给日期仍澄清。最终输入改用中性的same_name_events，要求先应用用户日期和范围再判断；accepted-module/accepted-session为第四次验证，仍有一组同名活动被擅自合并；review-module/review-session为按需增加第二次模型核验的试验版本；用户要求优先减少调用后，该实现已撤销。single-call-module/single-call-session是当前最终实现。acceptance.json逐项核对状态、条件、活动ID、动态字段及落库结果。

公开合同schemas.py、public.py、ports.py未修改；逐节点CLI回放与模块输出仍相同。change-boundary.json及docs/understanding-source-before-fix.json记录修改边界与基线，docs/understanding-source-sha256.json记录当前实现。

模型内部ready分支不再提供assumptions字段，避免让模型另写一份与目录重复或冲突的知识。公开QuestionRequest/ModelDecision的assumptions字段保留，模型路径返回空元组；公开契约及确定性候选选择不改。所有用户条件必须写入完整问题，不能因不再输出assumptions而丢失合并口径。

## 单次调用与确定性校验

已删除event_scope_review.py及第二次模型调用。模型一次输出event_scope_checks和decision：前者只给出同名活动是否明确范围、对应用户原话片段；后者给出完整问题或澄清。apply_scope_checks用代码核对检查项是否存在、用户片段是否确实来自当前问题或可信历史；证据缺失、未明确或片段伪造时返回ambiguous。不使用第二个模型复核，不写自定义日期解析器或条件DSL。

普通自然语言理解最多一次AgentScope结构化调用；明确候选序号由resolve_followup直接处理，零模型调用。传输Schema、动态证据枚举及分支约束继续使用Pydantic原生组件。温度在本节点调用时设为0，不改变其他模块；60秒总预算、无SDK/客户端重试配置保留。

模型投影减少重复信息：保留字段业务含义、类型及别名，移除字段重复的存储属性；活动名称、日期和完整证据ID合并展示，不再提供两份相同活动清单。公开SqlSemanticContext完全不变，完整目录仍由下游查询模块使用。

用户范围片段匹配和Schema能检查结构、出处，无法独自证明语义判断永远正确。因此继续以真实多轮、同名未明确/明确日期/明确集合等反例验收，不宣称任意自然语言100%可靠。

## 当前验收与速度

- 55项自动测试通过；四节点CLI回放与模块结果一致。包含一次调用上限、伪造范围片段拒绝、非ready结构约束、证据冲突和原有会话恢复测试。
- 最终16个真实请求对应16次AgentScope SDK调用，另1次注入超时。原三轮重启续聊、失败后追问、多值合并、双活动交集、动态字段、缺数据、无关请求、两组同名及明确日期/任意范围均符合本批检查。
- 两库共17请求93阶段，未结束阶段0、日志失败0；业务SQL执行0次。acceptance.json记录具体检查，性能记录在performance-comparison.json。
- 与双调用试验相比，提示正文中位字符数29517→20101（约减少32%）；包含Schema后34364→25653（约减少25%）。同名相关三个样例均值5.166→3.464秒，减少约33%。
- 这只是分时小样本；完整会话接口本次三轮分别14.771、11.858、22.000秒。首批模块调用也出现约31秒，均如实保留。没有证据把全部剩余延迟归因于网络、模型或连接建立，后续需接线/基础设施侧分别测量，不能在业务节点盲目加缓存或改会话。

模型核验试验及各轮失败全部保留，最终只以single-call-*作为当前版本证据。临时双调用方案没有写入最终代码包的运行代码。
