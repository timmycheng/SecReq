/* 一键修复辅助: 把"门禁阻断 → 需要逐条补数据"的繁琐操作收敛成一个按钮。
   供产物页「下一步指引」与评审页「一键修复」共用。 */
import { api } from '../api'
import type { RequirementRow } from '../types'

export function unconfirmedRegulatory(reqs: RequirementRow[]): RequirementRow[] {
  return reqs.filter((r) => r.category === '监管报送' && !r.reg_confirmed)
}

export function criticalWithoutOwner(reqs: RequirementRow[]): RequirementRow[] {
  return reqs.filter((r) => r.priority === 'critical' && !(r.owner ?? '').trim())
}

/** 逐条确认全部监管报送事项, 返回成功数(失败抛错由调用方提示)。 */
export async function batchConfirmRegulatory(projectId: number, reqs: RequirementRow[]) {
  let done = 0
  for (const r of unconfirmedRegulatory(reqs)) {
    await api.confirmRegulatory(projectId, r.req_id)
    done += 1
  }
  return done
}

/** 为全部未指定责任人的 critical 需求统一指派同一责任人。 */
export async function batchSetOwner(projectId: number, reqs: RequirementRow[], owner: string) {
  const targets = criticalWithoutOwner(reqs)
  for (const r of targets) {
    await api.setRequirementOwner(projectId, r.req_id, owner)
  }
  return targets.length
}
