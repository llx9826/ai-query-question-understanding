# 字段值标准化与澄清补充修复

本次保持六业务模块，按语义目录→问题理解→查询执行→结果呈现的顺序修改。采集、数据准备、编排持久化、前端、模型配置与实际Excel准备库均未改动。端口仍为38080。

## 问题及修复责任

| 模块 / 节点 | 原因 | 修改后行为 |
| --- | --- | --- |
| semantic_catalog / build_sql_context | 目录要求明确并列口径，理解和SQL提示词却默认保留并列 | query_defaults作为两端共同默认：计划出席、报名ID计数、保留全部并列；用户明确补充优先 |
| semantic_catalog / country_code | 把中文、英文、缩写的解释交给模型，每轮依赖不完整原值样本 | pycountry ISO 3166-1 + Babel/CLDR及gettext，确定性映射为alpha-2；不模糊猜内部代码、区域或混合值 |
| question_understanding / build_understanding_context | 历史虽已保存，未明确整理尚未完成的澄清任务 | 从已有业务轮次和AgentScope原生消息投影ClarificationContext，包含原问题、历史澄清及本轮补充；不新增聊天存储或模型 |
| question_understanding / interpret_question边界 | 真实补充回归发生轮次引用字面量校验失败 | 允许已知历史及本轮ID，在适配边界移除重复本轮引用、去重历史引用；不存在的历史ID仍拒绝 |
| query_execution / read_metadata、execute_sql | 无差别发送国家前100个原值，产生截断警告 | 国家使用只读COUNTRY_CODE函数；其他字段按问题检索相关原值。内部diagnostics仅进入阶段审计，不进入用户warnings |
| answer_presentation / build_view、narrate_answer | 把“模型仅看20行”当成“查询不完整”，误说34人中剩余14人可能更多 | 代码对全部已返回数值列计算数量/min/max，分别传query_truncated和preview_truncated；仍只调用一次呈现模型 |

COUNTRY_CODE属于语义值解释，不改变原值或原表结构。本版由SQLite连接注册只读确定性函数；直接在普通SQLite命令行执行这类SQL时也需注册该函数。未来PG适配应复用同一标准化规则，通过准备阶段派生列或值映射表实现，不能声称本次已支持PG函数。

## 国家处理范围

- 英国、UK、GB、GBR、United Kingdom等确定为GB；中英文名称、大小写、全半角和重音由标准数据及字符规范化处理。
- 少量明确的常用别名（UK、UAE、香港/澳门的常用中文写法、沙特）由代码列出；没有按本次提问维护整个国家字典。
- 真实库128种原值（含NULL），115种可标准化，覆盖2264条记录。另有30条NULL、46条未识别或混合/区域原值，保留不改。
- 未识别例：Y-L、yilang、加勒比、圣马丁、斯洛文尼亚＆克罗地亚等。代码不会根据公司所在地、读音或字符串局部推断国家。未识别值仍支持原值查询。
- 邀请国家不是国籍。国家代码转换不改变该字段的业务含义。

筛选例：`COUNTRY_CODE(country)=COUNTRY_CODE('英国')`。原值或未识别值可直接`country='Y-L'`；语义筛选模板还保留原文精确匹配分支。分组归并用`COALESCE(COUNTRY_CODE(country),country)`，未知及混合原值不丢失。国家映射不需要模型推断所有原值。

## 澄清原则

用户当前明确条件 > 该任务此前用户明确条件 > 目录默认。历史助手问过某选项，不代表用户必须填完一份问卷。

普通“参加”活动按计划出席，极值保留全部并列；不询问是否包含未标记活动。真正缺少指标定义、分子分母、特定人员指代等必要信息时，只问剩余缺项。用户补充后重新判断，不重复已回答项。“未参加”不能擅自等同实际缺席；明确0/空白口径后按补充执行。明确要求实际签到时，说明数据缺失。

契约仍保留original_question（最新原话）和standalone_question（完整任务），SQL接收整个QuestionRequest，而非只接收改写字符串。原生会话保存/恢复继续由AgentScope2负责；本次只增加纯业务投影，不添加Redis或另一套会话数据库。

## 验证证据

实际业务库未修改，SHA256：`29f953774d260e93717c1fb488064490e906192ab9cba0bab48aa87334f84b05`。

| 批次 | 结果 | 模型调用 | 说明 |
| --- | --- | --- | --- |
| real | 数据/路由8/10；另发现预览解释错误 | 24 | 保留原始失败记录；6月3日否定参加被误当实际缺席，补充后又被无匹配日期拦截 |
| final-real | 6/6 | 16 | 34人并列且有姓名；否定计划出席及0/空白补充均530条；实际签到不可用；Y-L精确查询1条；原过度澄清保存后重启，补一句计划出席即查询34人 |
| supplement-real | 1/2 | 2 | 真正澄清完成率后，补充请求在理解输出的轮次引用校验失败，未执行SQL；不计通过 |
| supplement-final | 2/2 | 4 | 澄清完成率→补充分子分母→354/2340=15.13%，未知状态保留在分母 |

旧过度澄清的C0是受控解释器复现历史错误回复，不计真实模型题目；后续C1使用真实百炼模型、真实Excel库及真实AgentScope SQLite重启恢复。所有批次都有HTTP消息、逐阶段输入输出和审计文件；无评审模型、无应用内自动重试。测试本身的受控故障与真实调用明确分开。

final-real完成后仅补充轮次ID边界规范化及提示说明，涉及理解适配器、浅层Schema和理解提示词3处；该边界有针对性测试，并用最终代码完成supplement-final真实两轮。最终代码与supplement-final记录哈希一致。不可将前批记录冒充同一冻结版本的验收；变化记录见validation-clarification/changes.json。

国家专项真实查询：英国105条；印度尼西亚118条；归并后113组，合计2340条，未识别原值及NULL组保留。该批随后只修改理解澄清边界和呈现，国家解释/执行实现未变。单元测试另覆盖标准代码、中文/英文、未知/混合值、作用域隔离和原值查询。

发布全套212项测试通过，2条已有框架警告保留，结果见validation-clarification/release-full-tests.txt。所有真实批次审计写异常均0。常规非空问数3次模型调用；只有澄清或数据缺失判断时1次；国家标准化、消息整理、数值摘要0次。

复现：

```bash
python -m examples.evaluate_clarification --output /tmp/aiq-clarification --env-file .env --final-check
python -m examples.evaluate_clarification --output /tmp/aiq-supplement --env-file .env --extra-check
python -m examples.score_clarification /tmp/aiq-supplement
pytest -q
```

评分器核对SQL结果及路由，少量固定事实检查不等于证明所有自然语言解释都正确。这里的通过率仅针对本批用例，不代表任意问题100%正确。

## 部署与完成边界

升级执行`docker compose up -d --build --force-recreate`。本次目录版本更新，旧语义上下文按既有隔离规则失效；升级后请新建会话完整提问一次。同一版本正常重启的澄清恢复已验证，不声称修复了旧版从未保存的历史。

Docker实机镜像构建与浏览器最终验收仍未完成，当前环境没有Docker。无匹配日期的通用空集合业务表达、超长会话压缩和持续模型延迟仍需单独验收；本批修复了识别原则并验证真实已有日期，不声称所有不存在日期的否定查询均已闭环。未识别原值可查，但不会自动判为某个国家。

## 研究依据

- [pycountry官方包文档](https://pypi.org/project/pycountry/)提供ISO国家实体、代码查找和gettext翻译；本版固定26.2.16。
- [Babel Locale官方文档](https://babel.pocoo.org/en/latest/api/core.html)提供本地化地区名称；本版固定2.17.0。
- [Google Cloud Text-to-SQL技术说明](https://cloud.google.com/blog/products/databases/techniques-for-improving-text-to-sql)讨论业务语义上下文、相关schema检索和数据值定位。这里采用确定性标准化及按需值提示，没有引入另一套问数框架。
- [Dialogflow CX参数机制](https://docs.cloud.google.com/dialogflow/cx/docs/concept/parameter)区分默认可选参数与需要收集的必要参数，并在会话中传播已获取值。借鉴“只收集仍缺的必要信息”的原则；没有引入Dialogflow，状态存储仍为AgentScope2。
