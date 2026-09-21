# 真实 20 题评测证据

本目录为固定版本的一次真实调用，不能通过重新运行覆盖原记录。

- `manifest.json`：旧题、随机候选池、抽样种子、独立参照 SQL/答案、数据库和应用源码哈希。
- `results.json`：当前网页 BFF 返回的真实完整业务结果、文本、进度和耗时。
- `audit.db`：仅 `query_trace_requests`、`query_trace_stages` 两张审计表，含阶段输入输出、提示词和 SQL。没有原生凭证表或会话密钥。
- `scores.json`、`manual-review.json`：确定性核对与逐题文字复核记录。
- `source-verification.json`：独立读取原 Excel 与参照 SQL 对比，17 道可查询题均一致。
- `report.md`：指标定义、逐题结果、问题归属和修复顺序。

证据包根目录包含本次应用源码、真实业务 SQLite、原 Excel 和评测脚本。业务模块在测试前后未修改。`runtime-versions.json` 记录主要组件版本。

在项目根目录使用已安装项目依赖的 Python 进行离线重放（不会调用模型）：

```bash
python evaluation/twenty-20260915/score.py
python evaluation/twenty-20260915/verify_excel.py data/source.xlsx "$(pwd)/data/chery-excel.db"
```

第二个脚本需要 openpyxl，只读原始工作簿，不修改数据。首次打开工作簿会重置其不准确的尺寸元数据，以完整读取全部 75 列。

重新进行真实模型测试需要配置自己的百炼凭证文件，并使用一个全新的输出目录：

```bash
PYTHONPATH=. python examples/evaluate_twenty.py --env-file /path/to/model.env --output evaluation/new-run
```

本轮两个会话并行，每题只调用一次。不要把后续重跑覆盖到本目录，也不要把新运行结果混入本轮通过率。O07 审计故障导致漏记录，详细限制见报告。
