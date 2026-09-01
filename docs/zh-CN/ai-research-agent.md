# GoGlobal Intelligence V5.4.0 AI & Research

本发布包加入第一版 Decision Research Agent，同时保留原有 AI Evidence Recovery。

## 两类 AI 用途

### AI Evidence Recovery
用于发现缺失的外部数据、联网取证、结构化提取、验证并写入 Evidence。用户输入、确认 HS、手工关税/税率和上传数据不会被 AI 静默覆盖。

### Decision Research Agent
用于读取当前 Decision Case、GoGlobal Intelligence 已有结构化数据和 Evidence，然后按专业 Skill 生成市场进入研究报告。它可以使用联网研究，但不会直接修改用户成本、确认编码或确定性计算结果。

当前 Skill：
- Market Demand
- Trade & Supply
- Tariff & Tax
- Market Access
- Pricing & Commercial Economics
- Evidence Validation
- Decision Research

## 联网研究配置

模型服务与联网研究已经拆开。

联网研究支持：
- Auto：优先当前模型原生联网能力；不可用时使用已配置 Tavily。
- Provider-native：只用模型服务商的原生 Web Search。
- Tavily：Tavily 负责搜索，当前模型负责结构化分析。
- None：只读 GoGlobal Intelligence 本地证据。

Tavily API Key 为可选配置。若当前模型支持原生联网搜索，则无需 Tavily。

## 决策页

“AI 决策简报”升级为“AI 决策研究”。第一次点击进入确认状态，第二次才真正调用模型/联网研究。

报告包含：
- AI 建议与规则结果分离
- 市场需求
- 供给与竞争
- 市场准入
- 价格与经济性
- 关键风险
- 尚未验证事项
- 推荐行动
- 决策表述
- 可点击的联网研究来源

## 跨平台

同一个源码包同时支持 Windows 与 macOS。

Windows：`run_win.bat`

macOS：`run_mac.command`

项目统一要求 Node.js 22.12+。macOS 启动脚本会自动检查 Node 版本并在 UI 可用后打开浏览器。
