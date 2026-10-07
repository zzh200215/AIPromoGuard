<template>
  <div class="login-page">
    <!-- ══ 左：封面（墨黑 · 公报气质）══ -->
    <section class="cover" aria-label="产品介绍">
      <div class="cover-grain" aria-hidden="true" />

      <!-- 文号：公文身份细节（记忆点来源之一） -->
      <header class="cover-head">
        <div class="seal" aria-hidden="true">
          <StampMark />
        </div>
        <div class="cover-id">
          <span class="cover-org">智能合规审查平台</span>
          <span class="cover-doc-no">金审字〔2026〕第 001 号</span>
        </div>
      </header>

      <div class="cover-body">
        <h1 class="cover-title">
          <span class="line">让每一句承诺</span>
          <span class="line">都有据<span class="accent">可依</span></span>
        </h1>

        <p class="cover-desc">
          面向银行理财、基金销售、保险产品的合规审查工作台。上传材料，
          双引擎定位违规，给出法规依据与修改建议，人工复核后形成整改闭环。
        </p>

        <div class="cover-rule" aria-hidden="true" />

        <!-- 审查维度：公报目录式编号清单 -->
        <ol class="dim-list">
          <li v-for="(f, i) in FEATURES" :key="f.title" class="dim-item">
            <span class="dim-no">{{ String(i + 1).padStart(2, '0') }}</span>
            <span class="dim-title">{{ f.title }}</span>
            <span class="dim-sub">{{ f.sub }}</span>
          </li>
        </ol>
      </div>

      <footer class="cover-foot">
        <span>双引擎：规则 + 大模型</span>
        <span class="dot" aria-hidden="true">·</span>
        <span>结论可溯源</span>
        <span class="dot" aria-hidden="true">·</span>
        <span>全链路留痕</span>
      </footer>
    </section>

    <!-- ══ 右：内页（纸白 · 登录）══ -->
    <section class="sheet" aria-label="登录">
      <div class="sheet-grain" aria-hidden="true" />

      <div class="form-box">
        <p class="form-eyebrow">Sign in · 登录</p>
        <h2 class="form-title">进入审查台</h2>
        <p class="form-sub">使用机构分配的账号继续</p>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          size="large"
          class="login-form"
          @keyup.enter="onSubmit"
        >
          <el-form-item prop="username">
            <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" clearable />
          </el-form-item>
          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="密码"
              :prefix-icon="Lock"
              show-password
            />
          </el-form-item>
          <el-button
            type="primary"
            size="large"
            class="login-btn"
            :loading="loading"
            @click="onSubmit"
          >
            登 录
          </el-button>
        </el-form>

        <p class="form-note">
          <span class="note-line" aria-hidden="true" />
          操作全程留痕，供监管检查回溯
        </p>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { h, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Lock, User } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

/** 印章式品牌标记：外方内圆（篆刻印面结构），纯 SVG 无外部资源 */
const StampMark = () =>
  h('svg', { viewBox: '0 0 40 40', width: 34, height: 34, 'aria-hidden': 'true' }, [
    h('rect', {
      x: 2.5,
      y: 2.5,
      width: 35,
      height: 35,
      rx: 3,
      fill: 'none',
      stroke: 'currentColor',
      'stroke-width': 2,
      'stroke-dasharray': '3 2.4',
      opacity: 0.55,
    }),
    h('path', {
      d: 'M20 8.5 L28 20 L20 31.5 L12 20 Z',
      fill: 'currentColor',
      opacity: 0.9,
    }),
    h('circle', { cx: 20, cy: 20, r: 3.2, fill: 'var(--cover-bg, #14110d)' }),
  ])

/** 五个审查维度（与 README 核心层一致）——公报目录式呈现，不再用彩色圆点 */
const FEATURES = [
  { title: '禁止性表述', sub: '保本保收益、承诺收益等字面红线' },
  { title: '限制性表述', sub: '换一种说法的语义违规识别' },
  { title: '披露完整性', sub: '风险提示与披露要素是否齐全' },
  { title: '适当性匹配', sub: '产品风险等级与客群匹配校验' },
  { title: '证据核验', sub: '引用幻觉拦截，结论可溯源' },
]

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const formRef = ref<FormInstance>()
const form = reactive({ username: '', password: '' })
const loading = ref(false)

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function onSubmit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await auth.login(form)
    ElMessage.success('登录成功')
    const redirect = (route.query.redirect as string) || '/'
    router.push(redirect)
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}
</script>

<style scoped lang="scss">
/* ═══════════════════════════════════════════════════════════
   Editorial 方向：墨黑封面 + 纸白内页 + 金铜强调
   纸感暖调、宋体系大标题、发丝规则线、编号目录
   ═══════════════════════════════════════════════════════════ */

.login-page {
  --cover-bg: #14110d; /* 暖调近黑：印刷油墨感 */
  --cover-text: #f3eee3; /* 暖调近白：纸张感 */
  --cover-muted: rgba(243, 238, 227, 0.52);
  --cover-line: rgba(243, 238, 227, 0.16);
  --accent: #c8963c; /* 金铜：印刷烫金，全页唯一强调色（= 全局 --app-accent） */
  --accent-deep: #a8761f; /* 金铜深调：需达对比度的场景（输入框焦点环 3.92:1） */
  --sheet-bg: #fffdf9; /* 纸白（= 全局 --app-surface，全站统一定义） */
  --sheet-text: #1d1913;
  --sheet-muted: #6f6759;
  --sheet-line: rgba(29, 25, 19, 0.12);

  height: 100%;
  display: flex;
  background: var(--sheet-bg);
  color: var(--sheet-text);
}

/* ── 左：封面 ─────────────────────────────────────────── */
.cover {
  position: relative;
  flex: 1.25;
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 44px 56px 36px;
  background: var(--cover-bg);
  color: var(--cover-text);
  overflow: hidden;

  /* 装饰规则线：竖向发丝线冲出画布（破格元素） */
  &::after {
    content: '';
    position: absolute;
    top: -15%;
    right: 76px;
    width: 1px;
    height: 130%;
    background: linear-gradient(
      180deg,
      transparent,
      var(--cover-line) 18%,
      var(--cover-line) 82%,
      transparent
    );
    pointer-events: none;
  }
}

/* 纸张颗粒：SVG feTurbulence 噪点叠加（氛围层） */
.cover-grain,
.sheet-grain {
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.05;
  mix-blend-mode: overlay;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}

.cover-head {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 14px;
  animation: rise 640ms var(--ease-out, cubic-bezier(0.16, 1, 0.3, 1)) both;
}

.seal {
  color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.cover-id {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.cover-org {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.14em;
}

.cover-doc-no {
  font-family: 'JetBrains Mono', 'IBM Plex Mono', Consolas, monospace;
  font-size: 11px;
  letter-spacing: 0.08em;
  color: var(--cover-muted);
}

.cover-body {
  position: relative;
  z-index: 1;
  max-width: 560px;
}

/* 宋体系大标题：权威文书感（拉丁衬线兜底数字与英文） */
.cover-title {
  margin: 0 0 22px;
  font-family: 'Noto Serif SC', 'Source Han Serif SC', 'Songti SC', 'STSong', 'SimSun', Georgia, serif;
  font-size: clamp(40px, 4.6vw, 60px);
  font-weight: 700;
  line-height: 1.18;
  letter-spacing: 0.02em; /* 中文大标题正字距 */

  .line {
    display: block;
    animation: rise 700ms var(--ease-out, cubic-bezier(0.16, 1, 0.3, 1)) both;
  }

  .line + .line {
    animation-delay: 90ms;
  }

  .accent {
    color: var(--accent);
    position: relative;
  }

  /* 金铜强调下划：印章钤记式的短横线 */
  .accent::after {
    content: '';
    position: absolute;
    left: 0.06em;
    right: 0.06em;
    bottom: 0.08em;
    height: 3px;
    background: var(--accent);
    opacity: 0.4;
  }
}

.cover-desc {
  margin: 0 0 30px;
  max-width: 460px;
  font-size: 14px;
  line-height: 1.9;
  letter-spacing: 0.02em;
  color: var(--cover-muted);
  animation: rise 700ms var(--ease-out, cubic-bezier(0.16, 1, 0.3, 1)) 180ms both;
}

.cover-rule {
  height: 1px;
  margin: 0 0 26px;
  background: linear-gradient(90deg, var(--accent) 0 42px, var(--cover-line) 42px);
  animation: rise 700ms var(--ease-out, cubic-bezier(0.16, 1, 0.3, 1)) 240ms both;
}

/* ── 编号目录：维度清单 ───────────────────────────────── */
.dim-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
}

.dim-item {
  display: grid;
  grid-template-columns: 44px 108px 1fr;
  align-items: baseline;
  gap: 0 14px;
  padding: 11px 0;
  border-bottom: 1px solid var(--cover-line);
  animation: rise 640ms var(--ease-out, cubic-bezier(0.16, 1, 0.3, 1)) both;

  &:first-child {
    border-top: 1px solid var(--cover-line);
  }

  /* 错峰入场：5 条目录逐行揭示 */
  @for $i from 1 through 5 {
    &:nth-child(#{$i}) {
      animation-delay: #{280 + ($i - 1) * 70}ms;
    }
  }
}

.dim-no {
  font-family: 'JetBrains Mono', 'IBM Plex Mono', Consolas, monospace;
  font-size: 12px;
  letter-spacing: 0.06em;
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}

.dim-title {
  font-family: 'Noto Serif SC', 'Source Han Serif SC', 'Songti SC', 'STSong', 'SimSun', Georgia, serif;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.06em;
}

.dim-sub {
  font-size: 13px;
  line-height: 1.6;
  color: var(--cover-muted);
}

.cover-foot {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  letter-spacing: 0.1em;
  color: var(--cover-muted);
  animation: rise 640ms var(--ease-out, cubic-bezier(0.16, 1, 0.3, 1)) 640ms both;

  .dot {
    color: var(--accent);
    opacity: 0.7;
  }
}

/* ── 右：内页（登录）─────────────────────────────────── */
.sheet {
  position: relative;
  flex: 1;
  min-width: 420px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px;
  background: var(--sheet-bg);

  /* 登录页是**固定的纸墨语言**（品牌页，不随主题切换）：
     此处局部锁死 EP 文本/语义变量——否则 html.dark 会覆盖 :root 的
     --el-text-color-*，暗色用户会在纸白底上看到浅灰字（不可读）。
     各值均按纸白/输入底实测达标（见交付自检）。 */
  --el-text-color-primary: #1d1913;
  --el-text-color-regular: #2a251d; /* 输入文字 */
  --el-text-color-placeholder: #7d7466; /* 对输入底 4.53:1 */
  --el-text-color-secondary: #6f6759;
  --el-color-danger: #b3261e; /* 错误提示：深红，纸白底上达标 */
  --el-border-color: rgba(29, 25, 19, 0.5);

  /* 内页左侧装订线：与封面交接处的一根发丝线 */
  &::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    width: 1px;
    height: 100%;
    background: linear-gradient(180deg, transparent, var(--sheet-line) 20%, var(--sheet-line) 80%, transparent);
  }
}

.form-box {
  width: 356px;
  position: relative;
  z-index: 1;
  animation: rise 720ms var(--ease-out, cubic-bezier(0.16, 1, 0.3, 1)) 120ms both;
}

.form-eyebrow {
  margin: 0 0 14px;
  font-family: 'JetBrains Mono', 'IBM Plex Mono', Consolas, monospace;
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--sheet-muted);
}

.form-title {
  margin: 0 0 8px;
  font-family: 'Noto Serif SC', 'Source Han Serif SC', 'Songti SC', 'STSong', 'SimSun', Georgia, serif;
  font-size: 30px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--sheet-text);
}

.form-sub {
  margin: 0 0 34px;
  font-size: 13px;
  letter-spacing: 0.02em;
  color: var(--sheet-muted);
}

/* Element Plus 输入框：方角、发丝线、聚焦转金铜 */
.login-form {
  :deep(.el-form-item) {
    margin-bottom: 20px;
  }

  :deep(.el-input__wrapper) {
    border-radius: 2px;
    /* 常态边框 rgba(29,25,19,.5)：对纸白 3.09:1，满足控件边界 ≥3:1 */
    box-shadow: 0 0 0 1px rgba(29, 25, 19, 0.5) inset;
    background: #fffdf9;
    padding: 4px 14px;
    transition: box-shadow 180ms ease-out;

    &:hover {
      box-shadow: 0 0 0 1px rgba(29, 25, 19, 0.64) inset;
    }

    &.is-focus {
      /* 深调金铜 1.5px：对输入底 3.92:1，达标且保留品牌色相 */
      box-shadow: 0 0 0 1.5px var(--accent-deep) inset;
    }
  }

  :deep(.el-input__inner) {
    letter-spacing: 0.02em;
  }
}

/* 主按钮：墨黑底、金铜描边、悬停擦除式反馈 */
.login-btn {
  width: 100%;
  margin-top: 10px;
  height: 46px !important;
  border-radius: 2px !important;
  border: 1px solid var(--cover-bg) !important;
  background: var(--cover-bg) !important;
  color: var(--cover-text) !important;
  font-size: 15px !important;
  letter-spacing: 0.42em !important;
  text-indent: 0.42em;
  transition:
    background 180ms ease-out,
    color 180ms ease-out,
    box-shadow 180ms ease-out;

  &:hover:not(.is-loading) {
    background: var(--accent) !important;
    border-color: var(--accent) !important;
    color: #16130f !important;
    box-shadow: 0 6px 18px rgba(200, 150, 60, 0.32);
  }

  &:active:not(.is-loading) {
    transform: translateY(1px);
  }
}

.form-note {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 30px 0 0;
  font-size: 12px;
  letter-spacing: 0.04em;
  color: var(--sheet-muted);

  .note-line {
    width: 26px;
    height: 1px;
    background: var(--sheet-line);
    flex-shrink: 0;
  }
}

/* ── 入场与降级 ─────────────────────────────────────── */
@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(18px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .cover-head,
  .cover-title .line,
  .cover-desc,
  .cover-rule,
  .dim-item,
  .cover-foot,
  .form-box {
    animation: none !important;
  }
}

/* ── 响应式：窄屏收敛为单栏（封面转顶部精简版）─────── */
@media (max-width: 960px) {
  .login-page {
    flex-direction: column;
  }

  .cover {
    flex: none;
    padding: 28px 28px 24px;

    &::after {
      display: none;
    }
  }

  .cover-title {
    font-size: 32px;
  }

  .cover-desc,
  .dim-list,
  .cover-rule {
    display: none;
  }

  .cover-foot {
    margin-top: 18px;
  }

  .sheet {
    flex: 1;
    min-width: 0;
    padding: 40px 28px;

    &::before {
      top: 0;
      left: 0;
      width: 100%;
      height: 1px;
      background: var(--sheet-line);
    }
  }
}
</style>
