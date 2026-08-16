/** 法规/条款 CRUD 与检索接口。 */
import { request } from './request'
import type { Page, PaginationParams } from '@/types/api'
import type {
  Article,
  ArticleCreate,
  ArticleUpdate,
  Regulation,
  RegulationCreate,
  RegulationSearchHit,
  RegulationSearchRequest,
  RegulationUpdate,
} from '@/types/regulation'

export const listRegulations = (
  params: PaginationParams & { domain?: string; keyword?: string },
) => request<Page<Regulation>>({ url: '/regulations', method: 'get', params })

export const createRegulation = (body: RegulationCreate) =>
  request<Regulation>({ url: '/regulations', method: 'post', data: body })

export const getRegulation = (id: number) =>
  request<Regulation>({ url: `/regulations/${id}`, method: 'get' })

export const updateRegulation = (id: number, body: RegulationUpdate) =>
  request<Regulation>({ url: `/regulations/${id}`, method: 'put', data: body })

export const deleteRegulation = (id: number) =>
  request<{ deleted: number }>({ url: `/regulations/${id}`, method: 'delete' })

export const searchRegulations = (body: RegulationSearchRequest) =>
  request<{ total: number; results: RegulationSearchHit[] }>({
    url: '/regulations/search',
    method: 'post',
    data: body,
  })

/** 条款：挂在 /regulations prefix 下，注意路径不是 /articles */
export const listArticles = (regulationId: number, params: PaginationParams = {}) =>
  request<Page<Article>>({
    url: `/regulations/${regulationId}/articles`,
    method: 'get',
    params: { page: params.page ?? 1, page_size: params.page_size ?? 50 },
  })

export const createArticle = (regulationId: number, body: ArticleCreate) =>
  request<Article>({ url: `/regulations/${regulationId}/articles`, method: 'post', data: body })

export const updateArticle = (articleId: number, body: ArticleUpdate) =>
  request<Article>({ url: `/regulations/articles/${articleId}`, method: 'put', data: body })

export const deleteArticle = (articleId: number) =>
  request<{ deleted: number }>({ url: `/regulations/articles/${articleId}`, method: 'delete' })
