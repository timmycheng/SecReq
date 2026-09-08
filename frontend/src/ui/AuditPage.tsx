/* 日志审计(#280, 自系统管理 Tab 独立): 登录/生成/确认/知识库与用户管理变更的留痕。
   动作中文标签与明细摘要在后端统一下发(#65); 明细列截断展示, 点开弹窗看格式化全文(#64)。 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Button, Card, DatePicker, Modal, Select, Space, Table, Tag, Tooltip, Typography, message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'

import { api, type AuditLogRow } from '../api'
import { TABLE_PAGINATION } from './common'
import PageHeader from './PageHeader'

export default function AuditPage() {
  const [rows, setRows] = useState<AuditLogRow[]>([])
  const [loading, setLoading] = useState(false)
  const [viewing, setViewing] = useState<AuditLogRow | null>(null)
  const [user, setUser] = useState<string>()
  const [action, setAction] = useState<string>()
  const [range, setRange] = useState<{ from?: string; to?: string }>({})

  const reload = useCallback(() => {
    setLoading(true)
    api.listAuditLogs()
      .then(setRows)
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoading(false))
  }, [])
  useEffect(reload, [reload])

  const list = useMemo(() => rows.filter((r) =>
    (!user || r.username === user)
    && (!action || r.action === action)
    && (!range.from || r.created_at >= range.from)
    && (!range.to || r.created_at <= `${range.to} 23:59:59`)),
  [rows, user, action, range])

  const columns: ColumnsType<AuditLogRow> = [
    { title: '时间', dataIndex: 'created_at', width: 170 },
    { title: '操作人', dataIndex: 'username', width: 120 },
    {
      title: '动作', dataIndex: 'action', width: 150,
      render: (_v, r) => (
        <Tooltip title={`原始动作码: ${r.action}`}>
          <Tag color={r.action === 'login_failed' ? 'red' : undefined}>{r.action_label ?? r.action}</Tag>
        </Tooltip>
      ),
    },
    {
      title: '明细', dataIndex: 'detail', ellipsis: true,
      render: (_v, r) => (
        <a style={{ wordBreak: 'break-all' }} onClick={() => setViewing(r)}>
          {r.summary || JSON.stringify(r.detail ?? {})}
        </a>
      ),
    },
    { title: 'IP', dataIndex: 'ip', width: 130, render: (v) => v || '—' },
  ]

  return (
    <div style={{ padding: 24 }}>
      <PageHeader
        title="日志审计"
        description="登录、生成、确认、漏洞库校验与知识库/用户管理变更的留痕, 只读"
        extra={<Button onClick={reload}>刷新</Button>}
      />
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            allowClear placeholder="操作人" style={{ width: 150 }} value={user}
            options={[...new Set(rows.map((r) => r.username))].map((v) => ({ value: v, label: v }))}
            onChange={(v) => setUser(v)}
          />
          <Select
            allowClear placeholder="动作" style={{ width: 180 }} value={action}
            options={[...new Set(rows.map((r) => r.action))]
              .map((code) => ({ value: code, label: rows.find((r) => r.action === code)?.action_label ?? code }))}
            onChange={(v) => setAction(v)}
          />
          <DatePicker.RangePicker
            allowEmpty={[true, true]}
            onChange={(v) => setRange({
              from: v?.[0]?.format('YYYY-MM-DD'),
              to: v?.[1]?.format('YYYY-MM-DD'),
            })}
          />
          <Typography.Text type="secondary">共 {list.length} 条</Typography.Text>
        </Space>
      </Card>
      <Card styles={{ body: { padding: 0 } }}>
        <Table<AuditLogRow>
          rowKey="id" loading={loading} dataSource={list} size="small"
          tableLayout="fixed"
          pagination={TABLE_PAGINATION}
          columns={columns}
        />
      </Card>
      <Modal
        open={viewing !== null} onCancel={() => setViewing(null)} footer={null} width={720}
        title={viewing
          ? `${viewing.action_label ?? viewing.action} · ${viewing.username} · ${viewing.created_at}`
          : ''}
      >
        {viewing?.summary && (
          <Typography.Paragraph style={{ marginBottom: 8 }}>{viewing.summary}</Typography.Paragraph>
        )}
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 4 }}>
          明细原文:
        </Typography.Text>
        <pre style={{
          margin: 0, maxHeight: 420, overflow: 'auto', fontSize: 12, lineHeight: 1.6,
          whiteSpace: 'pre-wrap', wordBreak: 'break-all', background: '#fafafa', padding: 12, borderRadius: 6,
        }}>
          {JSON.stringify(viewing?.detail ?? {}, null, 2)}
        </pre>
      </Modal>
    </div>
  )
}
