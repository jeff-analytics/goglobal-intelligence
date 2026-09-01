# GoGlobal Intelligence

**AI 驱动的市场进入与盈利决策平台**

GoGlobal Intelligence 是一套中英文双语的产品市场决策工具。它把贸易数据、关税与税费、供应结构、Marketplace 研究、成本测算和联网研究放在同一套决策流程中，用于判断一个产品进入目标市场的商业可行性。

系统将确定性计算与 AI 研究分开处理。用户确认的数据和业务假设保持最高优先级，AI 获取的外部证据和建议保留来源并明确标识。

**当前版本：** `v5.4.1`

[English README](README.md) · [更新记录](CHANGELOG.md) · [文档](docs/README.md)

## 核心能力

- **项目设置**：商品、原产地、HS / 海关编码、目标市场和 Marketplace 分类。
- **市场扫描**：按统一指标比较多个候选市场，并使用非支配排序形成 Pareto 多目标前沿。
- **贸易与供应研究**：UN Comtrade 进口额、原产地份额、CR3、CR5、HHI、贸易历史和全球供应网络风险。
- **关税与税费研究**：HS6 关税参考、官方来源证据、VAT/GST 和关税矩阵。
- **Marketplace 研究**：eBay Taxonomy、Listing 研究、Comparable Engine 和价格基准。
- **成本与利润**：成本假设、目标利润、反推售价、Monte Carlo / 拉丁超立方模拟和 Sobol 敏感性分析。
- **决策案例**：根据已有证据和经济性计算形成确定性 Decision Case。
- **Decision Research Agent**：根据当前中英文设置生成研究分析，支持市场、定价、风险、来源和行动视图。
- **产品组合**：使用 MILP 和 Bertsimas-Sim 风格预算不确定集进行多产品、多市场资源配置。
- **HS 候选排序**：BM25 + 本地 Dense Embedding + 否定语义特征 + Pairwise Learning-to-Rank，用户确认结果会形成排序反馈。

## 决策流程

```text
项目设置
  ↓
市场扫描 + Pareto 前沿
  ↓
贸易与供应 + 网络风险
  ↓
关税 / 税费 / 汇率
  ↓
Marketplace 研究
  ↓
成本与利润 + LHS / Sobol
  ↓
决策案例
  ↓
Decision Research Agent
  ↓
MILP / 鲁棒资源配置
```

## 产品原则

1. **确定性计算优先**：利润、售价、集中度和核心决策指标由程序计算。
2. **证据可追溯**：外部证据保留来源 URL、获取信息和证据状态。
3. **用户数据优先**：确认的分类、上传数据、成本和手工覆盖不会被 AI 静默替换。
4. **缺口保持可见**：缺失、临时或冲突证据不会被隐藏。
5. **模型与搜索分离**：AI 模型和联网研究服务可以独立配置。
6. **本地运行**：Windows 和 macOS 使用同一套代码，本地 SQLite 保存项目数据。

## 数据与 AI 接入

| 模块 | 当前支持 |
| --- | --- |
| 贸易数据 | UN Comtrade |
| 关税参考 | UNCTAD TRAINS / WITS、当地官方来源 |
| 汇率 | ECB |
| Marketplace | eBay Taxonomy / Browse API |
| AI 模型 | DeepSeek、OpenAI、Anthropic、Gemini、自定义兼容服务 |
| 联网研究 | 模型原生搜索、Tavily、离线模式 |

AI 与外部服务均为可选配置。即使没有配置模型，项目存储和确定性计算仍然可以使用。

## 技术栈

- 前端：React 19、Vite 8、Recharts、Lucide
- 后端：FastAPI、Pydantic、Uvicorn
- 数据库：SQLite
- 高级分析：NumPy、SciPy / HiGHS、scikit-learn、NetworkX
- 数据处理：Python、requests、openpyxl
- 测试：pytest + 前端 production build 校验
- 系统：Windows / macOS

## 快速启动

### 环境要求

- Node.js **22.12+**
- Python **3.11+**，推荐 Python 3.12
- npm

### Windows

双击：

```text
run_win.bat
```

启动器会自动创建 Python 虚拟环境、安装依赖、校验前端 build、检查本地端口并启动 API 与 UI。

### macOS

```bash
chmod +x run_mac.command
./run_mac.command
```

Intel 和 Apple Silicon 均支持。退出时在启动终端按一次 `Ctrl+C` 即可同时关闭前后端。

### 迁移旧 V5.3.x 数据

Windows：

```text
scripts/windows/migrate_from_existing.bat
```

macOS：

```bash
chmod +x scripts/macos/migrate_from_existing.command
./scripts/macos/migrate_from_existing.command
```

迁移脚本只复制本地配置、SQLite 数据和可复用缓存，不复制 `.venv` 或 `node_modules`。

## 配置

项目提供 `.env.example`。本地启动器会在首次运行时自动创建 `.env`。API Key 也可以直接在系统的“数据源”页面中配置。

不要把 `.env`、本地数据库、虚拟环境、缓存或生成的前端文件提交到 GitHub。

## 仓库结构

```text
GoGlobal Intelligence/
├── backend/                 FastAPI、研究引擎、测试
├── frontend/                React / Vite 前端
├── docs/                    方法、数据和 Agent 文档
├── scripts/
│   ├── macos/               迁移、自检脚本
│   └── windows/             迁移、修复和启动辅助脚本
├── .github/workflows/       CI
├── .env.example
├── docker-compose.yml
├── run_mac.command
├── run_win.bat
├── CHANGELOG.md
├── SECURITY.md
└── VERSION
```

## 自检

Windows：

```text
scripts/windows/self_check.bat
```

macOS：

```bash
./scripts/macos/self_check.command
```

自检会运行后端 pytest 和前端 production build。

## 版本管理

仓库目录保持 `GoGlobal Intelligence`，不在文件夹名称中加入版本号。版本通过 Git Tag 管理，例如 `v5.4.1`，具体改动见 [CHANGELOG.md](CHANGELOG.md)。
