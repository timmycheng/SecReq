/* 一键辅助: 未确认事项统计与批量确认(走查整改: 确认动作+批量操作, 责任人概念已移除)。
   #310 属实性确认: 待处理口径按 review_status(open/rectifying)计算,
   不属实(invalid)是开发侧的主动结论, 不参与批量确认以免被「确认全部」误覆盖。 */
import { api } from '../api'
import type { RequirementRow } from '../types'

/** 需要开发侧处理的状态(待确认/整改中)。 */
export function needsDevAction(r: RequirementRow): boolean {
  return r.review_status === 'open' || r.review_status === 'rectifying'
}

export function unconfirmedRegulatory(reqs: RequirementRow[]): RequirementRow[] {
  return reqs.filter((r) => r.category === '监管报送' && needsDevAction(r))
}

export function unconfirmedAll(reqs: RequirementRow[]): RequirementRow[] {
  return reqs.filter(needsDevAction)
}

/** 单条确认(属实)。 */
export async function confirmOne(projectId: number, reqId: string) {
  await api.confirmRegulatory(projectId, reqId)
}

/** 批量确认(后端批量接口), 返回确认数与未命中编号。 */
export async function batchConfirm(projectId: number, reqIds: string[]) {
  return api.batchConfirmRequirements(projectId, reqIds)
}

/* ── 按知识库规则聚合(#310): 同一规则命中多个功能/数据项时合并展示 ── */

export interface RequirementGroup {
  templateId: string
  /** 组标题(取首条实例; 命中多条且标题各异时展示层追加「等 N 条」) */
  title: string
  description: string
  category: string
  /** 组内最高优先级 */
  priority: string
  instances: RequirementRow[]
}

const PRIORITY_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }

export function groupByTemplate(reqs: RequirementRow[]): RequirementGroup[] {
  const map = new Map<string, RequirementGroup>()
  for (const r of reqs) {
    const g = map.get(r.template_id) ?? {
      templateId: r.template_id,
      title: r.title,
      description: r.description,
      category: r.category,
      priority: r.priority,
      instances: [],
    }
    g.instances.push(r)
    if ((PRIORITY_RANK[r.priority] ?? 9) < (PRIORITY_RANK[g.priority] ?? 9)) g.priority = r.priority
    map.set(r.template_id, g)
  }
  return [...map.values()]
}
