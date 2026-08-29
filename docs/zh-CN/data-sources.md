# BorderMargin V5.3.8 数据源说明

## eBay Taxonomy

Workspace 和 eBay Research 使用 eBay Taxonomy 获取 marketplace 对应的分类信息。

用于：
- 商品短词分类建议
- 分类树浏览
- Category Path
- Item Aspects
- 当前品类需要补充的属性

应用不在前端预置某个品类的固定规格问题。

## UN Comtrade

用于 Market Scan 和 Trade & Tariff。

主要字段：
- 总进口额
- 指定 Origin 的进口额
- Origin Share
- 多年度贸易历史
- 实际返回年份
- Data Coverage

Origin 通过 UN Comtrade reference 数据动态解析 partner code，不固定某一个国家。

用户可以保存较长的当地 customs code；贸易请求统一使用前 6 位 HS6。

## ECB

用于 FX reference。只有接口返回后才显示。

## WITS / UNCTAD TRAINS

当前作为历史 tariff reference。若没有 numeric observation，界面保持 unavailable。

## eBay Browse Sandbox

用于验证：
- keyword search
- category filter
- marketplace
- sort
- pagination
- listing field normalization
- generic comparable filtering

Sandbox listing 不进入真实市场价格 benchmark。

## 企业私有数据

Cost & Margin 页面使用用户输入的企业参数。系统不预置商品成本、平台费率或目标利润率。
