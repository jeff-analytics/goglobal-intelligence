# BorderMargin V5.3.8 模型服务配置

网页入口：`数据源 → 模型服务`

配置字段：

- 服务商名称，可选
- 接口协议
- API Base URL
- API Key，可选
- Model ID

支持：

- Chat Completions-compatible
- Responses API
- Anthropic Messages
- Gemini GenerateContent

`仅测试` 不保存配置。`保存并验证` 验证成功后写入项目根目录 `.env`。

对应环境变量：

```text
AI_PROVIDER=
AI_PROTOCOL=
AI_BASE_URL=
AI_API_KEY=
AI_MODEL=
```

模型服务用于 Evidence Recovery、官方来源提取和 Evidence Brief。未配置模型服务时，现有 API、缓存、用户上传和确定性计算保持可用。

## 2026-08-29：模型与联网研究分离

当前版本在“数据源”中把 AI 配置分为两部分。

### AI 模型
用于结构化提取、推理和 Decision Research Agent。普通用户可以直接选择 DeepSeek / OpenAI / Anthropic / Google Gemini；协议和 Base URL 放在高级配置中。

### 联网研究
- Auto：优先模型原生 Web Search；不可用时使用已配置 Tavily。
- Provider-native：只使用模型原生联网能力。
- Tavily：Tavily 搜索，当前模型综合分析。
- None：仅使用 BorderMargin 本地证据。

AI Evidence Recovery 与 AI Decision Research 使用同一模型配置，但权限和工作流不同。前者可以把验证后的缺失外部证据写入 Evidence；后者输出研究建议和来源，不会修改用户确认数据。
