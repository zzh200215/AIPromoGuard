/**
 * 临时前端视觉验证 mock API（仅本地开发/截图验证用，不进生产路径）。
 * 覆盖登录 + 工作台 + 任务 + 影响中心 + 台账 + 知识库 + 管理页所需的最小接口集。
 * 启动：node dev-mock.mjs   （监听 8000，配合 vite proxy /api/v1）
 */
import http from 'node:http'

const ok = (data) => JSON.stringify({ code: 0, message: 'ok', data })

const TASK = (i, status, progress, extra = {}) => ({
  id: i,
  task_name: `稳健回报混合基金单页A${i > 1 ? `-v${i}` : ''}`,
  document_name: '稳健回报混合基金宣传单页.pdf',
  document_type: '宣传材料',
  domain: 'fund',
  profile: 'standard',
  status,
  progress,
  stages: {
    classify: { status: 'completed', cost_ms: 120 },
    regulation_match: { status: 'completed', cost_ms: 430 },
    rule_scan: { status: 'completed', cost_ms: 65 },
    llm_scan: { status: 'completed', cost_ms: 3200 },
  },
  created_at: '2026-09-11 10:24:00',
  ...extra,
})

const REPORT = {
  report_version: '1.2',
  task_id: 1,
  document_name: '稳健回报混合基金宣传单页.pdf',
  domain: 'fund',
  generated_at: '2026-09-11 10:26:40',
  summary: { total_violations: 5, high_risk: 2, medium_risk: 2, low_risk: 1, pending_verification: 1 },
  violations: [
    {
      source: 'rule', violation_type: 'rule', type: '禁止性', rule_id: 1, rule_name: '承诺保本保收益',
      original_text: '本金安全无忧，稳赚不赔的稳健之选', page: 1, paragraph: 2, confidence: 0.99,
      severity: 'high', risk_level: 'high', result_id: 1, human_status: 'confirmed', human_confirmed_by: 2, regulation_id: 2,
      description: '命中禁止性表述：承诺保本保收益', related_regulations: ['《公开募集证券投资基金销售机构监督管理办法》第二十四条'],
      suggestion: '删除保本保收益承诺，改为披露风险提示', related_cases: [
        { case_name: '某银行理财违规承诺收益被罚', penalty_org: '金监总局', penalty_date: '2026-07-15', similarity: 0.87 },
      ],
    },
    {
      source: 'llm', violation_type: 'llm', type: '限制性', rule_name: null,
      original_text: '历史年化收益均超 8%，未来可期', page: 1, paragraph: 3, confidence: 0.72,
      severity: 'high', risk_level: 'high', result_id: 2, flag: '建议关注', human_status: 'false_positive', human_confirmed_by: 2,
      description: '以历史业绩暗示未来收益', related_regulations: ['《证券投资基金销售管理办法》相关条款'],
      suggestion: '补充“过往业绩不预示未来表现”声明', related_cases: [],
    },
    {
      source: 'hybrid', violation_type: 'hybrid', type: '披露性', rule_id: 7, rule_name: '风险揭示缺失',
      original_text: '立即申购，享受限时费率优惠', page: 2, paragraph: 1, confidence: 0.95,
      severity: 'medium', risk_level: 'medium', result_id: 3, human_status: 'confirmed', human_confirmed_by: 0,
      related_regulations: [], suggestion: '补充风险揭示与费率说明', related_cases: [],
    },
  ],
  llm_usage: { calls: 6, total_tokens: 18432, model: 'qwen-plus', priced: true, estimated_cost_cny: 0.35, failed_blocks: 0 },
  human_review: {
    pending_confirm: 0, confirmed: 2, false_positive: 1, auto_confirmed: 1, manual_reviewed: 2,
    final_total: 2, final_high: 1, final_medium: 1, final_low: 0,
    last_confirmed_at: '2026-09-12 09:30:00',
  },
  regulations: [
    { id: 2, regulation_name: '公开募集证券投资基金销售机构监督管理办法', regulation_no: '证监会令第196号' },
    { id: 1, regulation_name: '关于加强金融产品网络营销管理的通知', regulation_no: '金规〔2026〕3号' },
  ],
  pending_verification: [
    { risk_level: 'medium', original_text: '适合所有投资者配置', page: 2, paragraph: 4, reasons: ['适当性匹配需人工判断目标客群'] },
  ],
}

// 签发状态（mock 内存态）：POST /tasks/1/sign-off 后注入报告响应
let mockSignOff = null

// 人工判定内存态：批量确认/撤销直接改 REPORT.violations，报告计数动态重算
const nowStr = () => new Date().toISOString().slice(0, 19).replace('T', ' ')

function mockApplyVerdict(ids, verdict) {
  const idSet = new Set(ids)
  let updated = 0
  for (const v of REPORT.violations) {
    if (!idSet.has(v.result_id)) continue
    v.human_status = verdict
    v.human_confirmed_by = 1 // mock 登录用户 admin
    v.human_confirmed_at = nowStr()
    updated++
  }
  return updated
}

const RESULTS = {
  task_id: 1,
  total: 4,
  items: [
    { result_id: 1, violation_type: 'rule', risk_level: 'high', original_text: '本金安全无忧，稳赚不赔的稳健之选', location_page: 1, location_paragraph: 2, rule_id: 1, confidence_score: 0.99, status: 'pending_confirm', regulation_name: '公开募集证券投资基金销售机构监督管理办法', article_no: '第二十四条', article_excerpt: '基金销售机构不得预测基金投资业绩...' },
    { result_id: 2, violation_type: 'llm', risk_level: 'high', original_text: '历史年化收益均超 8%，未来可期', location_page: 1, location_paragraph: 3, confidence_score: 0.72, status: 'pending_confirm', regulation_name: null, article_no: null },
    { result_id: 3, violation_type: 'hybrid', risk_level: 'medium', original_text: '立即申购，享受限时费率优惠', location_page: 2, location_paragraph: 1, rule_id: 7, confidence_score: 0.95, status: 'confirmed', auto_confirmed: true, confirmed_at: '2026-09-11 10:26:40', regulation_name: '证券投资基金销售管理办法', article_no: '第十八条' },
    // PR-2 演示样本：低置信×高风险（复核路由最优先 + 队列行级引导高亮）
    { result_id: 4, violation_type: 'llm', risk_level: 'high', original_text: '预计年化收益可达 12%，把握黄金配置窗口', location_page: 2, location_paragraph: 3, confidence_score: 0.35, status: 'pending_confirm', regulation_name: null, article_no: null },
  ],
}

const routes = {
  'POST /api/v1/auth/login': () =>
    ok({ access_token: 'mock-token', user: { id: 1, username: 'admin', role: 'admin', department: '合规部' } }),
  'GET /api/v1/auth/me': () => ok({ id: 1, username: 'admin', role: 'admin', department: '合规部' }),

  'GET /api/v1/impact/overview': () =>
    ok({
      pending_updates: 3, updates_to_analyze: 2, pending_assessments: 4,
      assessments_by_status: { draft: 2, pending_review: 2 }, high_risk_materials: 3,
      running_batches: 1, remediation_total: 8, remediation_pending: 3, remediation_done: 4,
      rules_pending_publish: 2, active_rules: 75,
    }),

  'GET /api/v1/tasks': (searchParams) => {
    const search = (searchParams.get('search') || '').trim()
    const status = searchParams.get('status') || ''
    const page = Number(searchParams.get('page') || 1)
    const pageSize = Number(searchParams.get('page_size') || 8)
    const all = Array.from({ length: 24 }, (_, i) => i + 1).map((i) =>
      TASK(i, i % 3 === 1 ? 'completed' : i % 3 === 2 ? 'running' : 'pending', i % 3 === 1 ? 100 : i * 12),
    )
    const filtered = all.filter((t) => {
      if (status && t.status !== status) return false
      if (search && !`${t.task_name}${t.document_name}`.toLowerCase().includes(search.toLowerCase())) {
        return false
      }
      return true
    })
    return ok({
      items: filtered.slice((page - 1) * pageSize, page * pageSize),
      total: filtered.length,
      page,
      page_size: pageSize,
    })
  },
  'POST /api/v1/results/bulk-confirm': (searchParams, body) => {
    const verdict = body?.verdict === 'false_positive' ? 'false_positive' : 'confirmed'
    return ok({ updated: mockApplyVerdict(body?.result_ids ?? [], verdict), skipped: [] })
  },
  'POST /api/v1/results/revert': (searchParams, body) => {
    const idSet = new Set(body?.result_ids ?? [])
    const skipped = []
    let updated = 0
    for (const id of idSet) {
      const v = REPORT.violations.find((x) => x.result_id === id)
      if (!v) {
        skipped.push({ result_id: id, reason: 'not_found' })
        continue
      }
      if (!v.human_status || v.human_status === 'pending_confirm') {
        skipped.push({ result_id: id, reason: 'already_pending' })
        continue
      }
      v.human_status = 'pending_confirm'
      v.human_confirmed_by = null
      v.human_confirmed_at = null
      updated++
    }
    return ok({ updated, skipped })
  },
  'POST /api/v1/ai/tasks/1/ask': (searchParams, body) => {
    const q = String(body?.question ?? '')
    const usage = { prompt_tokens: 812, completion_tokens: 286, total_tokens: 1098, calls: 1 }
    if (/收益|承诺|保本/.test(q)) {
      return ok({
        answer:
          '是的。「本金安全无忧，稳赚不赔的稳健之选」违反收益承诺类禁止性规定：\n1. 承诺保本保收益，违反《公开募集证券投资基金销售机构监督管理办法》第二十四条（销售机构不得预测投资业绩、不得承诺本金不受损失）。\n2. 「历史年化收益均超 8%，未来可期」以历史业绩暗示未来收益，同样构成违规。\n建议：删除全部收益承诺表述，统一改为揭示风险的合规话术并补充风险提示声明。',
        refs: [
          { regulation_id: 2, name: '公开募集证券投资基金销售机构监督管理办法', article_no: '第二十四条', quote: '基金销售机构不得预测基金投资业绩，不得承诺本金不受损失或者承诺最低收益' },
          { regulation_id: 1, name: '关于加强金融产品网络营销管理的通知', article_no: '第八条', quote: '不得利用历史业绩进行虚假或引人误解的宣传' },
        ],
        usage,
      })
    }
    if (/整改|修改|建议|怎么改/.test(q)) {
      return ok({
        answer:
          '按优先级给出三条整改建议：\n1. 【高风险】删除「本金安全无忧，稳赚不赔」收益承诺，替换为「基金有风险，投资须谨慎」等风险揭示表述。\n2. 【高风险】「未来可期」等暗示性收益表述改为「过往业绩不预示未来表现」的规范声明。\n3. 【中风险】限时优惠与申购引导需补充费用构成说明与风险匹配提示。\n完成以上修改后建议重新送审一次以确认清零。',
        refs: [
          { regulation_id: 2, name: '公开募集证券投资基金销售机构监督管理办法', article_no: '第二十四条', quote: null },
          { regulation_id: 1, name: '关于加强金融产品网络营销管理的通知', article_no: '第十二条', quote: null },
        ],
        usage,
      })
    }
    return ok({
      answer:
        '本报告共检出 3 条违规：高风险 2 条（收益承诺、历史业绩暗示）、中风险 1 条（风险揭示缺失）。整体风险集中在「收益承诺与风险揭示不足」两类主题上，其中 1 条为系统自动确认、2 条待人工判定。需要我就某一条违规展开依据或给出改写建议，可以直接说明条款内容。',
      refs: [
        { regulation_id: 2, name: '公开募集证券投资基金销售机构监督管理办法', article_no: '第二十四条', quote: null },
      ],
      usage,
    })
  },
  'POST /api/v1/ai/results/1/rewrite': () =>
    ok({
      rewritten: '本基金不保证本金及收益，过往业绩不预示未来表现。投资须谨慎，请阅读基金合同与风险揭示书。',
      changes: [
        '删除「本金安全无忧，稳赚不赔」的收益承诺',
        '补充「过往业绩不预示未来表现」的规范声明',
        '增加风险揭示与阅读引导，符合适当性管理要求',
      ],
      usage: { prompt_tokens: 520, completion_tokens: 96, total_tokens: 616, calls: 1 },
    }),
  'POST /api/v1/ai/results/2/rewrite': () =>
    ok({
      rewritten: '该基金成立于 2019 年，过去三年年化回报率为 8.2%（数据来源：基金定期报告）。过往业绩不预示未来表现，投资须谨慎。',
      changes: [
        '为历史业绩补充数据来源与统计区间',
        '删除「未来可期」等暗示性表述',
        '补充过往业绩免责声明',
      ],
      usage: { prompt_tokens: 534, completion_tokens: 112, total_tokens: 646, calls: 1 },
    }),
  'POST /api/v1/ai/results/3/rewrite': () =>
    ok({
      rewritten: '本基金单笔申购费率 0.15%（原费率 1.5%，优惠期限以公告为准）。基金投资可能产生本金损失，请根据自身风险承受能力审慎决策。',
      changes: [
        '限时优惠补充原费率与优惠期限说明',
        '删除「立即申购」催促性话术',
        '补充风险匹配提示，满足信息披露要求',
      ],
      usage: { prompt_tokens: 528, completion_tokens: 104, total_tokens: 632, calls: 1 },
    }),
  'POST /api/v1/ai/tasks/1/summary': () =>
    ok({
      text: '本材料整体风险偏高：2 条高风险违规集中于「收益承诺与历史业绩暗示」，1 条中风险涉及风险揭示缺失。核心问题是以确定性话术诱导申购，与销售适当性和信息披露要求冲突。建议优先删除全部收益承诺类表述、补充规范的风险提示声明后重新送审。',
      model: 'qwen-plus',
      generated_at: '2026-09-13 15:20:00',
      stale: false,
    }),
  'POST /api/v1/ai/results/1/verdict-advice': () =>
    ok({
      suggested_verdict: 'confirmed',
      confidence: 0.92,
      reasons: [
        '「稳赚不赔」属于典型收益承诺表述，与《公开募集证券投资基金销售机构监督管理办法》第二十四条直接冲突',
        '命中规则「承诺保本保收益」为禁止性条款，规则匹配置信度 0.99',
      ],
      usage: { prompt_tokens: 486, completion_tokens: 88, total_tokens: 574, calls: 1 },
    }),
  'POST /api/v1/ai/results/2/verdict-advice': () =>
    ok({
      suggested_verdict: 'confirmed',
      confidence: 0.86,
      reasons: [
        '以历史数据暗示未来收益，符合夸大宣传特征',
        '缺少「过往业绩不预示未来表现」的配套声明',
      ],
      usage: { prompt_tokens: 502, completion_tokens: 76, total_tokens: 578, calls: 1 },
    }),
  'POST /api/v1/ai/results/3/verdict-advice': () =>
    ok({
      suggested_verdict: 'confirmed',
      confidence: 0.68,
      reasons: [
        '限时优惠引导未附带费用构成与风险提示，与信息披露要求存在差距',
        '置信度较低：需人工确认材料其他版面是否已包含风险揭示内容',
      ],
      usage: { prompt_tokens: 498, completion_tokens: 82, total_tokens: 580, calls: 1 },
    }),
  'GET /api/v1/tasks/1': () => ok(TASK(1, 'completed', 100)),
  'GET /api/v1/tasks/15': () => ok(TASK(15, 'failed', 100)),
  'GET /api/v1/tasks/1/report': () => {
    const v = REPORT.violations
    const byStatus = (s) => v.filter((x) => x.human_status === s).length
    const finals = v.filter((x) => x.human_status === 'confirmed')
    const manualAt = v.map((x) => x.human_confirmed_at).filter(Boolean).sort()
    return ok({
      ...REPORT,
      human_review: {
        ...REPORT.human_review,
        pending_confirm: byStatus('pending_confirm'),
        confirmed: byStatus('confirmed'),
        false_positive: byStatus('false_positive'),
        auto_confirmed: v.filter((x) => x.human_status === 'confirmed' && x.human_confirmed_by === 0).length,
        manual_reviewed: v.filter(
          (x) => (x.human_status === 'confirmed' || x.human_status === 'false_positive') && x.human_confirmed_by > 0,
        ).length,
        final_total: finals.length,
        final_high: finals.filter((x) => x.severity === 'high').length,
        final_medium: finals.filter((x) => x.severity === 'medium').length,
        final_low: finals.filter((x) => x.severity === 'low').length,
        last_confirmed_at: manualAt.length ? manualAt[manualAt.length - 1] : REPORT.human_review.last_confirmed_at,
      },
      sign_off: mockSignOff,
    })
  },
  'POST /api/v1/tasks/1/sign-off': (searchParams, body) => {
    mockSignOff = {
      decision: body?.decision === 'rejected' ? 'rejected' : 'released',
      username: 'admin',
      note: body?.note ?? null,
      created_at: new Date().toISOString().slice(0, 19).replace('T', ' '),
    }
    return ok({ task_id: 1, ...mockSignOff })
  },
  'GET /api/v1/tasks/1/sign-off': () => ok({ task_id: 1, decision: mockSignOff?.decision ?? null, username: mockSignOff?.username ?? null, note: mockSignOff?.note ?? null, created_at: mockSignOff?.created_at ?? null }),
  'GET /api/v1/tasks/1/results': () => ok(RESULTS),
  'GET /api/v1/tasks/1/document-content': () =>
    ok({
      task_id: 1,
      document_name: '稳健回报混合基金宣传单页.pdf',
      blocks: [
        { text: '稳健回报混合基金 · 宣传单页', page: 1, paragraph: 1, heading: true },
        {
          text: '本产品由某某基金管理有限公司管理，风险等级为中风险，过往业绩不代表未来表现。',
          page: 1, paragraph: 2, heading: false,
        },
        { text: '本金安全无忧，稳赚不赔的稳健之选', page: 1, paragraph: 3, heading: false },
        { text: '历史年化收益均超 8%，未来可期', page: 1, paragraph: 4, heading: false },
        { text: '产品费率说明', page: 2, paragraph: 1, heading: true },
        {
          text: '立即申购，享受限时费率优惠。认购费率 0.8%，管理费 1.2%/年。',
          page: 2, paragraph: 2, heading: false,
        },
        { text: '适合所有投资者配置，无需风险评估。', page: 2, paragraph: 3, heading: false },
      ],
    }),

  'GET /api/v1/system/monitor': () =>
    ok({
      timestamp: '2026-09-12 10:00:00',
      tasks: { last_24h: 12, completed: 9, running: 1, pending: 2, avg_duration_seconds: 42.5 },
      database: { ok: true, knowledge_base: { regulations: 48, rules: 82, users: 6 } },
      vector_store: { legal_articles: 809, legal_penalty_cases: 68 },
      graph: {
        available: true,
        nodes: { Regulation: 48, Article: 809, ViolationPattern: 130, PenaltyCase: 68, ProductType: 12 },
        relationships: { RELATES_TO: 530, VIOLATES: 260, EVIDENCED_BY: 96 },
      },
      celery: { available: true, queue_depth: 3, workers_alive: ['fcr-worker@1'] },
      audit: { last_24h: 210, errors_last_24h: 0 },
    }),

  'GET /api/v1/regulatory-updates': () =>
    ok({
      items: [
        { id: 3, source: 'pbc', title: '关于规范现金管理类产品运作的通知', doc_no: '银发〔2026〕12号', publish_date: '2026-09-10', domain: 'wealth', llm_summary: '收紧现金管理类产品投资范围与披露要求', status: 'pending' },
        { id: 1, source: 'nfra', title: '关于加强金融产品网络营销管理的通知', doc_no: '金规〔2026〕3号', publish_date: '2026-09-01', domain: 'banking', llm_summary: '细化网络营销宣传用语与披露要求', status: 'imported' },
        { id: 2, source: 'csrc', title: '公开募集证券投资基金销售机构监督管理办法', doc_no: '证监会令第196号', publish_date: '2026-08-20', domain: 'fund', llm_summary: '强调适当性与风险揭示', status: 'imported' },
      ],
      total: 3,
    }),
  'POST /api/v1/regulatory-updates/3/confirm': () => ok({ regulation_id: 3, regulation_name: '关于规范现金管理类产品运作的通知' }),
  'POST /api/v1/regulatory-updates/1/confirm': () => ok({ regulation_id: 1, regulation_name: '关于加强金融产品网络营销管理的通知' }),
  'POST /api/v1/regulatory-updates/1/ignore': () => ok({}),
  'POST /api/v1/tasks': (searchParams, body) => ok({ task_id: 1 }),
  'POST /api/v1/documents/text': () =>
    ok({ document_id: 'doc_paste01', file_name: '粘贴文本.txt', file_size: 128, status: 'uploaded' }),

  'GET /api/v1/notifications': () =>
    ok({
      items: [
        { id: 2, type: 'batch_failed', title: '批次审查完成（含失败）：复批：网络营销新规影响材料', body: '成功 4 / 失败 2，失败任务可在批次详情页一键重试。', link: '/batches/2', is_read: 0, created_at: '2026-09-12 15:20:00' },
        { id: 1, type: 'task_failed', title: '任务审查失败：稳健回报混合基金单页A-v15', body: '常见原因：文档格式异常、依赖服务未就绪。可在任务详情页重试。', link: '/tasks/15', is_read: 0, created_at: '2026-09-12 14:05:00' },
      ],
      total: 2,
      unread: 2,
    }),
  'POST /api/v1/notifications/2/read': () => ok({ id: 2, is_read: 1 }),
  'POST /api/v1/notifications/1/read': () => ok({ id: 1, is_read: 1 }),
  'POST /api/v1/notifications/read-all': () => ok({ updated: 2 }),
  'POST /api/v1/rules/1/re-review': () =>
    ok({
      batch_id: 3,
      batch_name: '规则重审：承诺保本保收益',
      total_count: 2,
      task_ids: [21, 22],
      skipped: [{ task_id: 9, name: '历史任务9', reason: '原文档已不存在' }],
    }),
  'GET /api/v1/impact/penalty-cases': () =>
    ok({
      items: [
        { id: 1, case_name: '某银行理财违规承诺收益被罚', penalty_org: '金监总局某监管局', penalty_date: '2026-07-15', violation_summary: '宣传材料承诺保本保收益', related_regulation_count: 3 },
        { id: 2, case_name: '某基金公司夸大业绩宣传被罚', penalty_org: '证监会', penalty_date: '2026-06-02', violation_summary: '夸大过往业绩、误导投资者', related_regulation_count: 2 },
      ],
      total: 2,
    }),
  'POST /api/v1/impact/assessments': () =>
    ok({ id: 9, title: '影响评估', status: 'draft', items: { rules: [], materials: [] }, high_count: 0, medium_count: 0, low_count: 0 }),
  'GET /api/v1/impact/assessments': () =>
    ok({
      items: [
        { id: 9, title: '关于加强金融产品网络营销管理的通知', update_title: '关于加强金融产品网络营销管理的通知', status: 'pending_review', high_count: 2, medium_count: 1, low_count: 0, created_at: '2026-09-11 15:02:00' },
        { id: 8, title: '某银行理财违规承诺收益被罚', update_title: '某银行理财违规承诺收益被罚', status: 'confirmed', high_count: 1, medium_count: 2, low_count: 1, created_at: '2026-09-10 09:12:00' },
      ],
      total: 2,
    }),
  'GET /api/v1/impact/assessments/9': () =>
    ok({
      id: 9,
      title: '关于加强金融产品网络营销管理的通知',
      status: 'pending_review',
      high_count: 2, medium_count: 1, low_count: 0,
      summary: '本次新规对营销宣传用语、披露完整性提出 3 类新增要求，预扫命中 5 条规则、影响 10 份在用材料，其中 2 份高风险。',
      items: {
        rules: [
          { rule_id: 1, rule_name: '承诺保本保收益', domain: 'banking', severity: 'high', matched_by: 'link', confirm_status: 'pending' },
          { rule_id: 2, rule_name: '夸大过往业绩', domain: 'fund', severity: 'high', matched_by: 'keyword', confirm_status: 'pending' },
        ],
        materials: [
          { material_id: 1, name: '稳健回报混合基金单页A', product_type: '基金', material_type: '宣传单页', owner: '王敏', matched_rules: [2], risk_score: 86, risk_level: 'high', reason: '命中 2 条高风险规则且有同类罚单', confirm_status: 'pending' },
          { material_id: 2, name: '安享养老保险产品海报', product_type: '保险', material_type: '海报', owner: '李强', matched_rules: [1], risk_score: 45, risk_level: 'medium', reason: '命中 1 条规则', confirm_status: 'pending' },
        ],
        remediation: [
          { batch_id: 2, task_id: 12, task_status: 'completed', material_id: 1, material_name: '稳健回报混合基金单页A', violation_count: 3, requires_remediation: true, decision: 'pending' },
          { batch_id: 2, task_id: 13, task_status: 'completed', material_id: 2, material_name: '安享养老保险产品海报', violation_count: 0, requires_remediation: false, decision: 'done' },
          // R3-2 v2 演示：依据失效待更新条目（无审查任务，按 material_id 决策）
          { kind: 'stale', material_id: 3, material_name: '结构性存款产品说明书', version: 'v3', last_review_status: 'failed', reasons: ['规则已停用：禁止宣称理财产品保本', '法规已废止/失效：旧版理财销售管理办法'], requires_remediation: true, decision: 'pending' },
        ],
      },
      batches: [{ id: 2, batch_name: '复批：网络营销新规影响材料', status: 'completed', total_count: 6, completed_count: 6 }],
    }),
  'GET /api/v1/impact/assessments/8': () => routes['GET /api/v1/impact/assessments/9'](),

  // R3-2 v2：依据失效材料写入系统整改清单（演示：同步后返回容器评估 9）
  'POST /api/v1/impact/materials/stale/sync': () =>
    ok({ assessment_id: 9, checked: 3, stale_count: 1, added: 1, refreshed: 0, resolved: 0, reopened: 0, total: 3 }),
  // 整改决策（审查项传 task_id、stale 项传 material_id）：前端决策后重新拉详情，这里只回 ok
  'POST /api/v1/impact/assessments/9/remediation': () => ok({ items: [] }),

  'GET /api/v1/impact/materials': () =>
    ok({
      items: [
        { id: 1, name: '稳健回报混合基金单页A', product_type: 'fund', material_type: '宣传单页', version: 'v2', owner: '王敏', document_id: 'doc_a1b2c3', status: 'active', last_review_status: 'violation', created_at: '2026-08-01 09:00:00' },
        { id: 2, name: '安享养老保险产品海报', product_type: 'insurance', material_type: '海报', version: 'v1', owner: '李强', document_id: 'doc_d4e5f6', status: 'active', last_review_status: 'clean', created_at: '2026-08-03 09:00:00' },
        { id: 3, name: '结构性存款产品说明书', product_type: 'wealth', material_type: '说明书', version: 'v3', owner: '赵芳', document_id: 'doc_g7h8i9', status: 'active', last_review_status: 'failed', created_at: '2026-08-05 09:00:00' },
      ],
      total: 3,
    }),

  'GET /api/v1/batches': () =>
    ok({
      items: [
        { id: 2, batch_name: '复批：网络营销新规影响材料', status: 'failed', total_count: 6, completed_count: 4, failed_count: 2, created_at: '2026-09-11 15:10:00' },
        { id: 1, batch_name: '三季度集中送审批次', status: 'running', total_count: 12, completed_count: 7, failed_count: 1, created_at: '2026-09-10 09:00:00' },
      ],
      total: 2,
    }),
  'GET /api/v1/batches/2': () =>
    ok({
      batch: { id: 2, batch_name: '复批：网络营销新规影响材料', status: 'failed', total_count: 6, completed_count: 4, failed_count: 2, created_at: '2026-09-11 15:10:00' },
      tasks: [11, 12, 13, 14].map((i) => TASK(i, 'completed', 100)).concat([
        TASK(15, 'failed', 100),
        TASK(16, 'failed', 100),
      ]),
    }),
  'GET /api/v1/batches/1': () =>
    ok({
      batch: { id: 1, batch_name: '三季度集中送审批次', status: 'running', total_count: 12, completed_count: 7, failed_count: 1, created_at: '2026-09-10 09:00:00' },
      tasks: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => TASK(i, i % 3 === 1 ? 'completed' : i % 3 === 2 ? 'running' : 'pending', i % 3 === 1 ? 100 : i * 12)),
    }),
  'GET /api/v1/batches/3': () =>
    ok({
      batch: { id: 3, batch_name: '规则重审：承诺保本保收益', status: 'running', total_count: 2, completed_count: 0, failed_count: 0, created_at: '2026-09-12 15:00:00' },
      tasks: [TASK(21, 'running', 40), TASK(22, 'pending', 0)],
    }),
  'POST /api/v1/batches/2/retry-failed': () => ok({ batch_id: 2, retried: [15, 16], skipped: 0 }),
  'POST /api/v1/tasks/15/retry': () => ok({ task_id: 15, status: 'pending' }),
  'POST /api/v1/tasks/16/retry': () => ok({ task_id: 16, status: 'pending' }),

  'GET /api/v1/regulations': () =>
    ok({
      items: [
        { id: 1, regulation_name: '关于加强金融产品网络营销管理的通知', regulation_no: '金规〔2026〕3号', issuer: '国家金融监督管理总局', domain: 'banking', status: 'effective', publish_date: '2026-09-01' },
        { id: 2, regulation_name: '公开募集证券投资基金销售机构监督管理办法', regulation_no: '证监会令第196号', issuer: '中国证监会', domain: 'fund', status: 'effective', publish_date: '2026-08-20' },
        { id: 3, regulation_name: '互联网保险业务监管办法', regulation_no: '银保监会令第13号', issuer: '银保监会', domain: 'insurance', status: 'amended', publish_date: '2025-12-10' },
      ],
      total: 48,
    }),
  'GET /api/v1/regulations/1': () =>
    ok({ id: 1, regulation_name: '关于加强金融产品网络营销管理的通知', regulation_no: '金规〔2026〕3号', issuer: '国家金融监督管理总局', domain: 'banking', status: 'effective', publish_date: '2026-09-01', effective_date: '2026-10-01' }),
  'GET /api/v1/regulations/2': () =>
    ok({ id: 2, regulation_name: '公开募集证券投资基金销售机构监督管理办法', regulation_no: '证监会令第196号', issuer: '中国证监会', domain: 'fund', status: 'effective', publish_date: '2026-08-20', effective_date: '2026-09-20' }),
  'GET /api/v1/regulations/1/articles': () =>
    ok({
      items: [
        { id: 1, article_no: '第六条', chapter_no: '第二章', section_no: '', content: '金融机构开展网络营销应当建立健全内部审批流程，确保宣传内容真实、准确、可追溯。', vector_id: 'vec_001' },
        { id: 2, article_no: '第十二条', chapter_no: '第三章', section_no: '', content: '不得利用宣传材料承诺保本保收益或者暗示收益区间。', vector_id: 'vec_002' },
      ],
      total: 42,
    }),
  'POST /api/v1/regulations/search': () =>
    ok({
      results: [
        { article_id: 2, regulation_name: '关于加强金融产品网络营销管理的通知', article_no: '第十二条', content: '不得利用宣传材料承诺保本保收益或者暗示收益区间。', highlight: '不得利用宣传材料<em>承诺保本保收益</em>或者暗示收益区间。', status: 'effective', score: 0.923 },
        { article_id: 5, regulation_name: '公开募集证券投资基金销售机构监督管理办法', article_no: '第二十四条', content: '禁止预测基金投资业绩或者承诺收益。', highlight: '禁止预测基金投资业绩或者<em>承诺收益</em>。', status: 'effective', score: 0.887 },
      ],
      total: 2,
    }),
  'GET /api/v1/rules': () =>
    ok({
      items: [
        { id: 1, rule_name: '承诺保本保收益', domain: 'banking', rule_type: 'regex', severity: 'high', status: 'active', is_active: 1, version: 3 },
        { id: 2, rule_name: '夸大过往业绩', domain: 'fund', rule_type: 'keyword', severity: 'high', status: 'active', is_active: 1, version: 1 },
        { id: 3, rule_name: '暗示收益区间（挖掘）', domain: 'fund', rule_type: 'regex', severity: 'medium', status: 'draft', is_active: 0, version: 1 },
      ],
      total: 82,
    }),
  'GET /api/v1/graph/stats': () =>
    ok({ available: true, nodes: { Regulation: 48, Article: 809, ViolationPattern: 130, PenaltyCase: 68 } }),
  'POST /api/v1/graph/query': () =>
    ok({
      patterns: [
        { pattern_name: '承诺保本保收益', domain: 'banking', severity: 'high', similarity: 0.94 },
        { pattern_name: '暗示收益区间', domain: 'fund', severity: 'medium', similarity: 0.81 },
      ],
      regulations: [
        { regulation_id: 1, regulation_name: '关于加强金融产品网络营销管理的通知', article_nos: ['第十二条'] },
        { regulation_id: 2, regulation_name: '公开募集证券投资基金销售机构监督管理办法', article_nos: ['第二十四条', '第三十一条'] },
      ],
      cases: [
        { case_name: '某银行理财违规承诺收益被罚', penalty_org: '金监总局', penalty_date: '2026-07-15', similarity: 0.87 },
      ],
    }),
  'POST /api/v1/graph/cases/recommend': () =>
    ok({
      cases: [
        { case_name: '某基金公司夸大业绩宣传被罚', penalty_org: '证监会', penalty_date: '2026-06-02', similarity: 0.83 },
      ],
    }),
  'GET /api/v1/users': () =>
    ok({
      items: [
        { id: 1, username: 'admin', role: 'admin', department: '合规部', status: 1, created_at: '2026-07-01 09:00:00' },
        { id: 2, username: 'wangmin', role: 'reviewer', department: '基金销售部', status: 1, created_at: '2026-07-12 09:00:00' },
        { id: 3, username: 'lqiang', role: 'viewer', department: '保险部', status: 0, created_at: '2026-08-01 09:00:00' },
      ],
      total: 3,
    }),
  'GET /api/v1/results/feedback-stats': () =>
    ok({
      by_source: {
        rule: { confirmed: 120, false_positive: 4, pending_confirm: 8, confirm_rate: 0.967, false_positive_rate: 0.032 },
        llm: { confirmed: 42, false_positive: 11, pending_confirm: 15, confirm_rate: 0.792, false_positive_rate: 0.208 },
        hybrid: { confirmed: 66, false_positive: 1, pending_confirm: 3, confirm_rate: 0.985, false_positive_rate: 0.015 },
      },
      totals: { confirmed: 228, false_positive: 16, pending_confirm: 26 },
      overall_false_positive_rate: 0.066,
    }),
  'GET /api/v1/results/rules/quality': () =>
    ok({
      total: 3,
      items: [
        { rule_id: 2, rule_name: '夸大过往业绩', hits: 53, confirmed: 42, false_positive: 11, pending_confirm: 0, confirm_rate: 0.792, false_positive_rate: 0.208 },
        { rule_id: 1, rule_name: '承诺保本保收益', hits: 124, confirmed: 120, false_positive: 4, pending_confirm: 0, confirm_rate: 0.967, false_positive_rate: 0.032 },
      ],
    }),
  'GET /api/v1/results/rules/suggestions': () =>
    ok({
      total: 1,
      items: [
        { rule_id: 2, rule_name: '夸大过往业绩', domain: 'fund', severity: 'high', action: 'remove_keyword', keyword: '可期', reason: '关键词「可期」贡献 6 条误报', confirmed: 42, false_positive: 11, fp_rate: 0.208, fp_samples: ['未来可期', '前景可期'] },
      ],
    }),
}

function readJsonBody(req) {
  return new Promise((resolve) => {
    const chunks = []
    req.on('data', (c) => chunks.push(c))
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf-8')
      if (!raw) return resolve(undefined)
      try {
        resolve(JSON.parse(raw))
      } catch {
        resolve(undefined)
      }
    })
    req.on('error', () => resolve(undefined))
  })
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost')
  const key = `${req.method} ${url.pathname}`
  let handler = routes[key]
  if (!handler) {
    // 详情类接口按前缀匹配：/tasks/1/report → 优先精确 key，再找最长前缀
    for (const k of Object.keys(routes)) {
      const [method, path] = [k.slice(0, k.indexOf(' ')), k.slice(k.indexOf(' ') + 1)]
      if (req.method === method && url.pathname.startsWith(path + '/')) {
        handler = routes[k]
        break
      }
    }
  }
  console.log(new Date().toISOString(), key, handler ? '' : '(fallback)')
  res.setHeader('Content-Type', 'application/json')
  res.statusCode = 200
  try {
    const body = req.method === 'POST' || req.method === 'PUT' ? await readJsonBody(req) : undefined
    res.end(handler ? handler(url.searchParams, body) : ok({ items: [], total: 0 }))
  } catch (err) {
    console.error('handler error', key, err)
    res.end(ok({ items: [], total: 0 }))
  }
})

const PORT = Number(process.env.MOCK_PORT) || 8000
server.listen(PORT, '127.0.0.1', () => console.log(`mock api on http://127.0.0.1:${PORT}`))
