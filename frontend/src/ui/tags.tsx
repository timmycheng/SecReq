/**
 * 共享状态标签(#280): 跨页面复用的 Tag 组件, 颜色一律取 ui/tokens.ts,
 * 页面不得自写 <Tag color=...> 的同义映射。
 */
import { Space, Tag, Typography } from 'antd'

import type { RoundSummary } from '../types'
import { GRADING_LEVEL_COLOR, GATE_STATUS_COLOR, PROJECT_STATUS_COLOR, PROJECT_STATUS_TEXT } from './tokens'

/** 等保定级标签: 未备案灰 / 一二三级按 GRADING_LEVEL_COLOR ramp。 */
export function LevelTag({ level }: { level?: string | null }) {
  if (!level) return <Tag>未备案</Tag>
  return <Tag color={GRADING_LEVEL_COLOR[level] ?? 'default'}>等保{level}</Tag>
}

/** 评估状态标签: 草稿=橙 / 已生成基线=绿。 */
export function ProjectStatusTag({ status }: { status: string }) {
  return (
    <Tag color={PROJECT_STATUS_COLOR[status] ?? 'default'}>
      {PROJECT_STATUS_TEXT[status] ?? status}
    </Tag>
  )
}

/** 评审门禁状态标签(ReviewGate)。 */
const GATE_TEXT: Record<string, string> = {
  pending: '待提交', in_review: '评审中', passed: '已通过',
  rejected: '已否决', rectifying: '整改中',
}
export function GateStatusTag({ status }: { status?: string | null }) {
  if (!status) return <Tag>未提交</Tag>
  return <Tag color={GATE_STATUS_COLOR[status] ?? 'default'}>{GATE_TEXT[status] ?? status}</Tag>
}

/** 最新评估轮次摘要格: 编码可复制 + 状态 + 定级 + 需求闭环数(系统清单/备案页共用)。 */
export function RoundCell({ round }: { round?: RoundSummary | null }) {
  if (!round) return <Typography.Text type="secondary">暂无已生成评估</Typography.Text>
  return (
    <Space size={6} wrap>
      <Typography.Text copyable={{ text: round.project_code }} style={{ fontSize: 13 }}>
        {round.project_code}
      </Typography.Text>
      <ProjectStatusTag status={round.status} />
      {round.grading_level && (
        <Tag color={GRADING_LEVEL_COLOR[round.grading_level] ?? 'default'}>{round.grading_level}</Tag>
      )}
      <Typography.Text type="secondary">
        需求 {round.requirements_total} 条 / 未闭环 {round.requirements_open}
      </Typography.Text>
    </Space>
  )
}
