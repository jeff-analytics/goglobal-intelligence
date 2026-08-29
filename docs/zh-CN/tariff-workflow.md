# 关税数据流程

BorderMargin V4.1 同时保留两条关税路径。

## 1. Connected / official-reference

系统会优先使用能够安全解析的当前官方来源；无法形成唯一税率时，保留 UNCTAD TRAINS / WITS 历史参考，并明确显示来源与年份。

- United States: USITC HTS
- United Kingdom: GOV.UK Trade Tariff
- EU markets: EU TARIC official verification source
- Other configured markets: UNCTAD TRAINS / WITS reference until a market-specific provider is added

HS6 足够做贸易分析，但当前执行关税往往需要更细的本地 tariff code。因此“查不到唯一当前税率”属于正常的数据状态，不会自动填 0%。

## 2. Verified manual rate

如果企业已经从报关行、海关裁定、官方 tariff lookup 或内部合规团队拿到税率，可以在 Trade & Suppliers 页面保存：
- Rate %
- Reference year
- Source / note

保存后重新同步市场，该税率将作为 User override 进入成本和 Decision Case，并保留来源说明。

## 原则

不根据 AI 猜关税，不把缺失税率当 0%，不把历史 WITS 数值包装成当前执行税率。
