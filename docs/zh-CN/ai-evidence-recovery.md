# GoGlobal Intelligence V5.4.0 AI Evidence Recovery

## 数据优先级

1. 用户手工确认或上传的数据
2. 官方 API / 官方结构化数据
3. 官方网页或文件中的可追溯证据
4. 可信公开网页中的可追溯证据
5. 缺失

AI 只补充缺失的外部数据，不自动修改用户输入。

## 可补充的数据

- 贸易规模、原产地贸易值与份额
- 来源国结构与集中度
- 关税参考、当地税号候选
- VAT / GST 等税率证据
- 汇率证据
- 市场准入要求
- 公开 marketplace / retailer 商品价格观测

所有数值记录都要求保留来源 URL。无法核验时保持缺失。

## 获取方式

- 已登记官方来源页面提取
- Provider 原生网页检索
- 公开商品页观测

当前直接网页检索协议包括 Responses API、Anthropic Messages 和 Gemini GenerateContent。对于 Chat Completions-compatible 配置，Evidence Recovery 会按能力探测同一 Base URL 的 Responses/Web Search；支持时自动使用，不支持时回退到已登记官方页面提取。

## Evidence Store

每条 AI Recovery 记录保存：

- Market
- Evidence type / field
- Value
- Source name / URL
- Evidence level
- Retrieval method
- Confidence
- Observed time
- Retrieved time

Excel 导出包含 `AI Evidence` 工作表。

## 市场价格

AI 找到的公开价格必须对应具体商品页面和 URL，再进入 Comparable Engine。用户上传或人工确认的市场价格优先于 AI 获取的公开价格。

## 用户数据保护

以下内容不会被 AI 自动覆盖：

- 用户确认的 HS / 海关编码
- 用户手工关税覆盖
- 用户手工税率覆盖
- Factory Cost
- Packaging / Freight / Fulfillment
- Platform Fee
- Target Margin
- 用户上传 marketplace observations
- 用户手工市场价格基准
