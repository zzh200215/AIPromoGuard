---
name: financial-compliance-review
description: 金融产品营销文本合规审查——银行理财/基金/保险宣传材料的违规检测与法规条款佐证。当用户要求审查金融营销文案能否发布（如"这段理财文案能不能发"）、检索某表述违反的监管法规（"保本承诺违反哪条规定"）、或对营销文本做监管红线/广告法筛查时使用。通过本仓库的 MCP 服务器（fcr-compliance-review）提供三个工具。
---

# 金融合规审查（fcr-compliance-review）

对金融产品营销文本做双引擎合规审查（规则引擎字面红线 + LLM 语义审查），
并检索法规条款佐证。规则引擎毫秒级零 token；LLM 语义层消耗 DashScope 配额。

## 接入（MCP 配置）

```json
{"mcpServers": {"fcr-compliance": {
    "command": "python", "args": ["-m", "src.mcp_server.server"],
    "cwd": "<本仓库根目录>"}}}
```

前置条件：
- MySQL 在跑且已导入规则/法规索引（`scripts/init_data/` 导入脚本；规则引擎与
  法规检索都读库）。未就绪时 scan_text 报错，先让用户完成初始化。
- `DASHSCOPE_API_KEY` 配在仓库 `.env`：仅 review_text 的 LLM 语义层需要；
  欠费/额度耗尽时 review_text 会失败，降级为 `use_llm=False` 纯规则筛查。
- 详见 `docs/mcp.md` 与仓库 README。

## 工具选型

| 工具 | 何时用 | 成本 |
|---|---|---|
| `scan_text(text, domain?)` | 第一道快速筛查：字面红线（"保本保收益""稳赚不赔"类） | 毫秒级，零 token |
| `review_text(text, domain?, use_llm=True)` | 需要语义层（变体话术/暗示性表述/适当性）时深审 | LLM token，长文本数十秒 |
| `search_regulations(query, domain?, top_k?)` | 检索法规条款佐证，回答"违反了哪条规定" | 毫秒级，零 token |

domain 取值：`banking` / `fund` / `insurance`（可省略 = 全领域）。

## 推荐工作流

1. **先扫后审**：对任何营销文本先 `scan_text`（零成本）；命中严重红线时
   已经可以给出结论，`review_text` 用于补充语义层发现。
2. **佐证闭环**：给出违规结论前用 `search_regulations` 核对条款原文，
   引用"《法规名》第 X 条"式的表述，不凭记忆引用法条。
3. **长文档走 API 通道**：MCP 通道把整段文本压成单块（不切分，适合短文案）。
   完整文档（docx/pdf、对比审查、审查策略 profile、待核验清单、处罚案例
   关联、人工复核流）走仓库 API：上传文件 → 创建任务 → 读报告。

## 结果解读

- `findings[].source`：`rule`（规则字面命中，直接采信）/ `hybrid`
  （规则+LLM 交叉确认，采信）/ `llm`（纯语义判断，建议关注，需人工确认）。
- `severity`：high/medium/low；`confidence` 0-1；`suggestion` 为修改建议，
  转述给用户时给出具体改法而非只报问题。
- `llm_usage.total_tokens`：本次 LLM 消耗。多次审查成本会累积，主动控制
  调用频次，不要对同一文本重复深审。
- 所有结论均为"潜在违规，供人工复核确认"——最终发布判断留给用户，
  不确定时明确说明而不是替用户拍板。
