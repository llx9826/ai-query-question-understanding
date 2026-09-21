# 结果呈现与模型分工：第5批

当前已完成answer_presentation模块，以及用户追加要求的阶段模型配置。问题理解和SQL业务节点未修改，仅其CLI模型装配和bootstrap中注入模型的配置作必要变更。完整在线问数入口尚未接入查询和呈现，下一批才修改AgentScope编排；本批不是在线完整链路上线验收。

## 为什么保留一次模型解释

单纯表格格式化不需要模型，但用自然语言结合问题解释动态结果需要模型参与。按用户本轮纠正，默认`mode=explain`对非空成功结果调用一次轻量模型；调用方明确选择`mode=data`则零模型。空结果、上游查询失败和候选澄清零模型。没有再加一次“是否需要模型”的分类调用，也没有关键词路由或自动升级强模型。

解释模型只能读取现有问题、允许展示的列/行及数据警告，没有数据库或查询工具。它负责表达，不重新计算业务指标、不推断未提供的原因。代码验证引用的单元格存在，并始终保留原始结果、口径和SQL证据；引用校验不等于证明所有自然语言句子都正确。本批3份真实解释已逐项核对数值和含义，不能据此承诺所有开放式分析都正确。

## 固定模块与节点契约

输入PresentationRequest：完整问题、上游query_trace_id、QueryOutcome、呈现模式与展示预算。输出PresentationOutcome：正常answer或呈现failure，记录本模块model_calls。模块只接收NarratorPort，不接收数据库、会话或整个DAG状态。

| 节点 | 输入 → 输出 | 模型调用 |
|---|---|---:|
| validate_result | PresentationRequest → ValidatedPresentation | 0 |
| build_view | ValidatedPresentation → AnswerView | 0 |
| render_answer | AnswerView → Answer | 0 |
| narrate_answer | NarrationRequest → Answer | 0或1 |

validate_result检查状态载荷、列唯一、行列一致、快照和SQL证据一致，拒绝非有限数和不支持的单元格类型；不重验SQL语义。build_view区分标量、表格、空结果、候选澄清、查询失败。render_answer转义Markdown/HTML，保留列标签、NULL与空字符串差别、ISO日期和Decimal文本。

查询截断和展示截断分开记录；最多展示20行，可配置1–100行，已收到的完整行文本仍保留在AnswerView中。长单元格仅裁剪Markdown预览，不修改结构化文本。标量0不会变成空结果；上游查询失败不伪装成“没有数据”。SQL、快照、目录版本和上游追踪ID保留在结构化evidence中。

narrate_answer失败、超时或引用越界时返回已生成的确定性回答，标明fallback与错误码，不追加模型调用，不重新查库。解释上下文超预算时也返回表格。业务错误返回原始query_failure归属；呈现异常才归answer_presentation。框架取消不被转换成普通失败。

上游暂未提供独立指标单位/语义类型元数据，确定性模板不猜“人/%”。标签和指标单位的补充属于query_execution输出契约任务，本批不倒改上游。模型可以按问题已明确的口径表达，不能自行补缺失单位。

## 使用AgentScope原生能力，不自建模型管理

核对安装版本AgentScope 2.0.8源码后，已删除本轮一度加入的ModelFactory及客户端字典缓存。现使用：

- 公开ChatModelConfig表示模型名称、参数和credential_id；框架会话服务原生负责按配置创建模型及解析凭证权限。
- 公开CredentialFactory.from_dict及credential.get_chat_model_class用于无会话独立CLI装配。该路径只有少量装配代码，没有自己的供应商注册表、工厂类、连接池、会话库或重试管理器。
- 在线现有理解入口继续使用框架注入的原生模型、凭证和客户端，组合根只设置理解阶段型号及关闭重试。session_model_config提供后续会话配置接线所需的原生DTO；目前尚未接通全DAG的三个模型角色。
- 我们只维护三个业务阶段到型号的映射。这属于应用配置，框架不可能自行决定哪个业务模块应使用哪个型号。没有直接导入AgentScope的私有get_model实现。

| 阶段 | 默认型号 | 调用预算 |
|---|---|---:|
| 问题理解（包含意图识别、追问补全） | qwen3.8-flash | 普通问题1；明确候选选择0 |
| SQL生成 | qwen3.7-plus | 1 |
| 自然语言结果解释 | qwen3.8-flash | 1；纯数据模式/空结果/失败/澄清0 |
| Excel处理、目录、SQL校验与执行、格式化、会话保存 | 不使用模型 | 0 |

型号通过AIQ_UNDERSTANDING_MODEL、AIQ_SQL_MODEL、AIQ_PRESENTATION_MODEL配置；共享既有百炼地址和凭证，不再用一个全局AIQ_MODEL_NAME控制所有阶段。示例为config/model-routing.env.example。所有真实生成仍通过AgentScope，SDK与客户端max_retries=0，默认enable_thinking=False。理解和SQL60秒，解释30秒；不自动升配或二次修复。

百炼官方模型列表和本账号/models接口均列出了qwen3.8-flash、qwen3.7-plus。[官方型号列表](https://help.aliyun.com/zh/model-studio/models)。本批未取得账户实际账单或计算成本下降百分比，不宣称精确节约金额。

## 验收

- 全套130项自动测试通过，保留原有96项；新增34项覆盖动态结果、引用、截断、转义、单次预算、失败回退和原生模型配置。ruff检查通过。原有SDK同会话拒绝路径警告保留，见session-runtime.md。
- 复用前批10题真实SQL结果，10题确定性呈现均通过；没有重新生成SQL、重新执行SQL或伪造业务记录。
- 四个节点各自通过CLI输入JSON运行，串联输出与模块输出一致，全部零模型调用。
- qwen3.8-flash真实理解7题：品牌统计、连续追问、无关请求拦截、实际签到缺数据、活动交集、同名活动歧义、英国/UK合并，均符合预期状态；完整问题中关键条件经检查保留。
- qwen3.8-flash真实解释3题：775条CHERY报名、1796条两场均出席、前10组品牌/国家分组；数值、列引用及计划出席口径一致。另一个空结果直接呈现，零模型调用。
- 本批共10次真实轻量模型调用（7次理解+3次解释），Plus调用0次，SQL执行0次。完成真实验收后撤掉自定义工厂的调整只改变装配方式，使用原生类型单测确认，未重复消耗模型调用。
- 真实理解首请求27.214秒，后续约2.4–3.9秒；真实解释约1.6–3.6秒。首请求延迟仍存在；不把模型降配当成所有延迟问题均已解决。

证据在validation-presentation：pytest.txt、light-models/results.json及audit.db、replay-results.json、replay-audit.db、cli-audit.db、change-boundary.json。每阶段输入、输出、模型提示和型号可在SQLite追踪表中核对。模型凭证和原生凭证数据库不在代码包内。

## 运行

```bash
# 零调用回放真实结果
python -m app.modules.answer_presentation \
  --request examples/presentation-replay/module.input.json --data-only

# 一次轻量模型解释：将请求JSON的mode设为explain
python -m app.modules.answer_presentation --request /path/to/explain-request.json \
  --env-file /path/to/model.env

# 独立节点
python -m app.modules.answer_presentation.nodes --node render_answer \
  --request examples/presentation-replay/render_answer.input.json
python -m app.modules.answer_presentation.nodes --node narrate_answer --schema
```

examples/presentation-replay内有四节点Schema、输入输出、模块样例及10份真实结果Markdown。例子默认data模式，避免重放时意外产生费用。

下一步属于编排和组合根：使用AgentScope原生会话把理解→查询→呈现接起来，保存候选、成功查询引用和呈现状态；呈现失败只重试呈现，不重新查库。不再另造模型工厂、会话管理器或第七个业务模块。
