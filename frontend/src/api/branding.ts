import { request } from '@/api/request'
import type {
  Announcement,
  AnnouncementPayload,
  Branding,
  BrandingUpdate,
} from '@/types/branding'

export const brandingApi = {
  publicBranding(): Promise<Branding> {
    return request<Branding>({ url: '/branding' })
  },

  adminBranding(): Promise<Branding> {
    return request<Branding>({ url: '/branding/admin' })
  },

  updateBranding(payload: BrandingUpdate): Promise<Branding> {
    return request<Branding>({ url: '/branding/admin', method: 'put', data: payload })
  },

  uploadImage(kind: 'logo' | 'background', file: File): Promise<Branding> {
    const data = new FormData()
    data.append('file', file)
    return request<Branding>({
      url: `/branding/admin/images/${kind}`,
      method: 'post',
      data,
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },

  deleteImage(kind: 'logo' | 'background'): Promise<Branding> {
    return request<Branding>({ url: `/branding/admin/images/${kind}`, method: 'delete' })
  },

  activeAnnouncements(): Promise<Announcement[]> {
    return request<Announcement[]>({ url: '/branding/announcements' })
  },

  listAnnouncements(): Promise<Announcement[]> {
    return request<Announcement[]>({ url: '/branding/admin/announcements' })
  },

  createAnnouncement(payload: AnnouncementPayload): Promise<Announcement> {
    return request<Announcement>({
      url: '/branding/admin/announcements',
      method: 'post',
      data: payload,
    })
  },

  updateAnnouncement(id: number, payload: AnnouncementPayload): Promise<Announcement> {
    return request<Announcement>({
      url: `/branding/admin/announcements/${id}`,
      method: 'put',
      data: payload,
    })
  },

  deleteAnnouncement(id: number): Promise<null> {
    return request<null>({ url: `/branding/admin/announcements/${id}`, method: 'delete' })
  },
}
