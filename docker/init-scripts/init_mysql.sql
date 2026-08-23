-- 金融产品合规智能审查系统 - 核心表结构（对齐 PRD §5.3.1）
-- 由 mysql 官方镜像在首次初始化时自动执行（写入 MYSQL_DATABASE 指定的库）

-- ================= 用户与权限 =================
CREATE TABLE IF NOT EXISTS users (
    id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    username    VARCHAR(64)  NOT NULL UNIQUE COMMENT '登录名',
    password_hash VARCHAR(128) NOT NULL COMMENT '密码哈希',
    role        VARCHAR(32)  NOT NULL DEFAULT 'reviewer' COMMENT 'admin/reviewer/viewer',
    department  VARCHAR(128) DEFAULT NULL,
    status      TINYINT      NOT NULL DEFAULT 1 COMMENT '1启用 0禁用',
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户表';

CREATE TABLE IF NOT EXISTS roles (
    id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(32) NOT NULL UNIQUE COMMENT 'admin/reviewer/viewer',
    permissions JSON        NOT NULL COMMENT '权限列表，如 ["upload","create_task"]'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='角色权限表';

-- ================= 审查任务 =================
CREATE TABLE IF NOT EXISTS review_tasks (
    id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    task_name     VARCHAR(255) NOT NULL,
    document_name VARCHAR(255) NOT NULL,
    document_path VARCHAR(512) DEFAULT NULL COMMENT '原始文件存储路径',
    document_type VARCHAR(32)  DEFAULT NULL COMMENT '说明书/协议/宣传材料',
    domain        VARCHAR(32)  DEFAULT NULL COMMENT 'banking/fund/insurance',
    status        VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT 'pending/processing/completed/failed/cancelled',
    progress      TINYINT      NOT NULL DEFAULT 0 COMMENT '0-100',
    stages        JSON         DEFAULT NULL COMMENT '各 Agent 节点状态/耗时（PRD §11.3）',
    created_by    BIGINT UNSIGNED DEFAULT NULL,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at    DATETIME     DEFAULT NULL,
    completed_at  DATETIME     DEFAULT NULL,
    report_path   VARCHAR(512) DEFAULT NULL,
    batch_id           BIGINT UNSIGNED DEFAULT NULL COMMENT '关联 review_batches.id',
    base_document_name VARCHAR(255)    DEFAULT NULL COMMENT '对比审查旧版文件名',
    base_document_path VARCHAR(512)    DEFAULT NULL COMMENT '对比审查旧版文件路径',
    diff_changes       JSON            DEFAULT NULL COMMENT '对比审查变更片段',
    KEY idx_status (status),
    KEY idx_created_by (created_by),
    KEY idx_batch_id (batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='审查任务表';

-- ================= 审查结果 =================
CREATE TABLE IF NOT EXISTS review_results (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    task_id          BIGINT UNSIGNED NOT NULL COMMENT '关联 review_tasks.id',
    violation_type   VARCHAR(16)  NOT NULL COMMENT 'rule/llm/hybrid',
    risk_level       VARCHAR(8)   NOT NULL DEFAULT 'low' COMMENT 'high/medium/low',
    original_text    TEXT         NOT NULL COMMENT '违规原文摘录',
    location_page    INT          DEFAULT NULL COMMENT '页码（1 起）',
    location_paragraph INT        DEFAULT NULL COMMENT '段落编号',
    regulation_id    BIGINT UNSIGNED DEFAULT NULL COMMENT '关联 regulations.id',
    article_id       BIGINT UNSIGNED DEFAULT NULL COMMENT '关联 articles.id',
    rule_id          BIGINT UNSIGNED DEFAULT NULL COMMENT '命中规则（rule/hybrid 时）',
    confidence_score DECIMAL(4,3) NOT NULL DEFAULT 0 COMMENT '置信度 0-1',
    description      TEXT         DEFAULT NULL COMMENT '违规描述',
    suggestion       TEXT         DEFAULT NULL COMMENT '修改建议',
    status           VARCHAR(16)  NOT NULL DEFAULT 'pending_confirm' COMMENT 'pending_confirm/confirmed/false_positive',
    created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    confirmed_at     DATETIME     DEFAULT NULL,
    confirmed_by     BIGINT UNSIGNED DEFAULT NULL,
    KEY idx_task_id (task_id),
    KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='审查结果表';

-- ================= 法规库 =================
CREATE TABLE IF NOT EXISTS regulations (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    domain          VARCHAR(32)  NOT NULL COMMENT 'banking/fund/insurance',
    regulation_name VARCHAR(255) NOT NULL,
    regulation_no   VARCHAR(64)  DEFAULT NULL COMMENT '文号',
    issuer          VARCHAR(128) DEFAULT NULL COMMENT '发布机构',
    publish_date    DATE         DEFAULT NULL,
    effective_date  DATE         DEFAULT NULL,
    status          VARCHAR(16)  NOT NULL DEFAULT 'effective' COMMENT 'effective/amended/repealed',
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_domain (domain)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='法规表';

CREATE TABLE IF NOT EXISTS articles (
    id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    regulation_id BIGINT UNSIGNED NOT NULL COMMENT '关联 regulations.id',
    chapter_no    VARCHAR(64)  DEFAULT NULL,
    section_no    VARCHAR(16)  DEFAULT NULL,
    article_no    VARCHAR(16)  DEFAULT NULL COMMENT '如：第二十六条',
    clause_no     VARCHAR(16)  DEFAULT NULL,
    item_no       VARCHAR(16)  DEFAULT NULL,
    content       TEXT NOT NULL COMMENT '条款原文',
    vector_id     VARCHAR(64)  DEFAULT NULL COMMENT '向量库中的 ID',
    KEY idx_regulation_id (regulation_id),
    KEY idx_article_no (regulation_id, article_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='法规条款表';

-- ================= 规则库 =================
CREATE TABLE IF NOT EXISTS rules (
    id           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    domain       VARCHAR(32)  NOT NULL COMMENT 'banking/fund/insurance',
    rule_name    VARCHAR(128) NOT NULL,
    rule_type    VARCHAR(16)  NOT NULL COMMENT 'regex/keyword/condition/composite',
    rule_content JSON         NOT NULL COMMENT '规则定义（DSL）',
    severity     VARCHAR(8)   NOT NULL DEFAULT 'medium' COMMENT 'high/medium/low',
    description  VARCHAR(512) DEFAULT NULL,
    is_active    TINYINT      NOT NULL DEFAULT 1,
    version      INT          NOT NULL DEFAULT 1,
    status       VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT 'draft/pending_review/active 生效生命周期',
    created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_domain_active (domain, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='规则库表';

-- ================= 处罚案例 =================
CREATE TABLE IF NOT EXISTS penalty_cases (
    id                 BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    case_name          VARCHAR(255) NOT NULL,
    penalty_org        VARCHAR(128) DEFAULT NULL COMMENT '处罚机构',
    penalty_date       DATE         DEFAULT NULL,
    penalty_result     VARCHAR(512) DEFAULT NULL COMMENT '处罚结果',
    violation_summary  TEXT         DEFAULT NULL COMMENT '违规摘要',
    related_regulations JSON        DEFAULT NULL COMMENT '关联法规 id 数组',
    created_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='处罚案例表';

-- ================= 审计日志 =================
CREATE TABLE IF NOT EXISTS audit_logs (
    id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id       BIGINT UNSIGNED DEFAULT NULL COMMENT '操作用户',
    username      VARCHAR(64)     DEFAULT NULL COMMENT '用户角色',
    action        VARCHAR(128)    NOT NULL COMMENT 'method + path',
    resource_type VARCHAR(64)     DEFAULT NULL,
    resource_id   VARCHAR(64)     DEFAULT NULL,
    client_ip     VARCHAR(45)     DEFAULT NULL,
    user_agent    VARCHAR(255)    DEFAULT NULL,
    status_code   INT             DEFAULT NULL,
    detail        TEXT            DEFAULT NULL,
    created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_user_time (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='审计日志表';

-- ================= 审查批次 =================
CREATE TABLE IF NOT EXISTS review_batches (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    batch_name      VARCHAR(255) NOT NULL COMMENT '批次名称',
    status          VARCHAR(16)  NOT NULL DEFAULT 'running' COMMENT 'running/completed/failed',
    total_count     INT          NOT NULL DEFAULT 0,
    completed_count INT          NOT NULL DEFAULT 0,
    failed_count    INT          NOT NULL DEFAULT 0,
    created_by      BIGINT UNSIGNED DEFAULT NULL,
    source_type     VARCHAR(32)     DEFAULT NULL COMMENT 'manual/impact_assessment 批次来源',
    source_id       BIGINT UNSIGNED DEFAULT NULL COMMENT '来源记录 id',
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at    DATETIME     DEFAULT NULL,
    KEY idx_created_by (created_by)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='审查批次表';

-- ================= 监管动态追踪 =================
CREATE TABLE IF NOT EXISTS regulation_updates (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    source              VARCHAR(16)  NOT NULL COMMENT '来源 nfra/csrc/pbc',
    title               VARCHAR(255) NOT NULL COMMENT '法规名称',
    doc_no              VARCHAR(64)  DEFAULT NULL COMMENT '文号',
    publish_date        DATE         DEFAULT NULL,
    url                 VARCHAR(512) DEFAULT NULL COMMENT '原文链接',
    domain              VARCHAR(32)  DEFAULT NULL COMMENT 'LLM判定领域',
    doc_type            VARCHAR(32)  DEFAULT NULL COMMENT '规章/规范性文件/办法/公告',
    llm_summary         VARCHAR(512) DEFAULT NULL COMMENT 'LLM摘要',
    matched_regulations JSON         DEFAULT NULL COMMENT '匹配的库内法规',
    status              VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT 'pending/imported/ignored/in_db',
    match_type          VARCHAR(16)  DEFAULT NULL COMMENT 'fetch/confirm/manual/in_db',
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_source_title (source, title)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='监管动态追踪表';

-- ================= 规则与法规条款关联 =================
CREATE TABLE IF NOT EXISTS rule_regulation_links (
    id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    rule_id       BIGINT UNSIGNED NOT NULL COMMENT '关联规则',
    regulation_id BIGINT UNSIGNED DEFAULT NULL COMMENT '库内法规',
    article_id    BIGINT UNSIGNED DEFAULT NULL COMMENT '具体条款',
    citation      VARCHAR(255)    DEFAULT NULL COMMENT '引用文本，如《销售管理办法》第X条',
    link_type     VARCHAR(16)     NOT NULL DEFAULT 'support' COMMENT 'support/derive',
    source        VARCHAR(16)     NOT NULL DEFAULT 'manual' COMMENT 'manual/impact_analysis',
    created_by    BIGINT UNSIGNED DEFAULT NULL,
    created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_link_rule (rule_id),
    KEY idx_link_regulation (regulation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='规则与法规条款关联表';

-- ================= 产品材料台账 =================
CREATE TABLE IF NOT EXISTS product_materials (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name                VARCHAR(255) NOT NULL COMMENT '材料名称',
    product_type        VARCHAR(32)  NOT NULL COMMENT 'fund/insurance/wealth',
    material_type       VARCHAR(32)  NOT NULL COMMENT '宣传单页/海报/推文/话术稿',
    version             VARCHAR(32)  NOT NULL DEFAULT 'v1',
    owner               VARCHAR(64)  DEFAULT NULL COMMENT '负责人',
    document_id         VARCHAR(64)  DEFAULT NULL COMMENT '关联待审文档 doc_xxxxxxxx',
    status              VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT 'active/archived',
    last_review_status  VARCHAR(16)  DEFAULT NULL COMMENT 'clean/violation/failed',
    last_reviewed_at    DATETIME     DEFAULT NULL,
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_material_product (product_type, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='产品材料台账表';

-- ================= 法规影响评估 =================
CREATE TABLE IF NOT EXISTS impact_assessments (
    id                   BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    regulation_update_id BIGINT UNSIGNED DEFAULT NULL COMMENT '触发源:监管动态',
    penalty_case_id      BIGINT UNSIGNED DEFAULT NULL COMMENT '触发源:处罚案例',
    title                VARCHAR(255) NOT NULL,
    summary              VARCHAR(1024) DEFAULT NULL COMMENT '评估结论摘要',
    status               VARCHAR(16)   NOT NULL DEFAULT 'draft' COMMENT 'draft/pending_review/confirmed/dismissed',
    items                JSON          DEFAULT NULL COMMENT '影响明细:受影响规则与材料及风险等级',
    high_count           INT           NOT NULL DEFAULT 0,
    medium_count         INT           NOT NULL DEFAULT 0,
    low_count            INT           NOT NULL DEFAULT 0,
    created_by           BIGINT UNSIGNED DEFAULT NULL,
    confirmed_by         BIGINT UNSIGNED DEFAULT NULL,
    confirmed_at         DATETIME      DEFAULT NULL,
    created_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_assessment_update (regulation_update_id),
    KEY idx_assessment_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='法规影响评估表';

-- LangGraph checkpoint 持久化（人工复核 interrupt/resume 跨进程、跨重启恢复；
-- 已有库由 MySQLCheckpointSaver.setup() 幂等补建，无需手工迁移）
CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    thread_id           VARCHAR(128)  NOT NULL,
    checkpoint_ns       VARCHAR(255)  NOT NULL DEFAULT '',
    checkpoint_id       VARCHAR(64)   NOT NULL,
    parent_checkpoint_id VARCHAR(64)  DEFAULT NULL,
    type                VARCHAR(64)   NOT NULL,
    checkpoint          LONGBLOB      NOT NULL,
    metadata_type       VARCHAR(64)   DEFAULT NULL,
    metadata            LONGBLOB      DEFAULT NULL,
    UNIQUE KEY uk_cp_thread (thread_id, checkpoint_ns, checkpoint_id),
    KEY idx_cp_thread (thread_id, checkpoint_ns, id),
    KEY idx_cp_parent (parent_checkpoint_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='LangGraph checkpoint 持久化(人工复核中断/恢复)';

CREATE TABLE IF NOT EXISTS langgraph_writes (
    thread_id     VARCHAR(128) NOT NULL,
    checkpoint_ns VARCHAR(255) NOT NULL DEFAULT '',
    checkpoint_id VARCHAR(64)  NOT NULL,
    task_id       VARCHAR(64)  NOT NULL,
    idx           INT          NOT NULL,
    channel       VARCHAR(255) NOT NULL,
    type          VARCHAR(64)  NOT NULL,
    write_blob     LONGBLOB     NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='LangGraph pending writes(节点写通道)';

-- ================= 默认数据 =================
INSERT INTO roles (name, permissions) VALUES
    ('admin',    JSON_ARRAY('upload','create_task','view_report','confirm','manage_regulations','manage_rules','manage_users','monitor')),
    ('reviewer', JSON_ARRAY('upload','create_task','view_report','confirm')),
    ('viewer',   JSON_ARRAY('view_report'))
ON DUPLICATE KEY UPDATE name = VALUES(name);

-- 初始管理员（密码：admin123，生产环境务必修改）
-- 占位，后续由安全模块写入 bcrypt 哈希
INSERT IGNORE INTO users (username, password_hash, role, department)
    VALUES ('admin', 'placeholder-hash', 'admin', '合规部');
