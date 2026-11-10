export interface Branding {
  site_name: string
  site_subtitle: string
  brand_mark_text: string
  login_footer_text: string
  dashboard_welcome: string
  logo_url: string
  background_url: string
  updated_at: string | null
}

export type BrandingUpdate = Omit<Branding, 'logo_url' | 'background_url' | 'updated_at'>

export type AnnouncementLevel = 'INFO' | 'IMPORTANT' | 'WARNING'

export interface Announcement {
  id: number
  title: string
  content: string
  level: AnnouncementLevel
  level_label: string
  is_active: boolean
  start_at: string | null
  end_at: string | null
  sort: number
  created_by_name: string | null
  created_at: string
  updated_at: string
}

export interface AnnouncementPayload {
  title: string
  content: string
  level: AnnouncementLevel
  is_active: boolean
  start_at: string | null
  end_at: string | null
  sort: number
}
