/* 平台设置组页面共用小件(#282 去重): 异步动作 hook / 连接测试结果提示 / 表格分页。
   仅收编重复实现, 不引入新依赖; 状态文案口径与 frontend-design-spec 一致。 */
import { useState } from 'react'
import { Alert, message } from 'antd'
import type { CSSProperties, ReactNode } from 'react'
import type { TablePaginationConfig } from 'antd'

/** 列表页统一分页: 每页 10/20/50, 默认 20(设计规范表格规则)。 */
export const TABLE_PAGINATION: TablePaginationConfig = {
  pageSize: 20,
  showSizeChanger: true,
  pageSizeOptions: [10, 20, 50],
  showTotal: (t) => `共 ${t} 条`,
}

/**
 * 保存/测试类异步动作的统一包装: busy 态 + 成功/失败 message。
 * 替代各页重复的 setBusy/try/catch/finally 样板; 校验类异常请留在 run 外部,
 * 让 antd 表单的行内红字接管, 不弹 message。
 */
export function useAsyncAction() {
  const [busy, setBusy] = useState(false)
  const run = async (action: () => Promise<unknown>, successText?: string) => {
    setBusy(true)
    try {
      await action()
      if (successText) message.success(successText)
    } catch (e) {
      // antd validateFields 的 rejection 没有 message 属性, 兜底文案避免空提示
      message.error((e as Error)?.message || '操作失败, 请检查输入')
    } finally {
      setBusy(false)
    }
  }
  return { busy, run }
}

/** 连接测试结果(LDAP/LLM/NetBox 通用): 成功展示耗时与可选补充描述, 失败展示原因。 */
export function TestResultAlert({ result, style, successDescription }: {
  result: { ok: boolean; latency_ms?: number; reason?: string } | null
  style?: CSSProperties
  successDescription?: ReactNode
}) {
  if (!result) return null
  return (
    <Alert
      style={style}
      type={result.ok ? 'success' : 'error'}
      showIcon
      message={result.ok
        ? `连接成功(${result.latency_ms ?? '—'}ms)`
        : `连接失败: ${result.reason ?? '未知原因'}`}
      description={result.ok ? successDescription : undefined}
    />
  )
}

/** 旧载荷无 field_values 时的字段名中文兜底(#176); 正常路径标签由后端 field_values 下发。 */
export const DIFF_FIELD_FALLBACK_LABELS: Record<string, string> = {
  title: '需求标题', description: '需求内容', priority: '优先级',
  acceptance_criteria: '验收标准', category: '类目', regulatory_ref: '合规出处',
}

/** 评审门禁锁定态(DESIGN 状态机): 审批中/已通过的项目内容只读。 */
export function isGateLocked(status: string | null | undefined): boolean {
  return status === 'in_review' || status === 'passed'
}
