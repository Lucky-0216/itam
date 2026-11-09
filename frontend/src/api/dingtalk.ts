import { request } from '@/api/request'
import type {
  DingTalkConfig,
  DingTalkConfigPayload,
  DingTalkConfigUpdatePayload,
  DingTalkOptions,
  DingTalkSyncAccepted,
  DingTalkSyncLog,
  DingTalkSyncLogPage,
  DingTalkTestResult,
} from '@/types/dingtalk'

export const dingtalkApi = {
  getConfig(): Promise<DingTalkConfig> {
    return request<DingTalkConfig>({ url: '/system/dingtalk/config' })
  },

  saveConfig(payload: DingTalkConfigUpdatePayload): Promise<DingTalkConfig> {
    return request<DingTalkConfig>({
      url: '/system/dingtalk/config',
      method: 'put',
      data: payload,
    })
  },

  testConfig(payload: DingTalkConfigPayload): Promise<DingTalkTestResult> {
    return request<DingTalkTestResult>({
      url: '/system/dingtalk/test',
      method: 'post',
      data: payload,
    })
  },

  getOptions(): Promise<DingTalkOptions> {
    return request<DingTalkOptions>({ url: '/system/dingtalk/options' })
  },

  triggerSync(): Promise<DingTalkSyncAccepted> {
    return request<DingTalkSyncAccepted>({ url: '/system/dingtalk/sync', method: 'post' })
  },

  listLogs(params: {
    page: number
    page_size: number
    status?: string
  }): Promise<DingTalkSyncLogPage> {
    return request<DingTalkSyncLogPage>({ url: '/system/dingtalk/logs', params })
  },

  getLog(id: number): Promise<DingTalkSyncLog> {
    return request<DingTalkSyncLog>({ url: `/system/dingtalk/logs/${id}` })
  },
}
