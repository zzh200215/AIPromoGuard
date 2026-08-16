/**
 * axios 实例与统一拦截。
 * 成功剥壳：code===0 → 返回 data；code!==0 → 提示并 reject。
 * 401 → 登出跳登录（带 redirect）；403 → 跳 /403。
 * 下载流（responseType blob）直接放行完整 response。
 */
import axios, { type AxiosRequestConfig, type AxiosResponse } from 'axios'
import { useAuthStore } from '@/stores/auth'

const service = axios.create({
  baseURL: '/api/v1',
  timeout: 60_000,
})

service.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

service.interceptors.response.use(
  (response: AxiosResponse) => {
    // 文件流直接放行，由调用方处理 Blob + 文件名
    if (response.config.responseType === 'blob') {
      return response
    }
    const body = response.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 0) {
        return body.data
      }
      ElMessage.error(body.message || '请求失败')
      return Promise.reject(new Error(body.message || '请求失败'))
    }
    return body
  },
  (error) => {
    const status: number | undefined = error.response?.status
    const data = error.response?.data
    if (status === 401) {
      useAuthStore().logout()
      // 动态 import 避免与 router 循环依赖
      import('@/router').then(({ default: router }) => {
        router.push({
          path: '/login',
          query: { redirect: router.currentRoute.value.fullPath },
        })
      })
    } else if (status === 403) {
      ElMessage.error(data?.message || '无权限执行该操作')
      import('@/router').then(({ default: router }) => {
        if (router.currentRoute.value.path !== '/403') router.push('/403')
      })
    } else {
      ElMessage.error(data?.message || error.message || '网络错误')
    }
    return Promise.reject(error)
  },
)

export function request<T>(config: AxiosRequestConfig): Promise<T> {
  return service.request(config) as Promise<T>
}
