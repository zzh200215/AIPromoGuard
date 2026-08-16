# 金融产品合规智能审查系统 — 产品需求文档 (PRD)

------

## 1. 项目概述

### 1.1 项目背景

金融产品（银行理财、基金、保险）在发行与销售环节需经过严格的合规审查。当前依赖人工逐条核对监管法规，存在以下痛点：

- **效率低**：单份复杂产品文档审查平均耗时 2 小时；
- **遗漏率高**：法规条文分散在 150+ 部文件中，人工难以全面覆盖；
- **一致性差**：不同审查员对模糊条款（如"风险披露不充分"）的理解存在偏差；
- **知识沉淀难**：历史违规案例与审查经验未形成结构化资产。

### 1.2 项目目标

构建一套**基于 Agentic RAG + 规则引擎**的智能合规审查系统，实现：

- 输入产品文档（PDF/Word/文本），自动输出结构化合规审查报告；
- 违规条款召回率 ≥ 90%，误报率控制在可接受范围内；
- 单份文档审查时间压缩至 15 分钟以内（含人工复核）；
- 覆盖银行理财、基金销售、保险产品三大领域。

### 1.3 业务范围

表格



| 领域     | 典型文档类型                           | 核心法规示例                                 |
| :------- | :------------------------------------- | :------------------------------------------- |
| 银行理财 | 理财产品说明书、风险揭示书、销售协议   | 《商业银行理财业务监督管理办法》             |
| 基金销售 | 基金招募说明书、宣传推介材料、客户协议 | 《公开募集证券投资基金销售机构监督管理办法》 |
| 保险产品 | 保险条款、投保须知、利益演示表         | 《保险销售行为管理办法》                     |

------

## 2. 业务需求分析

### 2.1 用户角色与场景

表格



| 角色               | 核心诉求                         | 使用场景                         |
| :----------------- | :------------------------------- | :------------------------------- |
| **合规审查员**     | 快速定位违规点，获取修改建议     | 日常产品上线前审查               |
| **合规团队管理员** | 维护法规库与规则库，监控审查质量 | 法规更新后同步规则，定期抽检报告 |
| **产品经理/法务**  | 了解产品合规风险全貌             | 产品设计和修改阶段前置审查       |
| **系统管理员**     | 保障系统稳定运行，管理用户权限   | 运维与权限配置                   |

### 2.2 核心业务流程（AS-IS → TO-BE）

**AS-IS（现状人工流程）：**

plain

```plain
产品文档 → 人工通读 → 逐条对照法规 → 记录疑似违规 → 查阅历史案例 → 撰写审查报告 → 人工复核 → 输出整改意见
（耗时约 2 小时/份）
```

**TO-BE（系统自动化流程）：**

plain

```plain
产品文档 → [系统] 文档解析与分类 → [系统] 法规智能匹配 → [系统] 规则引擎扫描 + LLM语义分析（并行） → [系统] 冲突融合与风险评估 → [系统] 报告生成 → [人工] 复核确认 → 输出最终报告
（系统处理约 3-5 分钟，人工复核约 10 分钟）
```

### 2.3 业务痛点与系统应对

表格



| 痛点                 | 系统应对策略                                      |
| :------------------- | :------------------------------------------------ |
| 法规分散难检索       | 条款级向量知识库 + 关键词索引，实现语义级法规召回 |
| 模糊条款判断标准不一 | LLM 语义理解 + 历史案例相似度匹配，提供参考依据   |
| 明确违规模式重复劳动 | 结构化规则引擎自动匹配，零延迟输出                |
| 历史经验无法复用     | Neo4j 知识图谱关联"法规-条款-违规模式-处罚案例"   |
| 报告格式不统一       | 结构化模板自动生成，支持人工编辑后导出            |

### 2.4 业务价值

- **效率价值**：审查效率提升约 8 倍；
- **质量价值**：召回率提升至 91%，显著降低合规风险；
- **资产价值**：法规知识库与违规案例库成为企业核心知识资产；
- **合规价值**：审查过程可追溯、可审计，满足监管检查要求。

------

## 3. 功能需求

### 3.1 功能全景图

plain

```plain
┌─────────────────────────────────────────────────────────────────┐
│                        用户交互层                                │
│  文档上传  │  审查任务管理  │  报告查看/导出  │  知识库管理      │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│                        应用服务层 (FastAPI)                      │
│  任务管理API  │  审查编排API  │  报告管理API  │  知识库管理API   │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│                        智能引擎层                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  规则引擎     │  │  LLM语义引擎  │  │   冲突解决与融合      │  │
│  │  (明确违规)   │  │  (模糊语义)   │  │   (规则优先策略)      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Agent 编排引擎 (LangGraph)                   │  │
│  │  文档分类 → 法规匹配 → 条款扫描 → 风险评估 → 报告生成    │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│                        数据与知识层                              │
│  Milvus(向量库)  │  Neo4j(图数据库)  │  MySQL(关系库)  │  Redis │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 功能模块详细说明

#### 3.2.1 文档接入与解析模块 (Document Ingestion)

表格



| 功能点     | 需求描述                                                     | 优先级 |
| :--------- | :----------------------------------------------------------- | :----- |
| 多格式支持 | 支持 PDF、Word（.doc/.docx）、TXT、图片（OCR）上传           | P0     |
| 智能解析   | 自动提取文本内容、表格、层级结构（标题/段落），保留原文档位置信息 | P0     |
| 文档分类   | 基于内容自动识别文档所属领域（银行理财/基金/保险）及文档类型（说明书/协议/宣传材料） | P0     |
| 文档预处理 | 文本清洗（去水印/页眉页脚/乱码）、段落切分、生成文档结构树   | P1     |
| 版本管理   | 支持同一产品多版本文档对比审查                               | P2     |

**关键需求**：解析结果需保留**原文位置信息**（页码/段落编号），用于后续违规条款精确定位。

#### 3.2.2 规则引擎模块 (Rule Engine)

表格



| 功能点     | 需求描述                                                     | 优先级 |
| :--------- | :----------------------------------------------------------- | :----- |
| 规则定义   | 支持正则表达式、关键词匹配、条件组合（AND/OR/NOT）、数值范围判断 | P0     |
| 规则分类   | 按领域（银行/基金/保险）+ 规则类型（禁止性/限制性/披露性）组织规则 | P0     |
| 规则管理   | 规则的增删改查、启用/停用、版本控制、生效时间配置            | P0     |
| 规则执行   | 对输入文档进行全量规则扫描，输出匹配结果（规则ID、匹配位置、匹配内容、置信度） | P0     |
| 规则模板库 | 预置三大领域常见违规模式规则模板（如"刚性兑付承诺"、"保本保收益"等） | P1     |
| 规则性能   | 单份文档规则扫描耗时 ≤ 30 秒                                 | P1     |

**关键需求**：规则引擎输出必须包含**原文定位信息**和**匹配的原文片段**，便于报告生成时溯源。

#### 3.2.3 LLM 语义分析模块 (LLM Semantic Analysis)

表格



| 功能点         | 需求描述                                                     | 优先级 |
| :------------- | :----------------------------------------------------------- | :----- |
| 语义审查       | 对文档进行语义级合规审查，识别模糊违规（如"风险披露不充分"、"适当性义务履行不到位"） | P0     |
| 上下文理解     | 理解文档整体语境，识别跨段落的语义违规（如前后文矛盾、披露不完整） | P0     |
| 法规召回 (RAG) | 基于 Milvus 向量库召回与文档内容语义相关的法规条款，作为 LLM 审查的上下文依据 | P0     |
| Prompt 工程    | 设计结构化 Prompt，要求 LLM 按指定格式输出审查结果（违规描述/位置/法规依据/修改建议） | P0     |
| 模型适配       | 支持对接主流 LLM API（OpenAI/Claude/国产大模型），支持模型切换与 fallback | P1     |
| 幻觉抑制       | 要求 LLM 输出必须引用具体法规条款，禁止无依据判断；设置置信度阈值过滤低质量输出 | P1     |

**关键需求**：LLM 审查必须基于**召回的法规条款上下文**（RAG），不能仅依赖模型内部知识，确保法规依据的准确性和时效性。

#### 3.2.4 混合审查与冲突解决模块 (Hybrid Review & Conflict Resolution)

表格



| 功能点       | 需求描述                                                     | 优先级 |
| :----------- | :----------------------------------------------------------- | :----- |
| 并行执行     | 规则引擎与 LLM 引擎对同一份文档并行审查                      | P0     |
| 结果融合     | 合并两份审查结果，去重（同一违规点被双引擎检出时合并）       | P0     |
| 冲突解决     | 当规则引擎与 LLM 结果冲突时，执行"规则优先"策略：规则引擎判定为违规则优先采信；LLM 单独检出的违规需标注"建议关注" | P0     |
| 置信度评分   | 对每条违规结果计算综合置信度（规则命中权重 + LLM 置信度权重） | P1     |
| 人工标注反馈 | 支持审查员对系统判定结果进行"确认违规/误报/漏报"标注，用于后续模型/规则优化 | P1     |

**冲突场景示例**：

- 规则引擎命中"保本保收益"关键词 → 直接判定违规（高置信度）；
- LLM 认为某段表述"暗示收益保障"但规则未命中 → 输出"疑似违规，建议关注"（中置信度）；
- 规则未命中且 LLM 认为合规 → 判定合规。

#### 3.2.5 法规知识库模块 (Regulatory Knowledge Base)

表格



| 功能点   | 需求描述                                                    | 优先级 |
| :------- | :---------------------------------------------------------- | :----- |
| 法规录入 | 支持法规文件批量导入、手动录入，自动解析章节条款结构        | P0     |
| 条款切分 | 将法规按"部→章→节→条→款→项"层级切分为最小语义单元（条款级） | P0     |
| 向量入库 | 条款文本向量化后存入 Milvus，支持语义检索                   | P0     |
| 法规更新 | 支持法规版本管理，新旧版本对比，自动标记废止/新增/修订条款  | P1     |
| 检索接口 | 提供关键词检索、语义检索、混合检索三种模式                  | P0     |
| 领域管理 | 按银行理财、基金销售、保险产品三大领域分类管理法规          | P0     |

**数据规模目标**：首期覆盖 150+ 部核心法规，条款级切分后预计 10,000+ 条款单元。

#### 3.2.6 知识图谱模块 (Knowledge Graph)

表格



| 功能点       | 需求描述                                                     | 优先级 |
| :----------- | :----------------------------------------------------------- | :----- |
| 图谱建模     | 构建"法规-条款-违规模式-处罚案例-产品类型"五元关联图谱       | P0     |
| 图谱查询     | 审查时自动关联：某违规点涉及哪些法规条款、历史上哪些类似案例被处罚 | P0     |
| 相似案例推荐 | 基于违规内容相似度，推荐历史处罚案例辅助风险评估             | P1     |
| 图谱可视化   | 提供图谱浏览界面，展示法规关联关系（前端可选）               | P2     |
| 图谱更新     | 支持增量更新，新法规/新案例自动融入现有图谱结构              | P1     |

**Neo4j 节点与关系设计**：

- 节点：`Regulation`（法规）、`Article`（条款）、`ViolationPattern`（违规模式）、`PenaltyCase`（处罚案例）、`ProductType`（产品类型）
- 关系：`HAS_ARTICLE`（法规包含条款）、`VIOLATES`（违反）、`SIMILAR_TO`（相似）、`APPLIES_TO`（适用于）、`PENALIZED_BY`（被处罚）

#### 3.2.7 Agent 编排模块 (Agent Orchestration)

基于 LangGraph 构建审查工作流，实现以下 Agent 节点：

表格



| Agent 节点            | 职责                     | 输入                    | 输出                        | 优先级 |
| :-------------------- | :----------------------- | :---------------------- | :-------------------------- | :----- |
| **DocClassifier**     | 识别文档领域与类型       | 原始文档内容            | 领域标签 + 文档类型         | P0     |
| **RegulationMatcher** | 从知识库召回相关法规条款 | 文档内容 + 领域标签     | Top-K 相关法规条款列表      | P0     |
| **RuleScanner**       | 执行规则引擎扫描         | 文档内容 + 规则库       | 规则命中结果列表            | P0     |
| **LLMScanner**        | 执行 LLM 语义审查        | 文档内容 + 召回法规条款 | LLM 审查结果列表            | P0     |
| **ConflictResolver**  | 融合双引擎结果，解决冲突 | 规则结果 + LLM 结果     | 融合后的违规列表            | P0     |
| **RiskAssessor**      | 评估每条违规的风险等级   | 融合违规列表 + 关联案例 | 带风险等级的违规列表        | P0     |
| **ReportGenerator**   | 生成结构化审查报告       | 带风险等级的违规列表    | 结构化 JSON / Markdown 报告 | P0     |

**工作流状态图**：

plain

```plain
[Start] → DocClassifier → RegulationMatcher → [Parallel] → RuleScanner → [Join] → ConflictResolver → RiskAssessor → ReportGenerator → [End]
                                      └→ LLMScanner ──┘
```

**关键需求**：

- 每个 Agent 节点需记录执行日志（输入/输出/耗时/异常）；
- 支持节点级重试与错误降级（如 LLM 超时则仅输出规则引擎结果）；
- 支持人工干预节点（审查员可中途修改召回法规或调整规则）。

#### 3.2.8 报告生成模块 (Report Generation)

审查报告必须包含以下五部分结构化内容：

表格



| 报告章节         | 内容要求                                                     | 优先级 |
| :--------------- | :----------------------------------------------------------- | :----- |
| **违规条款定位** | 违规内容原文摘录 + 精确位置（页码/段落编号）+ 高亮标记       | P0     |
| **风险等级**     | 高/中/低三级，评估依据（如：涉及禁止性规定/限制性规定/披露不充分） | P0     |
| **法规依据**     | 引用的具体法规名称、条款编号、条款原文                       | P0     |
| **修改建议**     | 针对该违规点的具体修改文案建议（LLM 生成）                   | P0     |
| **关联处罚案例** | 知识图谱中关联的历史相似处罚案例摘要（案例名称、处罚机构、处罚结果） | P1     |

**报告格式**：支持 Markdown、PDF、Word 导出；支持在线查看与批注。

#### 3.2.9 系统管理模块 (System Management)

表格



| 功能点   | 需求描述                                                     | 优先级 |
| :------- | :----------------------------------------------------------- | :----- |
| 用户权限 | RBAC 权限模型：管理员/审查员/访客三种角色                    | P1     |
| 任务管理 | 审查任务列表、状态跟踪（待处理/处理中/已完成/失败）、批量操作 | P0     |
| 审计日志 | 记录所有用户操作与系统审查行为，满足金融审计要求             | P1     |
| 监控告警 | 系统性能监控（API 响应时间/队列堆积/错误率）、异常告警       | P1     |
| 配置管理 | LLM 参数配置（温度/top-p/模型选择）、规则引擎阈值配置        | P1     |

------

## 4. 非功能需求

### 4.1 性能需求

- **并发能力**：支持至少 10 个审查任务并行处理；
- **响应时间**：单份 50 页以内文档，端到端审查（不含人工复核）≤ 5 分钟；
- **规则扫描**：单份文档 ≤ 30 秒；
- **LLM 审查**：单份文档 ≤ 3 分钟（含向量检索）；
- **向量检索**：Top-K 召回 ≤ 500ms；
- **图查询**：关联案例查询 ≤ 1s。

### 4.2 安全需求

- **数据隔离**：不同租户/部门的产品文档与审查结果逻辑隔离；
- **敏感信息保护**：产品文档中涉及的客户信息、商业机密需脱敏处理；
- **访问控制**：所有 API 需认证授权，审计日志不可篡改；
- **传输加密**：HTTPS/TLS 加密传输；
- **存储加密**：敏感数据（如法规原文、审查报告）加密存储。

### 4.3 可用性需求

- **系统可用性**：≥ 99.5%（计划内维护除外）；
- **故障降级**：LLM 服务不可用时，系统可降级为纯规则引擎模式继续运行；
- **数据备份**：MySQL/Neo4j/Milvus 定期备份，支持灾难恢复。

### 4.4 扩展性需求

- **法规扩展**：支持快速新增领域（如信托、证券）；
- **模型扩展**：支持无缝切换不同 LLM 提供商；
- **规则扩展**：规则库支持热更新，无需重启服务；
- **部署扩展**：支持 Docker Compose 单机部署 → K8s 集群部署的平滑过渡。

------

## 5. 技术实现方案

### 5.1 系统架构

采用**分层微服务架构**，核心服务通过 Docker 容器化部署：

plain

```plain
┌─────────────────────────────────────────────────────────────┐
│                      API Gateway (Nginx)                     │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────┐    ┌──────────────────┐    ┌──────────────┐
│  Web Frontend │    │  FastAPI App     │    │  Admin Panel │
│  (React/Vue)  │    │  (主应用服务)     │    │  (内部管理)  │
└──────────────┘    └──────────────────┘    └──────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌─────────────┐    ┌─────────────────┐    ┌─────────────┐
│  Task Queue │    │  LangGraph      │    │  Rule Engine │
│  (Celery +  │    │  Agent Workflow │    │  Service     │
│   Redis)    │    │                 │    │              │
└─────────────┘    └─────────────────┘    └─────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌─────────────┐    ┌─────────────────┐    ┌─────────────┐
│   Milvus    │    │     Neo4j       │    │   MySQL     │
│  (向量检索)  │    │   (知识图谱)     │    │  (关系数据)  │
└─────────────┘    └─────────────────┘    └─────────────┘
        ▼
┌─────────────────────────────────────────────────────────────┐
│              LLM Provider (OpenAI / Claude / 文心等)         │
│              (通过统一适配层调用，支持模型切换)               │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 技术选型与理由

表格



| 组件           | 选型                             | 理由                                                         |
| :------------- | :------------------------------- | :----------------------------------------------------------- |
| **Web 框架**   | FastAPI                          | 异步高性能、自动 API 文档、Python 生态成熟                   |
| **Agent 框架** | LangGraph                        | 支持复杂状态机工作流、可视化调试、与 LangChain 生态兼容      |
| **规则引擎**   | 自研（基于 Python）              | 金融领域规则高度定制化，Drools 等通用引擎适配成本高；自研更灵活 |
| **向量数据库** | Milvus                           | 开源、高性能、支持混合检索、与 Python SDK 集成友好           |
| **图数据库**   | Neo4j                            | 业界标准图数据库、Cypher 查询直观、图谱可视化工具成熟        |
| **关系数据库** | MySQL 8.0                        | 事务支持好、运维成本低、适合存储结构化业务数据               |
| **缓存/队列**  | Redis                            | 任务队列（Celery backend）、缓存热点数据、会话存储           |
| **文档解析**   | PyPDF2 / python-docx / PaddleOCR | 覆盖 PDF/Word/图片三种格式                                   |
| **向量模型**   | BGE / M3E（中文）                | 中文语义理解效果好，开源可本地部署                           |
| **LLM**        | GPT-4 / Claude 3 / 国产大模型    | 通过适配层统一调用，根据场景选择                             |
| **部署**       | Docker + Docker Compose          | 开发测试环境快速搭建，后续可迁移至 K8s                       |
| **任务队列**   | Celery + Redis                   | 异步处理文档解析、LLM 调用等耗时操作                         |

### 5.3 数据模型设计

#### 5.3.1 MySQL 核心表结构

sql

```sql
-- 用户与权限
users (id, username, role, department, created_at)
roles (id, name, permissions)

-- 审查任务
review_tasks (
    id, 
    task_name, 
    document_name, 
    document_path,
    document_type,      -- 说明书/协议/宣传材料
    domain,             -- 银行理财/基金/保险
    status,             -- pending/processing/completed/failed
    created_by,
    created_at,
    completed_at,
    report_path
)

-- 审查结果
review_results (
    id,
    task_id,
    violation_type,     -- rule / llm / hybrid
    risk_level,         -- high/medium/low
    original_text,      -- 违规原文
    location_page,      -- 页码
    location_paragraph, -- 段落号
    regulation_id,      -- 关联法规
    article_id,         -- 关联条款
    rule_id,            -- 关联规则（如有）
    confidence_score,   -- 置信度
    suggestion,         -- 修改建议
    status,             -- pending/confirmed/false_positive
    created_at
)

-- 法规库
regulations (
    id,
    domain,
    regulation_name,
    regulation_no,      -- 文号
    issuer,             -- 发布机构
    publish_date,
    effective_date,
    status              -- effective/amended/repealed
)

-- 法规条款
articles (
    id,
    regulation_id,
    chapter_no,
    section_no,
    article_no,
    clause_no,
    item_no,
    content,
    vector_id           -- Milvus 中的向量 ID
)

-- 规则库
rules (
    id,
    domain,
    rule_name,
    rule_type,          -- regex/keyword/condition/composite
    rule_content,       -- 规则定义（JSON）
    severity,           -- high/medium/low
    description,
    is_active,
    version,
    created_at,
    updated_at
)

-- 处罚案例
penalty_cases (
    id,
    case_name,
    penalty_org,        -- 处罚机构
    penalty_date,
    penalty_result,
    violation_summary,
    related_regulations -- JSON 数组
)
```

#### 5.3.2 Milvus 集合设计

Python

```python
# Collection: legal_articles
fields = [
    FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
    FieldSchema(name="article_id", dtype=DataType.INT64),      # 关联 MySQL articles.id
    FieldSchema(name="regulation_id", dtype=DataType.INT64),   # 关联 MySQL regulations.id
    FieldSchema(name="domain", dtype=DataType.VARCHAR, max_length=50),
    FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=4096),
    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=768)
]

# Index: IVF_FLAT 或 HNSW，度量方式 COSINE
```

#### 5.3.3 Neo4j 图模型

cypher

```cypher
// 节点标签
(:Regulation {id, name, domain, publish_date, status})
(:Article {id, regulation_id, chapter_no, article_no, content})
(:ViolationPattern {id, pattern_name, description, domain, severity})
(:PenaltyCase {id, case_name, penalty_org, penalty_date, summary})
(:ProductType {id, type_name, domain})

// 关系类型
(:Regulation)-[:HAS_ARTICLE]->(:Article)
(:Article)-[:VIOLATES {confidence}]->(:ViolationPattern)
(:ViolationPattern)-[:APPLIES_TO]->(:ProductType)
(:PenaltyCase)-[:INVOLVES_VIOLATION]->(:ViolationPattern)
(:PenaltyCase)-[:BASED_ON_REGULATION]->(:Regulation)
(:Article)-[:SIMILAR_TO {similarity_score}]->(:Article)
```

### 5.4 核心流程详细设计

#### 5.4.1 混合审查流程

plain

```plain
1. 文档上传
   └→ 解析服务提取文本与结构
   └→ 存入临时存储，生成 task_id

2. 触发审查工作流 (LangGraph)
   └→ Node 1: DocClassifier
       └→ 输入：文档标题 + 前 1000 字 + 目录结构
       └→ 输出：domain (banking/fund/insurance), doc_type
       └→ 失败降级：默认 domain = "unknown"，人工选择后继续
   
   └→ Node 2: RegulationMatcher
       └→ 输入：文档全文（切分为 chunks）
       └→ 处理：每个 chunk 向量化 → Milvus 混合检索（语义+关键词）→ Top-5 法规条款/ chunk
       └→ 输出：相关法规条款列表（去重后约 30-50 条）
       └→ 优化：按领域过滤，优先召回生效中的法规
   
   └→ Node 3: Parallel Scanning
       ├→ Branch A: RuleScanner
       │   └→ 输入：文档全文 + 该领域全部 active 规则
       │   └→ 处理：逐条规则匹配，输出命中结果
       │   └→ 输出：[{rule_id, matched_text, location, severity}]
       │
       └→ Branch B: LLMScanner
           └→ 输入：文档 chunks + 召回的法规条款（作为上下文）
           └→ 处理：每 chunk 调用 LLM 审查 Prompt
           └→ 输出：[{violation_desc, location, regulation_ref, confidence, suggestion}]
   
   └→ Node 4: ConflictResolver
       └→ 输入：RuleScanner 结果 + LLMScanner 结果
       └→ 处理：
           ├→ 同一位置双引擎均命中 → 合并，置信度 = max(rule_conf, llm_conf)
           ├→ 仅规则命中 → 直接采信，标记 "rule_confirmed"
           ├→ 仅 LLM 命中 → 采信但标记 "llm_suggested"，置信度下调 20%
           └→ 规则认为合规但 LLM 认为违规 → 输出 "llm_suggested"，人工复核
       └→ 输出：融合后的违规列表
   
   └→ Node 5: RiskAssessor
       └→ 输入：融合违规列表
       └→ 处理：
           ├→ 查询 Neo4j：该违规模式的历史处罚案例数量与严重程度
           ├→ 查询规则/LLM 的 severity 等级
           └→ 综合评分：高（禁止性违规/有重罚案例）/ 中（限制性违规/有轻罚案例）/ 低（披露不充分/无案例）
       └→ 输出：带风险等级的违规列表
   
   └→ Node 6: ReportGenerator
       └→ 输入：带风险等级的违规列表 + 关联案例
       └→ 处理：按报告模板组装结构化数据
       └→ 输出：JSON 格式报告 → 渲染为 Markdown/PDF

3. 人工复核
   └→ 审查员在界面查看报告，确认/驳回/补充违规点
   └→ 确认后的结果反馈至系统，用于优化规则/模型
```

#### 5.4.2 Prompt 设计（LLM 审查）

Python

```python
COMPLIANCE_REVIEW_PROMPT = """
你是一名资深金融合规审查专家，擅长审查{domain}领域的{doc_type}文档。

## 任务
请审查以下文档片段是否存在合规违规问题。

## 参考法规条款（已召回相关条款）
{retrieved_articles}

## 审查要求
1. 仅基于上述法规条款进行判断，不得依赖模型内部知识
2. 重点关注以下违规类型：
   - 禁止性违规：承诺保本保收益、刚性兑付、虚假宣传等
   - 限制性违规：超出许可范围销售、不当承诺等
   - 披露性违规：风险披露不充分、重要信息遗漏、表述模糊等
3. 对每条发现的违规，按以下格式输出：
   - violation: 违规描述
   - location: 违规在文档中的位置描述
   - regulation: 引用的法规名称及条款编号
   - severity: high/medium/low
   - confidence: 0-1 的置信度
   - suggestion: 具体的修改建议

## 输出格式
请以 JSON 数组格式输出，无违规时返回空数组 []。

## 文档片段
{document_chunk}
"""
```

#### 5.4.3 规则引擎设计

规则定义 DSL（JSON 格式）：

JSON

```json
{
  "rule_id": "RULE-BANK-001",
  "rule_name": "禁止刚性兑付承诺",
  "domain": "banking",
  "rule_type": "composite",
  "severity": "high",
  "definition": {
    "operator": "OR",
    "conditions": [
      {
        "type": "regex",
        "pattern": "保本保息|保本保收益|刚性兑付|承诺.*收益.*[0-9]+%"
      },
      {
        "type": "keyword",
        "keywords": ["保本", "保息", "保收益", "刚性兑付"],
        "match_mode": "any",
        "context_window": 20
      }
    ]
  },
  "description": "理财产品不得承诺保本保收益",
  "related_regulations": ["《商业银行理财业务监督管理办法》第26条"]
}
```

规则引擎执行逻辑：

1. 按领域过滤 active 规则；
2. 对每条规则，在文档中执行匹配；
3. 记录匹配位置、原文片段、规则 ID；
4. 输出结构化命中结果。

### 5.5 接口设计（核心 API）

表格



| 接口         | 方法 | 路径                                  | 说明                       |
| :----------- | :--- | :------------------------------------ | :------------------------- |
| 上传文档     | POST | `/api/v1/documents/upload`            | 上传产品文档，返回 task_id |
| 创建审查任务 | POST | `/api/v1/tasks`                       | 基于上传文档创建审查任务   |
| 查询任务状态 | GET  | `/api/v1/tasks/{task_id}`             | 获取任务状态与进度         |
| 获取审查报告 | GET  | `/api/v1/tasks/{task_id}/report`      | 获取结构化审查报告         |
| 确认审查结果 | POST | `/api/v1/results/{result_id}/confirm` | 人工确认违规/误报          |
| 法规检索     | GET  | `/api/v1/regulations/search`          | 关键词/语义检索法规        |
| 规则管理     | CRUD | `/api/v1/rules/*`                     | 规则的增删改查             |
| 法规管理     | CRUD | `/api/v1/regulations/*`               | 法规的增删改查             |
| 知识图谱查询 | POST | `/api/v1/graph/query`                 | Cypher 查询或预置查询      |

## 6. 项目文件目录结构

plain

```plain
financial-compliance-review/
├── docker/
│   ├── docker-compose.yml          # 全栈一键启动
│   ├── Dockerfile.api              # FastAPI 服务镜像
│   ├── Dockerfile.worker           # Celery Worker 镜像
│   └── init-scripts/             # 数据库初始化脚本
│       ├── init_mysql.sql
│       ├── init_neo4j.cypher
│       └── init_milvus.py
│
├── docs/
│   ├── PRD.md                      # 产品需求文档（本文档）
│   ├── API_SPEC.md                 # 接口规范
│   ├── RULE_DSL.md               # 规则引擎 DSL 规范
│   └── DEPLOYMENT.md             # 部署文档
│
├── src/
│   ├── api/                        # FastAPI 应用层
│   │   ├── __init__.py
│   │   ├── main.py                 # 应用入口
│   │   ├── routers/
│   │   │   ├── documents.py        # 文档上传/管理
│   │   │   ├── tasks.py            # 审查任务管理
│   │   │   ├── reports.py          # 报告查看/导出
│   │   │   ├── regulations.py      # 法规库管理
│   │   │   ├── rules.py            # 规则引擎管理
│   │   │   ├── graph.py            # 知识图谱查询
│   │   │   └── admin.py            # 系统管理
│   │   ├── middleware/
│   │   │   ├── auth.py             # JWT 认证
│   │   │   ├── audit.py            # 审计日志
│   │   │   └── exception.py        # 全局异常处理
│   │   └── schemas/                # Pydantic 数据模型
│   │       ├── document.py
│   │       ├── task.py
│   │       ├── report.py
│   │       ├── regulation.py
│   │       └── rule.py
│   │
│   ├── core/                       # 核心引擎层
│   │   ├── __init__.py
│   │   ├── agents/                 # LangGraph Agent 编排
│   │   │   ├── __init__.py
│   │   │   ├── workflow.py         # 审查工作流定义
│   │   │   ├── nodes/
│   │   │   │   ├── classifier.py   # 文档分类 Agent
│   │   │   │   ├── matcher.py      # 法规匹配 Agent
│   │   │   │   ├── rule_scanner.py # 规则扫描 Agent
│   │   │   │   ├── llm_scanner.py  # LLM 审查 Agent
│   │   │   │   ├── resolver.py     # 冲突解决 Agent
│   │   │   │   ├── assessor.py     # 风险评估 Agent
│   │   │   │   └── reporter.py     # 报告生成 Agent
│   │   │   └── edges/
│   │   │       └── transitions.py  # 状态转移逻辑
│   │   │
│   │   ├── rule_engine/            # 规则引擎
│   │   │   ├── __init__.py
│   │   │   ├── engine.py           # 引擎主类
│   │   │   ├── parser.py           # 规则解析器
│   │   │   ├── matchers/
│   │   │   │   ├── regex_matcher.py
│   │   │   │   ├── keyword_matcher.py
│   │   │   │   └── composite_matcher.py
│   │   │   └── models.py           # 规则数据模型
│   │   │
│   │   ├── llm/                    # LLM 适配层
│   │   │   ├── __init__.py
│   │   │   ├── client.py           # 统一 LLM 调用客户端
│   │   │   ├── providers/          # 各厂商适配器
│   │   │   │   ├── openai.py
│   │   │   │   ├── claude.py
│   │   │   │   └── qwen.py
│   │   │   ├── prompts/            # Prompt 模板
│   │   │   │   ├── review.py
│   │   │   │   ├── classify.py
│   │   │   │   └── suggestion.py
│   │   │   └── models.py
│   │   │
│   │   └── report/                 # 报告生成
│   │       ├── __init__.py
│   │       ├── generator.py        # 报告生成器
│   │       └── templates/          # 报告模板
│   │           ├── markdown.j2
│   │           └── pdf.css
│   │
│   ├── services/                   # 业务服务层
│   │   ├── __init__.py
│   │   ├── document_service.py     # 文档解析服务
│   │   ├── task_service.py         # 任务编排服务
│   │   ├── regulation_service.py   # 法规库服务
│   │   ├── rule_service.py         # 规则管理服务
│   │   ├── graph_service.py        # 知识图谱服务
│   │   └── report_service.py       # 报告服务
│   │
│   ├── infrastructure/             # 基础设施层
│   │   ├── __init__.py
│   │   ├── database/
│   │   │   ├── mysql.py            # MySQL 连接池
│   │   │   ├── neo4j_client.py     # Neo4j 客户端
│   │   │   ├── milvus_client.py    # Milvus 客户端
│   │   │   └── redis_client.py     # Redis 客户端
│   │   ├── storage/
│   │   │   └── file_storage.py     # 文档文件存储（本地/S3）
│   │   ├── queue/
│   │   │   └── celery_app.py       # Celery 配置
│   │   └── embedding/
│   │       └── embedding_model.py  # 向量模型封装
│   │
│   ├── models/                     # ORM 模型
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── task.py
│   │   ├── result.py
│   │   ├── regulation.py
│   │   ├── article.py
│   │   ├── rule.py
│   │   └── penalty_case.py
│   │
│   ├── parsers/                    # 文档解析器
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── pdf_parser.py
│   │   ├── docx_parser.py
│   │   └── ocr_parser.py
│   │
│   └── utils/                      # 工具类
│       ├── __init__.py
│       ├── logger.py
│       ├── config.py               # 配置管理（Pydantic Settings）
│       ├── security.py             # 加密/脱敏
│       └── validators.py
│
├── scripts/                        # 运维脚本
│   ├── init_data/                  # 初始化数据
│   │   ├── regulations/            # 法规原始数据
│   │   ├── penalty_cases/          # 处罚案例数据
│   │   └── import_regulations.py   # 数据导入脚本
│   ├── migrate/                    # 数据库迁移
│   └── backup/                     # 备份脚本
│
├── tests/                          # 测试
│   ├── unit/                       # 单元测试
│   ├── integration/                # 集成测试
│   └── fixtures/                   # 测试数据
│
├── configs/                        # 配置文件
│   ├── app.yaml                    # 应用配置
│   ├── rules/                      # 规则模板
│   │   ├── banking_rules.json
│   │   ├── fund_rules.json
│   │   └── insurance_rules.json
│   └── prompts/                    # Prompt 配置
│       └── review_prompts.yaml
│
├── .env.example                    # 环境变量模板
├── requirements.txt                # Python 依赖
├── pyproject.toml                  # 现代 Python 项目配置
└── README.md
```

------

## 7. 开发风险与应对策略

表格



| 风险类别     | 具体风险                                        | 影响等级 | 应对策略                                                     |
| :----------- | :---------------------------------------------- | :------- | :----------------------------------------------------------- |
| **数据风险** | 法规数据获取困难，150+ 部法规结构化处理工作量大 | 高       | 1. 优先聚焦 30 部核心高频法规（覆盖 80% 审查场景）；2. 与合规团队合作，采用半自动化+人工校验方式处理；3. 设计法规批量导入工具降低录入成本 |
| **数据风险** | 法规频繁更新，知识库时效性难以保障              | 中       | 1. 建立法规版本管理机制；2. 设置法规更新提醒与自动 diff 比对；3. 定期（季度）review 法规库 |
| **模型风险** | LLM 幻觉导致法规依据错误或虚构条款              | 高       | 1. 强制 RAG：LLM 必须基于召回的法规条款作答；2. 输出格式强制引用法规名称+条款编号；3. 人工复核环节作为最终把关；4. 建立 LLM 输出校验层 |
| **模型风险** | LLM API 不稳定或响应超时                        | 中       | 1. 多模型 fallback 机制；2. 超时降级为纯规则引擎模式；3. Celery 异步队列 + 重试机制；4. 本地部署小模型作为应急备份 |
| **技术风险** | 规则引擎维护成本高，规则膨胀后性能下降          | 中       | 1. 规则分层设计（基础规则/领域规则/机构自定义规则）；2. 规则预编译与索引优化；3. 定期清理无效规则；4. 规则命中统计，优先执行高频规则 |
| **技术风险** | 向量检索召回不准，导致 LLM 上下文缺失           | 中       | 1. 混合检索（向量+关键词+BM25）；2. 多路召回（标题召回+内容召回+摘要召回）；3. 召回结果重排序（Rerank）；4. 人工标注 badcase 持续优化 |
| **技术风险** | Neo4j 知识图谱建模不当，查询性能差              | 中       | 1. 前期充分调研图谱 schema；2. 控制单节点关系数量；3. 建立合适的索引；4. 复杂查询预计算 |
| **业务风险** | 合规团队对系统信任度不足，推广困难              | 高       | 1. 设计"人机协同"模式，系统辅助而非替代人工；2. 提供充分的解释性（违规依据可追溯）；3. 从简单场景切入，逐步建立信任；4. 定期输出系统准确率报告 |
| **安全风险** | 产品文档包含敏感信息，存在泄露风险              | 高       | 1. 数据脱敏处理（客户信息/金额等）；2. 传输与存储加密；3. 严格的访问控制与审计；4. 敏感操作留痕；5. 本地部署优先，LLM 调用走专线 |
| **性能风险** | 大文档（100+ 页）处理超时                       | 中       | 1. 文档切分并行处理；2. LLM 流式输出；3. 异步任务模式，用户可轮询进度；4. 优化向量检索 batch size |

------

## 8. 迭代开发计划

### Phase 1：MVP 验证期（第 1-4 周）

**目标**：验证核心流程可行性，跑通端到端审查链路

表格



| 周次 | 任务                                                | 交付物                            |
| :--- | :-------------------------------------------------- | :-------------------------------- |
| W1   | 项目脚手架搭建、Docker 环境配置、数据库初始化       | 可运行的基础服务                  |
| W2   | 文档解析模块 + 法规知识库（导入 10 部核心法规）     | 支持 PDF/Word 解析，法规可检索    |
| W3   | 规则引擎 V1（20 条基础规则）+ LLM 适配层 + RAG 检索 | 双引擎可独立运行                  |
| W4   | 简单串行工作流 + 报告生成（Markdown）+ 基础 API     | **MVP Demo**：上传文档 → 输出报告 |

**验收标准**：

- 可完成单领域（如银行理财）简单文档的端到端审查；
- 规则引擎与 LLM 可并行输出结果；
- 报告包含违规定位、法规依据、修改建议三部分。

------

### Phase 2：核心引擎建设期（第 5-8 周）

**目标**：完善规则引擎与 LLM 审查质量，构建冲突解决机制

表格



| 周次 | 任务                                            | 交付物             |
| :--- | :---------------------------------------------- | :----------------- |
| W5   | 规则引擎完善：支持复合规则、规则模板库（50 条） | 规则引擎 V2        |
| W6   | LLM Prompt 优化 + RAG 混合检索优化 + 幻觉抑制   | LLM 审查准确率提升 |
| W7   | 混合审查融合逻辑 + 冲突解决策略实现             | 混合审查模块       |
| W8   | 风险评估初版 + 报告模板完善（PDF 导出）         | 结构化报告 V2      |

**验收标准**：

- 规则库覆盖 50+ 条明确违规模式；
- 混合审查模式下违规召回率 ≥ 85%；
- 冲突解决策略可正确处理规则与 LLM 的结果冲突。

------

### Phase 3：知识图谱与知识库建设期（第 9-12 周）

**目标**：构建知识图谱，扩展法规覆盖范围

表格



| 周次 | 任务                                     | 交付物         |
| :--- | :--------------------------------------- | :------------- |
| W9   | Neo4j 图谱 Schema 设计与基础数据导入     | 知识图谱 V1    |
| W10  | 图谱关联查询 + 相似案例推荐功能          | 案例推荐模块   |
| W11  | 法规库扩展至 150+ 部，条款级切分与向量化 | 完整法规知识库 |
| W12  | 知识库管理后台（法规 CRUD、规则 CRUD）   | 管理后台 V1    |

**验收标准**：

- 覆盖三大领域 150+ 部法规；
- 知识图谱支持违规点关联历史案例；
- 管理后台可维护法规与规则。

------

### Phase 4：Agent 编排与系统完善期（第 13-16 周）

**目标**：LangGraph 工作流成熟，系统可投产使用

表格



| 周次 | 任务                                        | 交付物        |
| :--- | :------------------------------------------ | :------------ |
| W13  | LangGraph 完整工作流实现（6 个 Agent 节点） | Agent 编排 V1 |
| W14  | 任务队列（Celery）+ 异步处理 + 状态追踪     | 异步任务系统  |
| W15  | 用户权限 + 审计日志 + 安全加固              | 安全合规模块  |
| W16  | 系统监控 + 性能优化 + 压力测试              | 生产就绪版本  |

**验收标准**：

- 完整的 Agent 工作流可自动执行；
- 支持 10+ 并发审查任务；
- 单份文档端到端处理 ≤ 5 分钟；
- 系统可用性 ≥ 99.5%。

------

### Phase 5：优化与推广期（第 17-20 周）

**目标**：提升准确率，降低误报，推广至更多场景

表格



| 周次 | 任务                                     | 交付物       |
| :--- | :--------------------------------------- | :----------- |
| W17  | 人工反馈闭环：审查员标注 → 规则/模型优化 | 反馈优化机制 |
| W18  | 误报分析 + Prompt 迭代 + 规则精调        | 准确率提升   |
| W19  | 多领域扩展（信托、证券）可行性验证       | 扩展方案     |
| W20  | 完整文档 + 培训材料 + 上线支持           | 正式上线     |

**验收标准**：

- 违规条款召回率 ≥ 91%；
- 误报率较纯 LLM 方案显著降低；
- 单份文档审查时间（含人工复核）≤ 15 分钟；
- 用户满意度 ≥ 80%。

------

## 9. 关键指标 (KPI)

表格



| 指标           | 目标值    | 测量方式                                        |
| :------------- | :-------- | :---------------------------------------------- |
| 违规条款召回率 | ≥ 91%     | 人工抽检 100 份历史文档，对比系统检出与人工检出 |
| 误报率         | ≤ 15%     | 系统判定违规中经人工确认为误报的比例            |
| 端到端处理时间 | ≤ 5 分钟  | 系统处理耗时（不含人工复核）                    |
| 人工复核时间   | ≤ 10 分钟 | 审查员确认系统报告的平均耗时                    |
| 法规覆盖率     | 150+ 部   | 系统收录的法规数量                              |
| 系统可用性     | ≥ 99.5%   | 月度统计                                        |
| 用户满意度     | ≥ 80%     | 季度问卷调研                                    |

------

## 10. 附录

### 10.1 术语表

表格



| 术语        | 说明                                                         |
| :---------- | :----------------------------------------------------------- |
| Agentic RAG | 基于 Agent 架构的检索增强生成，Agent 可自主决定检索时机与方式 |
| LangGraph   | LangChain 生态中的图结构工作流框架，支持循环与条件分支       |
| 条款级切分  | 将法规按"条-款-项"层级拆分为最小语义单元                     |
| 刚性兑付    | 金融机构违反资管新规，承诺保本保收益的行为                   |

### 10.2 参考法规清单（首期核心）

- 《关于规范金融机构资产管理业务的指导意见》（资管新规）
- 《商业银行理财业务监督管理办法》
- 《公开募集证券投资基金销售机构监督管理办法》
- 《保险销售行为管理办法》
- 《证券期货投资者适当性管理办法》

------

> **文档状态**：初稿
> **编写日期**：2026-08-04
> **下次评审**：完成技术方案细化后

------

以上就是完整的 PRD。文档中所有模块、流程、数据模型和迭代计划均已对齐你简历中提到的技术栈与业务场景。建议你先组织一次内部评审，确认以下关键问题后再进入编码：

1. **法规数据来源**：150+ 部法规是否有现成的结构化数据，还是需要从头整理？
2. **LLM 选型**：使用云端 API 还是本地部署？这直接影响架构中的 `llm/providers` 实现和成本估算。
3. **规则引擎边界**：明确哪些违规模式走规则（如关键词类），哪些走 LLM（如语义模糊类），避免两者重叠导致维护混乱。

## 补充章节

### 11. API 接口详细规范

#### 11.1 上传文档

http

```http
POST /api/v1/documents/upload
Content-Type: multipart/form-data

Request:
  file: <binary>          # 支持 pdf, docx, doc, txt
  product_name: string    # 产品名称
  product_code: string    # 产品编码（可选）

Response: 201 Created
{
  "code": 0,
  "data": {
    "document_id": "doc_2v8x9k3m",
    "file_name": "XX银行理财计划说明书.pdf",
    "file_size": 2048576,
    "status": "uploaded",
    "upload_time": "2026-08-04T21:10:00+08:00"
  }
}
```

#### 11.2 创建审查任务

http

```http
POST /api/v1/tasks
Content-Type: application/json

Request:
{
  "document_id": "doc_2v8x9k3m",
  "priority": "normal",        // normal | high | urgent
  "review_depth": "standard",  // quick | standard | deep
  "callback_url": "https://your-system.com/webhook"  // 可选
}

Response: 201 Created
{
  "code": 0,
  "data": {
    "task_id": "task_9a5b2c1d",
    "status": "pending",
    "estimated_time": 180,     // 预计秒数
    "created_at": "2026-08-04T21:10:30+08:00"
  }
}
```

#### 11.3 查询任务状态（支持 SSE 长轮询）

http

```http
GET /api/v1/tasks/{task_id}

Response: 200 OK
{
  "code": 0,
  "data": {
    "task_id": "task_9a5b2c1d",
    "status": "processing",    // pending | processing | completed | failed | cancelled
    "progress": 65,            // 0-100
    "current_stage": "llm_scanning",  // 当前 Agent 节点
    "stages": {
      "doc_classifier": {"status": "completed", "cost_ms": 1200},
      "regulation_matcher": {"status": "completed", "cost_ms": 3500},
      "rule_scanner": {"status": "completed", "cost_ms": 8000},
      "llm_scanner": {"status": "processing", "cost_ms": 45000},
      "conflict_resolver": {"status": "pending"},
      "risk_assessor": {"status": "pending"},
      "report_generator": {"status": "pending"}
    },
    "created_at": "2026-08-04T21:10:30+08:00",
    "started_at": "2026-08-04T21:10:35+08:00",
    "estimated_completion": "2026-08-04T21:13:45+08:00"
  }
}
```

#### 11.4 获取审查报告

http

```http
GET /api/v1/tasks/{task_id}/report?format=markdown

Response: 200 OK
{
  "code": 0,
  "data": {
    "task_id": "task_9a5b2c1d",
    "report_version": "1.0",
    "generated_at": "2026-08-04T21:13:40+08:00",
    "summary": {
      "total_violations": 8,
      "high_risk": 2,
      "medium_risk": 3,
      "low_risk": 3,
      "rule_detected": 5,
      "llm_detected": 3,
      "hybrid_detected": 2
    },
    "violations": [
      {
        "violation_id": "vio_001",
        "type": "hybrid",              // rule | llm | hybrid
        "risk_level": "high",
        "confidence": 0.95,
        "location": {
          "page": 3,
          "paragraph": 12,
          "original_text": "本产品承诺年化收益率不低于 4.5%，保本保息..."
        },
        "regulation_refs": [
          {
            "regulation_name": "商业银行理财业务监督管理办法",
            "article_no": "第二十六条",
            "article_content": "商业银行销售理财产品，不得宣传或承诺保本保收益..."
          }
        ],
        "rule_ref": {
          "rule_id": "RULE-BANK-001",
          "rule_name": "禁止刚性兑付承诺"
        },
        "description": "文档中存在承诺保本保收益的表述，违反资管新规关于打破刚性兑付的要求",
        "suggestion": "建议修改为：'本产品为净值型理财产品，不保证本金和收益，产品净值随市场波动，投资者可能面临本金损失风险。过往业绩不代表未来表现。'",
        "related_cases": [
          {
            "case_name": "某银行违规承诺保本案",
            "penalty_org": "银保监会",
            "penalty_date": "2025-03-15",
            "penalty_result": "罚款 50 万元，责令整改",
            "similarity": 0.88
          }
        ],
        "status": "pending_confirm"     // pending_confirm | confirmed | false_positive
      }
    ],
    "report_download_url": "/api/v1/tasks/task_9a5b2c1d/report/download?format=pdf"
  }
}
```

#### 11.5 人工确认审查结果

http

```http
POST /api/v1/violations/{violation_id}/feedback
Content-Type: application/json

Request:
{
  "action": "confirm",        // confirm | false_positive | modify
  "comment": "确认违规，已通知产品部门修改",
  "modified_suggestion": ""   // action=modify 时填写
}

Response: 200 OK
{
  "code": 0,
  "message": "反馈已记录，将用于优化审查模型"
}
```

#### 11.6 法规语义检索

http

```http
POST /api/v1/regulations/search
Content-Type: application/json

Request:
{
  "query": "理财产品能否承诺保本保收益",
  "search_type": "hybrid",     // keyword | semantic | hybrid
  "domain": ["banking"],       // 可选过滤
  "top_k": 10
}

Response: 200 OK
{
  "code": 0,
  "data": {
    "total": 23,
    "results": [
      {
        "article_id": 1523,
        "regulation_name": "商业银行理财业务监督管理办法",
        "article_no": "第二十六条",
        "content": "商业银行销售理财产品，不得宣传或承诺保本保收益...",
        "score": 0.92,
        "highlight": "不得宣传或<em>承诺保本保收益</em>"
      }
    ]
  }
}
```

------

### 12. 统一响应规范与错误码

JSON

```json
{
  "code": 0,           // 0=成功，非0=错误
  "message": "success",
  "data": {},
  "trace_id": "req_7f3a9b2c"   // 用于日志追踪
}
```

表格



| 错误码 | 含义             | 场景                       |
| :----- | :--------------- | :------------------------- |
| 0      | 成功             | -                          |
| 1001   | 参数错误         | 必填字段缺失、格式非法     |
| 1002   | 文件格式不支持   | 上传了非 pdf/docx/txt 文件 |
| 1003   | 文件过大         | 单文件超过 50MB 限制       |
| 2001   | 任务不存在       | task_id 无效               |
| 2002   | 任务状态非法     | 对已完成任务执行取消       |
| 3001   | 法规检索失败     | Milvus 连接异常            |
| 3002   | 知识图谱查询失败 | Neo4j 连接异常             |
| 4001   | LLM 调用失败     | API 超时或限流             |
| 4002   | LLM 输出格式错误 | 返回非预期 JSON            |
| 5001   | 规则引擎执行错误 | 规则解析失败               |
| 9001   | 系统内部错误     | 未预期异常                 |

------

### 13. 安全方案详细设计

#### 13.1 认证授权

- **JWT Token**：登录后颁发 `access_token`（有效期 2h）+ `refresh_token`（有效期 7d）
- **RBAC 权限矩阵**：

表格



| 功能          | 管理员 | 审查员 | 访客   |
| :------------ | :----- | :----- | :----- |
| 上传文档      | ✅      | ✅      | ❌      |
| 创建审查任务  | ✅      | ✅      | ❌      |
| 查看报告      | ✅      | ✅      | 仅自己 |
| 确认/驳回违规 | ✅      | ✅      | ❌      |
| 法规库管理    | ✅      | ❌      | ❌      |
| 规则库管理    | ✅      | ❌      | ❌      |
| 用户管理      | ✅      | ❌      | ❌      |
| 系统监控      | ✅      | ❌      | ❌      |

#### 13.2 数据脱敏策略

文档解析时自动识别并脱敏：

表格



| 敏感类型 | 识别规则                | 脱敏方式                         |
| :------- | :---------------------- | :------------------------------- |
| 身份证号 | `\d{17}[\dXx]`          | 保留前 3 后 4，中间替换为 `****` |
| 手机号   | `1[3-9]\d{9}`           | 保留前 3 后 4，中间替换为 `****` |
| 银行卡号 | `\d{16,19}`             | 保留后 4 位，其余替换为 `****`   |
| 金额数字 | `\d+\.?\d*\s*[万亿]?元` | 保留量级，具体数字替换为 `***`   |

> 脱敏在**解析阶段**完成，原始文件加密存储，系统处理的是脱敏后文本。

#### 13.3 审计日志规范

所有操作记录不可篡改，字段包括：

JSON

```json
{
  "log_id": "log_uuid",
  "timestamp": "2026-08-04T21:15:00+08:00",
  "user_id": "user_001",
  "action": "CREATE_TASK",
  "resource_type": "review_task",
  "resource_id": "task_9a5b2c1d",
  "client_ip": "10.0.1.25",
  "user_agent": "Mozilla/5.0...",
  "request_payload": {"document_id": "doc_xxx"},
  "response_code": 201,
  "trace_id": "req_7f3a9b2c"
}
```

------

### 14. 测试策略

表格



| 测试层级       | 内容                                                         | 工具                    |
| :------------- | :----------------------------------------------------------- | :---------------------- |
| **单元测试**   | 规则引擎各 matcher、LLM prompt 输出解析、文档解析器          | pytest，覆盖率 ≥ 80%    |
| **集成测试**   | API 端到端调用、数据库事务、向量检索准确性                   | pytest + TestContainers |
| **Agent 测试** | LangGraph 工作流各节点状态转移、降级逻辑                     | 自定义测试框架          |
| **准确率测试** | 准备 50 份标注好的历史文档（含正负样本），测试召回率与误报率 | 人工标注基准集          |
| **性能测试**   | 并发 10/50/100 任务下的响应时间与系统稳定性                  | locust                  |
| **安全测试**   | 越权访问、SQL 注入、文件上传漏洞                             | 安全扫描工具            |

**基准测试数据集构建**：

- 收集 50 份真实产品文档（已脱敏）；
- 由资深合规专家人工标注违规点（位置、法规依据、风险等级）；
- 每轮迭代后用该数据集验证指标，确保不回归。

------

### 15. 部署架构（生产环境建议）

plain

```plain
                    [CDN / WAF]
                         │
                   [Nginx Gateway]
                    /           \
         [FastAPI API x3]  [FastAPI API x3]   # 负载均衡
              │                    │
         [Celery Worker x5]  [Celery Worker x5]  # 异步任务
              │
    ┌─────────┼─────────┐
    ▼         ▼         ▼
 [MySQL    [Neo4j    [Milvus    [Redis    [MinIO
  Primary]   Cluster]   Cluster]   Cluster]   / S3]
    │
 [MySQL Replica]
```

**容器资源建议（最小生产集群）**：

表格



| 服务          | 实例数 | CPU  | 内存 | 存储     | 说明               |
| :------------ | :----- | :--- | :--- | :------- | :----------------- |
| FastAPI       | 2      | 2核  | 4G   | 20G      | 无状态，可水平扩展 |
| Celery Worker | 3      | 4核  | 8G   | 20G      | LLM 调用密集型     |
| MySQL         | 1主1从 | 4核  | 8G   | 200G SSD | 关系数据           |
| Neo4j         | 3      | 4核  | 16G  | 500G SSD | 图数据，内存敏感   |
| Milvus        | 3      | 4核  | 16G  | 500G SSD | 向量检索，内存敏感 |
| Redis         | 3      | 2核  | 4G   | 20G      | 缓存+队列          |
| MinIO         | 2      | 2核  | 4G   | 1T       | 对象存储           |

------

### 16. 开发环境快速启动（Phase 1 用）

bash

```bash
# 1. 克隆项目
git clone <repo> && cd financial-compliance-review

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 LLM API Key 等

# 3. 启动基础设施
docker-compose -f docker/docker-compose.yml up -d mysql neo4j milvus redis

# 4. 初始化数据库
python scripts/init_data/init_mysql.py
python scripts/init_data/init_neo4j.cypher
python scripts/init_data/init_milvus.py

# 5. 安装依赖并启动服务
pip install -r requirements.txt
uvicorn src.api.main:app --reload --port 8000

# 6. 启动 Celery Worker
celery -A src.infrastructure.queue.celery_app worker -l info -Q review_tasks
```

------

## PRD 完整性核对清单

表格



| 要求项       | 状态 | 所在章节                                |
| :----------- | :--- | :-------------------------------------- |
| 业务需求     | ✅    | 第 2 章                                 |
| 功能拆分     | ✅    | 第 3 章（9 大模块）                     |
| 技术实现方案 | ✅    | 第 5 章（架构/选型/数据模型/流程/接口） |
| 项目文件目录 | ✅    | 第 6 章                                 |
| 开发风险     | ✅    | 第 7 章（10 项风险及应对）              |
| 迭代开发步骤 | ✅    | 第 8 章（5 Phase / 20 周）              |
| API 详细规范 | ✅    | 第 11 章（6 个核心接口）                |
| 错误码规范   | ✅    | 第 12 章                                |
| 安全方案     | ✅    | 第 13 章                                |
| 测试策略     | ✅    | 第 14 章                                |
| 部署架构     | ✅    | 第 15 章                                |
| 开发环境启动 | ✅    | 第 16 章                                |

------

**PRD 已全部完成。请确认以下关键决策后，我们将进入 Phase 1 编码：**

1. **LLM 接入方式**：先用哪个模型？（推荐先用QWEN或DEEPSEEK验证效果）
2. **法规数据**：是否有现成的 30 部核心法规文本？还是需要我从公开渠道帮你整理导入脚本？
3. **规则引擎启动集**：先实现哪 20 条规则？（我可以先预置"刚性兑付""保本保收益""虚假宣传"等高频规则模板）