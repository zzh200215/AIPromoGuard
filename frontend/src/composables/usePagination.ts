/** 分页状态封装：统一 page/page_size/total。 */
import { computed, ref } from 'vue'

export function usePagination(defaultPageSize = 20) {
  const page = ref(1)
  const pageSize = ref(defaultPageSize)
  const total = ref(0)

  const params = computed(() => ({ page: page.value, page_size: pageSize.value }))

  function reset() {
    page.value = 1
  }

  return { page, pageSize, total, params, reset }
}
