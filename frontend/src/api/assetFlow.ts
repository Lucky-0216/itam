import { request } from '@/api/request'
import type {
  ApprovalConfig,
  AssetHistoryItem,
  AssetRequestItem,
  AssetRequestPage,
  AssetRequestSummary,
  AvailableAsset,
  AvailableCategory,
  DirectOutboundCategory,
  DirectOutboundPayload,
  DirectOutboundResult,
  DirectOutboundUser,
  MyAssetItem,
  OutboundPayload,
  RequestCreatePayload,
  ReturnConfirmPayload,
  ReturnCreatePayload,
  ScanAssetResult,
} from '@/types/assetFlow'

interface AvailableAssetPage {
  items: AvailableAsset[]
  total: number
  page: number
  page_size: number
}

interface RequestQuery {
  page: number
  page_size: number
  keyword?: string
  request_type?: string
  status?: string
  pending_mine?: boolean
}

export const assetFlowApi = {
  categoryOptions(parentId?: number): Promise<AvailableCategory[]> {
    return request<AvailableCategory[]>({
      url: '/asset-requests/category-options',
      params: parentId ? { parent_id: parentId } : undefined,
    })
  },

  myRequests(params: RequestQuery): Promise<AssetRequestPage> {
    return request<AssetRequestPage>({ url: '/asset-requests/mine', params })
  },

  reviewRequests(params: RequestQuery): Promise<AssetRequestPage> {
    return request<AssetRequestPage>({ url: '/asset-requests/review', params })
  },

  reviewSummary(): Promise<AssetRequestSummary> {
    return request<AssetRequestSummary>({ url: '/asset-requests/review-summary' })
  },

  approvalConfig(): Promise<ApprovalConfig> {
    return request<ApprovalConfig>({ url: '/asset-requests/approval-config' })
  },

  updateApprovalConfig(payload: {
    dept_approval_required: boolean
    version: number
  }): Promise<ApprovalConfig> {
    return request<ApprovalConfig>({
      url: '/asset-requests/approval-config',
      method: 'put',
      data: payload,
    })
  },

  scan(code: string): Promise<ScanAssetResult> {
    return request<ScanAssetResult>({ url: '/asset-requests/scan', params: { code } })
  },

  createRequest(payload: RequestCreatePayload): Promise<AssetRequestItem> {
    return request<AssetRequestItem>({
      url: '/asset-requests',
      method: 'post',
      data: payload,
    })
  },

  createReturn(payload: ReturnCreatePayload): Promise<AssetRequestItem> {
    return request<AssetRequestItem>({
      url: '/asset-returns',
      method: 'post',
      data: payload,
    })
  },

  myAssets(): Promise<MyAssetItem[]> {
    return request<MyAssetItem[]>({ url: '/my-assets' })
  },

  getRequest(id: number): Promise<AssetRequestItem> {
    return request<AssetRequestItem>({ url: `/asset-requests/${id}` })
  },

  outboundAssets(
    id: number,
    params: { page: number; page_size: number },
  ): Promise<AvailableAssetPage> {
    return request<AvailableAssetPage>({
      url: `/asset-requests/${id}/outbound-assets`,
      params,
    })
  },

  approve(id: number, comment?: string | null): Promise<AssetRequestItem> {
    return request<AssetRequestItem>({
      url: `/asset-requests/${id}/approve`,
      method: 'post',
      data: { comment },
    })
  },

  reject(id: number, comment?: string | null): Promise<AssetRequestItem> {
    return request<AssetRequestItem>({
      url: `/asset-requests/${id}/reject`,
      method: 'post',
      data: { comment },
    })
  },

  cancel(id: number): Promise<AssetRequestItem> {
    return request<AssetRequestItem>({
      url: `/asset-requests/${id}/cancel`,
      method: 'post',
    })
  },

  outbound(id: number, payload: OutboundPayload): Promise<AssetRequestItem> {
    return request<AssetRequestItem>({
      url: `/asset-requests/${id}/outbound`,
      method: 'post',
      data: payload,
    })
  },

  confirmReturn(id: number, payload: ReturnConfirmPayload): Promise<AssetRequestItem> {
    return request<AssetRequestItem>({
      url: `/asset-requests/${id}/return-confirm`,
      method: 'post',
      data: payload,
    })
  },

  assetHistory(assetId: number): Promise<AssetHistoryItem[]> {
    return request<AssetHistoryItem[]>({ url: `/assets/${assetId}/history` })
  },

  directOutboundCategories(): Promise<DirectOutboundCategory[]> {
    return request<DirectOutboundCategory[]>({
      url: '/asset-direct-outbound/categories',
    })
  },

  directOutboundAssets(params: {
    keyword?: string
    category_id?: number
    include_child?: boolean
    page: number
    page_size: number
  }): Promise<AvailableAssetPage> {
    return request<AvailableAssetPage>({
      url: '/asset-direct-outbound/assets',
      params,
    })
  },

  directOutboundUsers(keyword?: string): Promise<DirectOutboundUser[]> {
    return request<DirectOutboundUser[]>({
      url: '/asset-direct-outbound/users',
      params: keyword ? { keyword } : undefined,
    })
  },

  directOutbound(payload: DirectOutboundPayload): Promise<DirectOutboundResult> {
    return request<DirectOutboundResult>({
      url: '/asset-direct-outbound',
      method: 'post',
      data: payload,
    })
  },
}
