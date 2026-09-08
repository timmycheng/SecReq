/* 评审中心(#307): 一级菜单页, 跨项目评审进度总览。
   评估提交后产生条目, 按数据权限过滤(pm 仅本人提交); 点击进入对应评审页。 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Card, Empty, Segmented, Space, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import { api } from '../api'
import { navigate } from '../router'
import PageHeader from './PageHeader'
import { GateStatusTag } from './tags'
import type { ReviewOverviewRow } from '../types'

const fmtDateTime = (v?: string | null) => v?.slice(0, 19).replace('T', ' ') ?? '—'

/** 状态筛选分组: 全部 / 评审中 / 已通过 / 整改中 / 已否决(门禁态聚合)。 */
const STATUS_FILTERS = [
  { label: '全部', value: 'all' },
  { label: '评审中', value: 'in_review' },
  { label: '已通过', value: 'passed' },
  { label: '整改中', value: 'rectifying' },
  { label: '已否决', value: 'rejected' },
] as const

export default function ReviewCenterPage() {
  const [rows, setRows] = useState<ReviewOverviewRow[]>([])
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState<string>('all')

  const load = useCallback(() => {
    setLoading(true)
    api.listReviews()
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }, [])
  useEffect(load, [load])

  const filtered = useMemo(
    () => (status === 'all' ? rows : rows.filter((r) => r.gate_status === status)),
    [rows, status],
  )

  const columns: ColumnsType<ReviewOverviewRow> = [
    {
      title: '评估 / 编码', dataIndex: 'project_name', width: 240, fixed: 'left',
      render: (v: string, r) => (
        <div>
          <Typography.Link onClick={() => navigate(`/evaluations/${r.project_id}/review`)}>{v}</Typography.Link>
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }}>{r.project_code}</Typography.Text>
        </div>
      ),
    },
    { title: '所属系统', dataIndex: 'system_name', width: 160, ellipsis: true,
      render: (v: string | null) => v || '—' },
    { title: '评审状态', dataIndex: 'gate_status', width: 110,
      render: (v: string) => <GateStatusTag status={v} /> },
    { title: '进度', dataIndex: 'status_verb', ellipsis: true },
    { title: '提交人', dataIndex: 'submitter_name', width: 110,
      render: (v: string | null) => v || '—' },
    { title: '评审人', dataIndex: 'reviewer_name', width: 110,
      render: (v: string | null) => v || '—' },
    { title: '提交时间', dataIndex: 'submitted_at', width: 150, render: fmtDateTime },
    { title: '最近动态', dataIndex: 'last_activity_at', width: 150, render: fmtDateTime },
    { title: '需求(待确认/已确认/评审通过)', key: 'summary', width: 200,
      render: (_: unknown, r) => {
        const s = r.requirement_summary ?? {}
        return (
          <Typography.Text style={{ fontSize: 12 }}>
            {s.open ?? 0} / {s.confirmed ?? 0} / {s.reviewed ?? 0}
            {(s.rectifying ?? 0) > 0 && (
              <Typography.Text type="warning"> (整改 {s.rectifying})</Typography.Text>
            )}
          </Typography.Text>
        )
      } },
    { title: '操作', key: 'ops', width: 100, fixed: 'right',
      render: (_, r) => (
        <a onClick={() => navigate(`/evaluations/${r.project_id}/review`)}>进入评审</a>
      ) },
  ]

  return (
    <div style={{ padding: 24 }}>
      <PageHeader
        title="评审中心"
        description="评估提交评审后在此产生条目, 点击进入对应评审页查看进度与留痕"
        extra={(
          <Segmented
            options={STATUS_FILTERS.map((s) => ({ label: s.label, value: s.value }))}
            value={status}
            onChange={(v) => setStatus(v as string)}
          />
        )}
      />
      <Card styles={{ body: { padding: 0 } }}>
        <Table<ReviewOverviewRow>
          rowKey="project_id"
          loading={loading}
          dataSource={filtered}
          scroll={{ x: 'max-content' }}
          pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: [10, 20, 50],
            showTotal: (t) => `共 ${t} 条` }}
          locale={{ emptyText: (
            <Empty style={{ padding: '32px 0' }} description={(
              <>
                <p style={{ fontWeight: 600 }}>暂无评审记录</p>
                <Typography.Text type="secondary">
                  评估提交评审后会出现在这里; 前往评估清单提交评审
                </Typography.Text>
              </>
            )} />
          ) }}
          columns={columns}
        />
      </Card>
      <Space style={{ marginTop: 8 }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          共 {rows.length} 条评审记录{status !== 'all' && `, 当前筛选 ${filtered.length} 条`}
        </Typography.Text>
      </Space>
    </div>
  )
}
