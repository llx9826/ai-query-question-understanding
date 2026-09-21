# 查询执行模块：一次生成、代码校验和执行

本批只改query_execution及其依赖、测试、启动脚本和文档。问题理解、会话、语义目录和数据准备代码保持原样。完整在线入口目前仍停在问题理解；查询模块已能独立运行，下一批完成动态结果呈现后再由AgentScope 2编排接入，不能把本次验收称为在线全链路已上线。

## 模块和节点契约

模块输入`QueryRequest(question: QuestionRequest)`，输出`QueryOutcome`。请求不能指定权限、数据库路径或快照。组合根持有`AccessScope`、`SqlSemanticContext`和数据库适配器；服务端固定当前已发布快照。模块门面依赖两个Protocol：`DataPort`和`SqlGenerator`。

| 节点 | 输入 → 输出 | 模型调用 | 责任 |
|---|---|---:|---|
| fix_context | QueryRequest → ExecutionContext | 0 | 核对来源和目录版本、固定快照、允许字段及行数预算 |
| read_metadata | ExecutionContext → GenerationContext | 0 | 真实结构和有界低基数取值、核对51场实际活动与目录 |
| generate_sql | GenerationContext → SqlDraft | 1 | LlamaIndex只生成SQL，AgentScope 2执行唯一模型请求 |
| validate_sql | ValidationRequest → SqlPreview | 0 | SQLGlot单语句、表列、函数、CTE作用域校验及服务端范围约束 |
| execute_sql | ValidationRequest → ExecutedRows | 0 | 从原始草稿重新校验、只读查询、超时、截断、重名候选 |
| package_result | PackageRequest → QueryResult | 0 | 动态列和类型、空结果、来源快照、最终SQL及参数、业务口径说明 |

不新增业务模块，不引入SQL条件DSL，不再限制为三个operation。节点不互调，模块service负责顺序；单节点CLI和模块CLI均使用相同DTO。`SqlPreview`只供审计查看，不是可回传执行的凭证。

`QueryOutcome.status`为ok/clarification/error。ok必须包含result；clarification返回既有PendingChoice契约；error包含业务模块、节点、错误码。生成失败或SQL错误不自动调用模型修复，也不重跑理解或同步数据。外层trace_request由组合根管理，六阶段及模型的实际提示、草稿、执行SQL、绑定参数和结果都落到独立审计SQLite。

## 组件的实际接入

锁定AgentScope 2.0.8、llama-index-core 0.14.24、SQLGlot 29.0.1，沿用SQLAlchemy 2。LlamaIndex的NLSQLRetriever使用sql_only=True、DEFAULT解析器和显式本地MockEmbedding，测试禁止生成阶段运行SQL或调用embedding。MockEmbedding只是隔离默认外部配置，当前路径没有向量化计算。

通过CustomLLM.acomplete桥接AgentScope原生generate_structured_output；模型及客户端由组合根创建并复用，SDK及客户端max_retries均为0。桥接实例限制每次生成最多一个SDK调用，温度0、模型预算60秒。当前不启动查询后答案模型、二次校对、自动修复或额外会话。

实际发现当前组件的context_str_prefix没有进入最终提示词，改用公开context_query_kwargs注入真实值、活动、关联及口径，并直接测试最终送给SDK的提示词包含真实活动ID、名称和映射。没有修改框架私有代码。

## 执行约束与目前边界

SQLGlot对真实字段白名单进行qualify；仅将作用域中指向物理表的关系替换成带快照和品牌条件的投影子查询，CTE名称遮蔽不能绕过。参与关系单独查询时也受报名品牌范围限制；已确认registration_id由绑定参数约束报名/参与关系。服务端重验执行上下文，拒绝客户端参数、技术快照列、系统表、外部函数、写语句、SELECT *、未知字段和未授权明细。

SQLite连接使用mode=ro和query_only；执行时间默认5秒，progress_handler中止超预算计算。外层最多取501行，返回500行并准确标记截断；先聚合/排序再截断，不减少计算使用的源数据。数据库线程收到异步取消后仍可能运行至5秒预算，不承诺立即中断。

支持已验收的CTE、子查询、JOIN、EXISTS、IN、AND/OR、UNION、分组、聚合、比例、日期场次、动态列及空结果。函数采取允许列表；递归CTE、未知函数或结构返回明确能力/校验错误。安全校验并不证明每一种自然语言语义都正确，不能据10题宣称覆盖所有问题。

同名人员的精确姓名明细查询返回数据库候选，field使用`registrations.registration_id`，证据包含固定快照。理解模块可以零模型调用处理“第一个”。聚合查询不会强制选择某一个同名人员；复杂范围下的通用实体消歧仍需扩展验收。编排层将来负责保存pending_choice，并在数据版本或权限变化后使旧候选失效。

当前只实现SQLite适配器；未来PG接入需单独实现和验收方言/只读/超时，不因用了SQLAlchemy就宣称PG已经通过。

## 本批验收证据

真实业务库`data/chery-excel.db`完整复制已发布Excel快照：2340条报名、51场活动、119340条参与关系。SHA-256与原已发布业务库一致，运行前后没有修改业务记录。

- 全部96项自动测试通过：原有55项理解/会话测试，加41项查询、隔离、组件预算及候选交互测试。ruff检查及格式检查通过。原SDK同会话拒绝路径的RuntimeWarning仍在，见session-runtime.md；本批不改会话模块。
- 初次真实生成10题、10次SDK调用。7题直接通过，3题因校验器把AND当外部函数被拦截；修正后重放8题通过，另2题暴露上述组件上下文接线缺失。
- 修正上下文后只重调交集、并集两题，两题通过。因此本批共12次真实模型调用，无自动模型重试。最终复用保存的真实草稿执行10题，10/10与独立人工参照SQL一致；最终重放新增模型调用0次。
- 6个独立节点CLI及模块CLI均用保存的真实草稿在真实库运行，节点串联结果与模块输出一致，新增模型调用0次。
- 查询模块实测常规样例约1.4–2.2秒；两个独立进程的首个请求约26秒，耗时集中在model_call阶段。尚未将首请求延迟归因到具体网络/SDK环节，不承诺所有请求都达到常规耗时。

| 问题范围 | 验证结果 |
|---|---:|
| CHERY报名记录 | 775 |
| 英国及UK两个原值 | 105 |
| 主题大会与音乐节全部参加 | 1796 |
| 两场任意参加，报名ID去重 | 2100 |
| 按品牌及国家分组前10组 | 逐组一致 |
| 姓名、公司、职务、入境航班动态明细 | 逐列逐行一致 |
| 全部会议场次，含无人出席场次 | 51 |
| 邀请国家原值冰岛的明细 | 空结果，保留列定义 |
| 4月27日icar品牌伙伴峰会 | 159 |
| CHERY签证completed / CHERY全部报名 | 20.65% |

证据目录：`validation-query/real-model`保留初次真实调用；`context-fix`保留两次修复后调用；`final-replay`保留8/10的中间失败；`accepted-replay`为最终10/10结果；`node-acceptance.json`为CLI验收；`change-boundary.json`为代码边界和业务数据校验；`pytest.txt`为完整自动测试记录。不删除失败记录，也不将回放称为新的真实模型调用。

## 独立运行

```bash
pip install -e '.[dev]'
python -m app.modules.query_execution --request examples/query-replay/module.input.json \
  --allow-details --env-file /path/to/model.env
```

模型配置复用AIQ_MODEL_API_KEY、AIQ_MODEL_BASE_URL、AIQ_MODEL_NAME。凭证不在交付包中。SQLite会话库与查询审计库分开，业务库只读。

零模型费用回放：

```bash
python -m app.modules.query_execution --request examples/query-replay/module.input.json \
  --allow-details --replay-sql examples/query-replay/draft.json
python -m app.modules.query_execution.nodes --node execute_sql \
  --request examples/query-replay/execute_sql.input.json --allow-details
python -m app.modules.query_execution.nodes --node execute_sql --schema
```

用`--brand CHERY`设置服务端品牌范围；缺省允许当前来源所有品牌，`--allow-details`由组合根配置，不能来自用户问题。各节点JSON示例和输入Schema位于examples/query-replay。真实生成验收脚本`examples.validate_query_model`可用`--case`只重测受影响问题，避免无意义地重跑模型。
