/* 一键辅助: 未确认事项统计与批量确认(走查整改: 确认动作+批量操作, 责任人概念已移除)。 */
import { api } from '../api'
import type { RequirementRow } from '../types'

export function unconfirmedRegulatory(reqs: RequirementRow[]): RequirementRow[] {
  return reqs.filter((r) => r.category === '监管报送' && !r.reg_confirmed)
}

export function unconfirmedAll(reqs: RequirementRow[]): RequirementRow[] {
  return reqs.filter((r) => !r.reg_confirmed)
}

/** 单条确认。 */
export async function confirmOne(projectId: number, reqId: string) {
  await api.confirmRegulatory(projectId, reqId)
}

/** 批量确认(后端批量接口), 返回确认数与未命中编号。 */
export async function batchConfirm(projectId: number, reqIds: string[]) {
  return api.batchConfirmRequirements(projectId, reqIds)
}
