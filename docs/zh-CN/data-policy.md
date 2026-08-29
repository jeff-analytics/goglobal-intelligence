# BorderMargin V5.3.8 数据规则

## 数据优先级

1. 用户确认或上传的数据
2. 官方 API / 官方结构化数据
3. 官方来源的 AI Evidence Recovery
4. 可信公开来源的 AI Evidence Recovery
5. 缺失

用户输入不会被 AI 自动覆盖。

## 数值规则

影响商业判断的数值必须满足至少一项：

- 来自公开或授权数据源
- 来自用户企业数据
- 来自带来源 URL 的 AI Evidence Recovery
- 由上述数据通过确定性公式计算

模型记忆不能直接填写贸易额、税率、汇率或市场价格。无法追溯来源的数值保持 missing / unavailable。

## Marketplace

- eBay Sandbox 只用于接口和 taxonomy 验证
- 用户上传市场观测可作为用户数据进入 Comparable Engine
- AI 公开网页价格必须保留商品页 URL，并经过 Comparable Engine
- 用户上传或人工确认的 benchmark 优先

## Tariff

全球 HS6 关税数据用于研究比较。最终税负仍应结合当地 tariff line、原产地待遇、优惠安排和当前贸易措施核验。

## Evidence Level

- A：官方 API / 官方结构化数据
- B：官方网页或文件中的可追溯证据
- C：可信第三方公开证据
- D：用户上传或确认的数据

系统保留数据来源、获取方式、时间和置信度。

## 系统配置

ISO code、marketplace identifier、UN Comtrade reporter code、currency code、API endpoint 等属于系统 reference/config，不直接生成商业结论。
