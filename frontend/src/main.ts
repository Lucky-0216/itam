import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import '@/styles/index.css'

import App from './App.vue'
import router from './router'
import { pinia } from './stores'
import { useAppStore } from './stores/app'
import { useBrandingStore } from './stores/branding'
import { permissionDirective } from './directives/permission'

const app = createApp(App)

for (const [name, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(name, component)
}

app.use(pinia)
app.use(ElementPlus, { locale: zhCn })
app.use(router)
app.directive('perm', permissionDirective)

const appStore = useAppStore(pinia)
appStore.applyTheme()
appStore.applyMotion()
void useBrandingStore(pinia).load()

app.mount('#app')
