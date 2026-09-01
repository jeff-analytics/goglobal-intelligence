# GoGlobal Intelligence V5.4.0 高级决策分析

V5.4.0 把原有的贸易研究、成本测算和 AI Decision Research 扩展到多目标决策、不确定性量化、数学规划、学习排序和网络风险分析。所有模块都基于可见输入与可解释输出，不把算法结果包装成无法拆解的单一黑箱分数。

## 1. Pareto 多目标市场筛选

- 使用 NSGA-II 风格的 fast non-dominated sorting。
- 每个指标显式声明 maximize / minimize。
- 输出 Front 1、Front 2 等层级和 crowding distance。
- 对被支配市场给出一个可验证的 dominator 和逐指标比较。
- 数据不完整的市场单独列出，不参加排序。

参考：Deb et al., *A Fast and Elitist Multiobjective Genetic Algorithm: NSGA-II*。

## 2. Monte Carlo、Latin Hypercube 与 Sobol

成本与利润页面允许对售价、采购、物流、税率、平台费等变量设置区间或分布。

- Monte Carlo：普通随机抽样。
- Latin Hypercube：每个变量边际区间分层覆盖，提高有限样本下的空间覆盖。
- 分布：Uniform、Triangular、截断 Normal。
- 输出：P05/P10/P25/P50/P75/P90/P95、亏损概率、达到目标毛利概率、CVaR 5%。
- Sobol：使用 scrambled Sobol low-discrepancy sequence 和 pick-freeze 设计，输出 S1、ST 与 interaction gap。

实现参考 SciPy `scipy.stats.qmc.LatinHypercube` 与 `scipy.stats.qmc.Sobol`。

## 3. MILP 与预算不确定集鲁棒优化

资源配置变量包括：

- `x(i,j)`：产品 i 在市场 j 的投入。
- `y(i,j)`：是否启用该产品-市场组合。
- `z(j)`：是否进入市场 j。

支持预算、单市场上限、单产品上限、高风险市场上限、最低进入市场数、必须进入、禁止进入和最低投入等约束。

目标支持：

- 最大化名义利润
- 最大化收入
- 最大化鲁棒利润下界

鲁棒模式采用 Bertsimas-Sim budgeted uncertainty counterpart。`Gamma` 控制同一时刻允许有多少个收益系数出现不利偏离。`Gamma=0` 接近名义优化，Gamma 提高时结果逐步保守。求解器使用 SciPy `milp` / HiGHS。

## 4. HS Hybrid Retrieval + Learning-to-Rank

HS 候选流程分三层：

1. **BM25**：对官方 HS6 描述做稀疏词项检索。
2. **Dense Embedding**：word/bigram + character n-gram 通过稳定哈希投影形成固定维度本地 dense embedding；不依赖在线 Transformer，也避免不同 BLAS / OS 下的 SVD 数值漂移。
3. **Pairwise Learning-to-Rank**：用户确认 HS 后保存 `selected > alternatives` 偏好，使用 pairwise logistic ranking 更新特征权重。

排序还显式处理 HS 描述中的否定语义，例如 `not knitted or crocheted`。候选如果否定了用户查询中的关键特征，会得到 `negation_conflict` 惩罚。该机制是通用语言特征，不针对某个 HS 代码写规则。

参考：Robertson & Zaragoza 的 BM25 概率相关性框架；Burges et al. 的 RankNet / pairwise learning-to-rank 思想。

## 5. 全球供应贸易网络风险

从实际取得的 UN Comtrade 双边 HS6 数据构建 supplier → market 图。

输出包括：

- supplier market reach
- global observed trade share
- Top1 / CR3 / HHI
- weighted betweenness centrality
- top systemic supplier exposure
- supplier-removal stress curve

NetworkX 的 weighted betweenness 把权重解释为路径距离，因此实现将贸易额转换为反比距离后计算中心性。网络结果只使用系统实际取得的双边贸易边，不补造缺失国家关系。

## 方法边界

- Pareto 前沿只表示当前所选指标下的非支配关系，不代表最终必须进入。
- Monte Carlo / Sobol 质量取决于用户对变量区间和分布的设定。
- Portfolio Optimization 中的收益和风险系数是规划输入；系统不会把它们伪装成精确需求预测。
- HS 排序提供候选，不替代报关分类责任和 WCO Explanatory Notes / 当地海关裁定。
- 贸易网络是基于可观测贸易数据的结构风险分析，不等同于完整供应链实物流网络。

## 主要参考

- Deb, K. et al. (2002), NSGA-II. IEEE Transactions on Evolutionary Computation.
- Bertsimas, D. & Sim, M. (2004), The Price of Robustness. Operations Research.
- SciPy documentation: `qmc.LatinHypercube`, `qmc.Sobol`, `optimize.milp`.
- Robertson, S. & Zaragoza, H. (2009), The Probabilistic Relevance Framework: BM25 and Beyond.
- Burges, C. et al. (2005), Learning to Rank using Gradient Descent.
- World Customs Organization, Harmonized System overview and HS FAQ.
- NetworkX documentation, weighted betweenness centrality.
