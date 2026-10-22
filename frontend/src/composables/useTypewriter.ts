/**
 * 打字机（伪流式）通用逻辑：拿到全文后逐字呈现，营造"AI 在说话"的体感。
 *
 * - start(full)：逐字打字（自动清理上一个定时器；空文本直接结束）
 * - set(full)：直接显示（回看/缓存场景不打字）
 * - typing：是否正在打字（供光标闪烁等消费）
 * - 组件卸载自动清理定时器
 */
import { onBeforeUnmount, ref } from 'vue'

export function useTypewriter(options?: { step?: number; intervalMs?: number }) {
  const step = options?.step ?? 3
  const intervalMs = options?.intervalMs ?? 24
  const text = ref('')
  const typing = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null

  function stop() {
    if (timer != null) {
      clearInterval(timer)
      timer = null
    }
    typing.value = false
  }

  function start(full: string) {
    stop()
    text.value = ''
    if (!full) return
    let i = 0
    typing.value = true
    timer = setInterval(() => {
      i = Math.min(full.length, i + step)
      text.value = full.slice(0, i)
      if (i >= full.length) stop()
    }, intervalMs)
  }

  function set(full: string) {
    stop()
    text.value = full
  }

  onBeforeUnmount(stop)

  return { text, typing, start, set, stop }
}
