import { request } from '@/api/request'
import type {
  AssetAttachment,
  AssetBatchUpdatePayload,
  AssetBatchUpdateResult,
  AssetCategory,
  AssetDeptOption,
  AssetPage,
  AssetPayload,
  AssetQuery,
  AssetStockInPayload,
  AssetTimelineItem,
  AssetUpdatePayload,
  CategoryField,
  CategoryFieldPayload,
  CategoryFieldUpdatePayload,
  CategoryPayload,
  CategoryUpdatePayload,
  CustodianOption,
  ModelPage,
  ModelPayload,
  ModelQuery,
  ModelUpdatePayload,
  AssetModel,
} from '@/types/asset'

export const assetApi = {
  categoryTree(): Promise<AssetCategory[]> {
    return request<AssetCategory[]>({ url: '/asset-categories/tree' })
  },

  createCategory(payload: CategoryPayload): Promise<AssetCategory> {
    return request<AssetCategory>({ url: '/asset-categories', method: 'post', data: payload })
  },

  updateCategory(id: number, payload: CategoryUpdatePayload): Promise<AssetCategory> {
    return request<AssetCategory>({
      url: `/asset-categories/${id}`,
      method: 'put',
      data: payload,
    })
  },

  deleteCategory(id: number): Promise<null> {
    return request<null>({ url: `/asset-categories/${id}`, method: 'delete' })
  },

  createCategoryField(
    categoryId: number,
    payload: CategoryFieldPayload,
  ): Promise<CategoryField> {
    return request<CategoryField>({
      url: `/asset-categories/${categoryId}/fields`,
      method: 'post',
      data: payload,
    })
  },

  updateCategoryField(
    categoryId: number,
    fieldId: number,
    payload: CategoryFieldUpdatePayload,
  ): Promise<CategoryField> {
    return request<CategoryField>({
      url: `/asset-categories/${categoryId}/fields/${fieldId}`,
      method: 'put',
      data: payload,
    })
  },

  deleteCategoryField(categoryId: number, fieldId: number): Promise<null> {
    return request<null>({
      url: `/asset-categories/${categoryId}/fields/${fieldId}`,
      method: 'delete',
    })
  },

  listModels(params: ModelQuery): Promise<ModelPage> {
    return request<ModelPage>({ url: '/asset-models', params })
  },

  createModel(payload: ModelPayload): Promise<AssetModel> {
    return request<AssetModel>({ url: '/asset-models', method: 'post', data: payload })
  },

  updateModel(id: number, payload: ModelUpdatePayload): Promise<AssetModel> {
    return request<AssetModel>({ url: `/asset-models/${id}`, method: 'put', data: payload })
  },

  deleteModel(id: number): Promise<null> {
    return request<null>({ url: `/asset-models/${id}`, method: 'delete' })
  },

  listAssets(params: AssetQuery): Promise<AssetPage> {
    return request<AssetPage>({ url: '/assets', params })
  },

  createAsset(payload: AssetPayload): Promise<AssetPage['items'][number]> {
    return request<AssetPage['items'][number]>({ url: '/assets', method: 'post', data: payload })
  },

  getAsset(id: number): Promise<AssetPage['items'][number]> {
    return request<AssetPage['items'][number]>({ url: `/assets/${id}` })
  },

  updateAsset(id: number, payload: AssetUpdatePayload): Promise<AssetPage['items'][number]> {
    return request<AssetPage['items'][number]>({
      url: `/assets/${id}`,
      method: 'put',
      data: payload,
    })
  },

  batchUpdateAssets(payload: AssetBatchUpdatePayload): Promise<AssetBatchUpdateResult> {
    return request<AssetBatchUpdateResult>({
      url: '/assets/batch-update',
      method: 'post',
      data: payload,
    })
  },

  exportAssets(params: Omit<AssetQuery, 'page' | 'page_size'>): Promise<Blob> {
    return request<Blob>({
      url: '/assets/export',
      params,
      responseType: 'blob',
      timeout: 120000,
    })
  },

  stockInAsset(
    id: number,
    payload: AssetStockInPayload,
  ): Promise<AssetPage['items'][number]> {
    return request<AssetPage['items'][number]>({
      url: `/assets/${id}/stock-in`,
      method: 'post',
      data: payload,
    })
  },

  deleteAsset(id: number): Promise<null> {
    return request<null>({ url: `/assets/${id}`, method: 'delete' })
  },

  custodianOptions(keyword?: string): Promise<CustodianOption[]> {
    return request<CustodianOption[]>({
      url: '/assets/custodian-options',
      params: { keyword },
    })
  },

  deptOptions(): Promise<AssetDeptOption[]> {
    return request<AssetDeptOption[]>({ url: '/assets/dept-options' })
  },

  assetTimeline(id: number): Promise<AssetTimelineItem[]> {
    return request<AssetTimelineItem[]>({ url: `/assets/${id}/timeline` })
  },

  listAssetAttachments(id: number): Promise<AssetAttachment[]> {
    return request<AssetAttachment[]>({ url: `/assets/${id}/attachments` })
  },

  uploadAssetAttachment(id: number, file: File): Promise<AssetAttachment> {
    const data = new FormData()
    data.append('file', file)
    return request<AssetAttachment>({
      url: `/assets/${id}/attachments`,
      method: 'post',
      data,
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },

  downloadAssetAttachment(id: number, attachmentId: number): Promise<Blob> {
    return request<Blob>({
      url: `/assets/${id}/attachments/${attachmentId}/download`,
      responseType: 'blob',
      timeout: 120000,
    })
  },

  deleteAssetAttachment(id: number, attachmentId: number): Promise<null> {
    return request<null>({
      url: `/assets/${id}/attachments/${attachmentId}`,
      method: 'delete',
    })
  },
}
