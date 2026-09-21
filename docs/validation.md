# 问题理解模块验收记录

本轮交付是第一批独立模块实现，未切换完整问数入口。语义目录和其他依赖保持基线内容，原完整项目未修改。

## 自动验证

- 29项pytest通过，包含真实AgentScope SDK配合HTTP替身的结构化输出测试；不能计作真实百炼调用。
- 4个节点均通过CLI JSON输入输出回放；节点串联与模块run输出一致。
- Ruff检查与格式检查通过；节点不依赖框架/数据库/编排，不调用兄弟节点。
- 超时后JSON序列化与恢复、正常追问、证据防伪、候选选择、范围变化、重置、历史裁剪与外部取消已验证。
- 会话存储没有自行实现；真实AgentScope服务持久化恢复在下一批。本轮JSON往返不是Redis持久化验收。

## 真实模型最终完整运行

模型qwen3.7-plus，AgentScope 2.0.8；真实Excel目录chery-excel-2026-v3。9次真实模型调用加1次明确标记的注入超时；只验证问题理解，无业务SQL执行。

| 用例 | 状态/原因 | 核对 |
|---|---|---|
| normal-1 | ready / ready | CHERY报名记录数 |
| normal-2 | ready / ready | 保留CHERY并添加主题大会 |
| normal-3 | ready / ready | 改为EXEED，保留主题大会 |
| multi-values | ready / ready | 英国与UK均保留 |
| intersection | ready / ready | 保留同时参加两场活动的要求 |
| dynamic-fields | ready / ready | 保留姓名、公司、职务、入境航班号 |
| missing-data | unavailable / data_missing | 明确没有实际签到数据 |
| out-of-scope | rejected / out_of_scope | 写诗请求被拦截 |
| after-failure | clarification / failed_turn_context | 省略追问澄清，不退回旧条件 |
| injected-failure | error / model_timeout | 保留本轮尝试，不标记意图已确认 |

检查输出的目标、条件、字段及拒绝理由，不以status=ready单独作为答对。9次最终真实理解符合本次用例预期；不把它写成SQL准确率或全面覆盖率。首次两次调用约25秒，随后约1.8—3.5秒；样本不足以承诺线上时延或证明历史60秒超时已根治。

`validation-release/understanding-audit.db`沿用query_trace_requests/query_trace_stages，共10请求、49阶段；没有未结束阶段或logging_failed。trace逐题对应下表。结构化输出及输入上下文保存在real-model-results.json。

## 修复过程保留

1. `validation`：最初实现的9次真实调用及1次注入超时。发现模型重复抄写实体字段名导致两次证据检查失败；已改为模型只选择证据ID，程序填充实体事实。
2. `validation-final`：人为取消的短暂配置验证，不计入最终成绩。日志保留该次取消，不当作完成运行。
3. `validation-accepted`：auto策略试验，9次真实调用及1次注入超时；有两次结构化失败。目录名不代表它已验收通过。
4. `validation-final-forced`：显式指定结构化工具并关闭思考的试验。仍发现类别与状态填错；structured-probe.json保存一次额外真实诊断调用的结构化参数，证明模型将out_of_scope填入status而不是允许的rejected。
5. 最终将模型输出简化为单一kind，服务端确定status/reason，完成`validation-release`完整复测。

这些早期失败不删除、不混入最终成功记录。因为模型schema已调整，旧文件用于诊断，不能按新Schema回放。总调用次数不能只报最后9次；各阶段完整结果及审计库随包保留，另有1次诊断调用与被取消的运行。

AgentScope默认结构化策略会在失败时切换策略，即使max_retries=0也不等于只有一次HTTP请求。最终通过公开ToolChoice指定generate_structured_output，百炼组合根配置enable_thinking=false，客户端和SDK重试均为0；模块内仍保留60秒总预算。参考[百炼Function Calling官方说明](https://help.aliyun.com/zh/model-studio/qwen-function-calling)。运行记录仅声明SDK调用，未取得的token和内部尝试数保持未知。

## 后续责任

问题理解本批完成独立闭环。下一批由AgentScope编排层完成真实会话保存/恢复、取消收尾及公开契约接线；SQL生成、执行和动态结果呈现仍由其所属模块实现。原服务未切到半成品接口，没有QuerySpec翻译兼容层。

## 最终trace索引

| 用例 | trace_id | 耗时秒 |
|---|---|---|
| multi-values | `fd0def83f2b24d16a50b0140c8e2b3fc` | 24.656 |
| normal-1 | `47c556f149a14caab54f8853952c9e4e` | 25.265 |
| intersection | `5c567457487f429688a627186fc29d40` | 2.739 |
| normal-2 | `8d589a12159f47f98f4c7925819a6516` | 3.502 |
| dynamic-fields | `9566b433def74d68b209674113fecf05` | 3.139 |
| normal-3 | `d8052f24ab2d4bd698d95894f94759f0` | 3.26 |
| injected-failure | `a06820e30c8f4d28afe145d26eab5ced` | 0.013 |
| missing-data | `70f3a49e33214e078e4b2014a10c2d96` | 2.282 |
| after-failure | `970fa9fbe69148d59519ee0a1e80411e` | 2.622 |
| out-of-scope | `0e6ed31e13784a3ca818a506027ba2a7` | 1.784 |
