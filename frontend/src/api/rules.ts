/** 规则 CRUD 接口。 */
import { request } from './request'
import type { Page, PaginationParams } from '@/types/api'
import type { Rule, RuleCreate, RuleUpdate } from '@/types/rule'

export const listRules = (
  params: PaginationParams & { domain?: string; is_active?: boolean },
) => request<Page<Rule>>({ url: '/rules', method: 'get', params })

export const createRule = (body: RuleCreate) =>
  request<Rule>({ url: '/rules', method: 'post', data: body })

export const getRule = (id: number) => request<Rule>({ url: `/rules/${id}`, method: 'get' })

export const updateRule = (id: number, body: RuleUpdate) =>
  request<Rule>({ url: `/rules/${id}`, method: 'put', data: body })

export const deleteRule = (id: number) =>
  request<{ deleted: number }>({ url: `/rules/${id}`, method: 'delete' })

export const draftRuleVersion = (id: number) =>
  request<Rule>({ url: `/rules/${id}/versions`, method: 'post' })

export const publishRule = (id: number) =>
  request<{ rule: Rule; superseded_rule_ids: number[] }>({
    url: `/rules/${id}/publish`,
    method: 'post',
  })
