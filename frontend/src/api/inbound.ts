import { request } from '@/api/request'
import type {
  Inbound,
  InboundCategoryOption,
  InboundCodePreview,
  InboundCreatePayload,
  InboundDeptOption,
  InboundModelOption,
  InboundPage,
  InboundReversePayload,
  InboundStatus,
  InboundType,
  InboundUpdatePayload,
  StockAssetPage,
  StockCategoryOption,
  StockOverview,
} from '@/types/inbound'

interface InboundListQuery {
  page: number
  page_size: number
  keyword?: string
  status?: InboundStatus
  inbound_type?: InboundType
}

interface StockItemQuery {
  page: number
  page_size: number
  keyword?: string
  category_id?: number
  include_child?: boolean
  location?: string
}

export const inboundApi = {
  departments(): Promise<InboundDeptOption[]> {
    return request<InboundDeptOption[]>({ url: '/inbounds/options/departments' })
  },

  categories(): Promise<InboundCategoryOption[]> {
    return request<InboundCategoryOption[]>({ url: '/inbounds/options/categories' })
  },

  models(categoryId?: number): Promise<InboundModelOption[]> {
    return request<InboundModelOption[]>({
      url: '/inbounds/options/models',
      params: categoryId ? { category_id: categoryId } : undefined,
    })
  },

  list(params: InboundListQuery): Promise<InboundPage> {
    return request<InboundPage>({ url: '/inbounds', params })
  },

  create(payload: InboundCreatePayload): Promise<Inbound> {
    return request<Inbound>({ url: '/inbounds', method: 'post', data: payload })
  },

  update(id: number, payload: InboundUpdatePayload): Promise<Inbound> {
    return request<Inbound>({ url: `/inbounds/${id}`, method: 'put', data: payload })
  },

  reverseAssets(id: number, payload: InboundReversePayload): Promise<Inbound> {
    return request<Inbound>({
      url: `/inbounds/${id}/reverse-assets`,
      method: 'post',
      data: payload,
    })
  },

  previewCodes(baseNo: string, quantity: number): Promise<InboundCodePreview> {
    return request<InboundCodePreview>({
      url: '/inbounds/options/next-codes',
      params: { base_no: baseNo, quantity },
    })
  },

  get(id: number): Promise<Inbound> {
    return request<Inbound>({ url: `/inbounds/${id}` })
  },

  confirm(id: number, version: number, comment?: string | null): Promise<Inbound> {
    return request<Inbound>({
      url: `/inbounds/${id}/confirm`,
      method: 'post',
      data: { version, comment: comment || null },
    })
  },

  cancel(id: number, reason?: string | null): Promise<Inbound> {
    return request<Inbound>({
      url: `/inbounds/${id}/cancel`,
      method: 'post',
      data: { reason: reason || null },
    })
  },

  stockOverview(location?: string): Promise<StockOverview> {
    return request<StockOverview>({
      url: '/stock/overview',
      params: location ? { location } : undefined,
    })
  },

  stockItems(params: StockItemQuery): Promise<StockAssetPage> {
    return request<StockAssetPage>({ url: '/stock/items', params })
  },

  stockCategories(): Promise<StockCategoryOption[]> {
    return request<StockCategoryOption[]>({ url: '/stock/categories' })
  },
}
