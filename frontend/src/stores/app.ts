import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

type ThemeMode = 'light' | 'dark'
export type ThemePrimary = 'blue' | 'teal' | 'violet' | 'white'

const THEME_KEY = 'itam_theme'
const PRIMARY_KEY = 'itam_primary'
const LEGACY_PALETTE_KEY = 'itam_palette'
const SIDEBAR_KEY = 'itam_sidebar_collapsed'
const MOTION_KEY = 'itam_animations'

const THEME_COLORS: Record<ThemePrimary, string> = {
  blue: '#111823',
  teal: '#121d1b',
  violet: '#171425',
  white: '#151a22',
}

function storedTheme(): ThemeMode {
  return localStorage.getItem(THEME_KEY) === 'dark' ? 'dark' : 'light'
}

function storedPrimary(): ThemePrimary {
  const value = localStorage.getItem(PRIMARY_KEY)
  if (value === 'teal' || value === 'violet' || value === 'blue' || value === 'white') return value
  const legacy = localStorage.getItem(LEGACY_PALETTE_KEY)
  if (legacy === 'jade') return 'teal'
  return 'blue'
}

export const useAppStore = defineStore('app', () => {
  const theme = ref<ThemeMode>(storedTheme())
  const primary = ref<ThemePrimary>(storedPrimary())
  const sidebarCollapsed = ref(localStorage.getItem(SIDEBAR_KEY) === '1')
  const animationsEnabled = ref(localStorage.getItem(MOTION_KEY) !== 'off')

  const isDark = computed(() => theme.value === 'dark')

  function applyTheme(): void {
    const root = document.documentElement
    root.classList.toggle('dark', theme.value === 'dark')
    root.dataset.primary = primary.value
    localStorage.setItem(THEME_KEY, theme.value)
    localStorage.setItem(PRIMARY_KEY, primary.value)
    const meta = document.querySelector('meta[name="theme-color"]')
    meta?.setAttribute('content', THEME_COLORS[primary.value])
  }

  function applyMotion(): void {
    document.documentElement.classList.toggle('no-animation', !animationsEnabled.value)
    localStorage.setItem(MOTION_KEY, animationsEnabled.value ? 'on' : 'off')
  }

  function setTheme(next: ThemeMode): void {
    theme.value = next
    applyTheme()
  }

  function setPrimary(next: ThemePrimary): void {
    primary.value = next
    applyTheme()
  }

  function resetTheme(): void {
    theme.value = 'light'
    primary.value = 'blue'
    applyTheme()
  }

  function toggleTheme(): void {
    setTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  function toggleAnimations(): void {
    animationsEnabled.value = !animationsEnabled.value
    applyMotion()
  }

  function setSidebarCollapsed(collapsed: boolean): void {
    sidebarCollapsed.value = collapsed
    localStorage.setItem(SIDEBAR_KEY, collapsed ? '1' : '0')
  }

  function toggleSidebar(): void {
    setSidebarCollapsed(!sidebarCollapsed.value)
  }

  return {
    theme,
    primary,
    isDark,
    sidebarCollapsed,
    animationsEnabled,
    applyTheme,
    applyMotion,
    setTheme,
    setPrimary,
    resetTheme,
    toggleTheme,
    toggleAnimations,
    setSidebarCollapsed,
    toggleSidebar,
  }
})
