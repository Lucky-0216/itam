import { defineStore } from 'pinia'

import { brandingApi } from '@/api/branding'
import type { Announcement, Branding } from '@/types/branding'

export function defaultBranding(): Branding {
  return {
    site_name: 'ITAM',
    site_subtitle: 'IT ASSET CONTROL',
    brand_mark_text: 'IT',
    login_footer_text: 'ITAM · IT 资产管理系统',
    dashboard_welcome: '',
    logo_url: '',
    background_url: '',
    updated_at: null,
  }
}

let loadPromise: Promise<void> | null = null

export const useBrandingStore = defineStore('branding', {
  state: () => ({
    branding: defaultBranding(),
    announcements: [] as Announcement[],
    loaded: false,
    loading: false,
  }),
  actions: {
    async load(force = false): Promise<void> {
      if (!force && (this.loaded || loadPromise)) {
        await loadPromise
        return
      }
      this.loading = true
      loadPromise = (async () => {
        try {
          this.branding = await brandingApi.publicBranding()
        } catch {
          this.branding = defaultBranding()
        } finally {
          this.loaded = true
          this.loading = false
        }
      })()
      try {
        await loadPromise
      } finally {
        loadPromise = null
      }
    },

    apply(next: Branding): void {
      this.branding = next
      this.loaded = true
    },

    async loadAnnouncements(): Promise<void> {
      try {
        this.announcements = await brandingApi.activeAnnouncements()
      } catch {
        this.announcements = []
      }
    },
  },
})
