import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './router/guards'
// ⚠️ 顺序敏感：EP 官方暗色变量集必须先于项目样式注入。
// 两者选择器同为 html.dark（特异性相同），后注入者胜出——
// styles/index.scss 里的品牌色暗色覆写依赖此顺序，调换会让校准静默失效。
import 'element-plus/theme-chalk/dark/css-vars.css'
import './styles/index.scss'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.mount('#app')
