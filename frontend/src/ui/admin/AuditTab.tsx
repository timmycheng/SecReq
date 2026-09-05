/* 审计日志: 登录/生成/确认/知识库与用户管理变更的留痕。
   动作中文标签与明细摘要在后端统一下发(#65); 明细列截断展示, 点开弹窗看格式化全文(#64)。 */
import { useCallback, useEffect, useState } from 'react'
import { Button, Modal, Space, Table, Tag, Tooltip, Typography, message } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'

import { api, type AuditLogRow } from '../../api'

export default function AuditTab() {
  const [rows, setRows] = useState<AuditLogRow[]>([])
  const [loading, setLoading] = useState(false)
  const [viewing, setViewing] = useState<AuditLogRow | null>(null)

  const reload = useCallback(() => {
    setLoading(true)
    api.listAuditLogs()
      .then(setRows)
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoading(false))
  }, [])
  useEffect(reload, [reload])

  return (
    <>
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        记录登录、生成、确认、漏洞库校验以及知识库与用户管理变更, 当前展示最近 {rows.length} 条。
      </Typography.Paragraph>
      <Space style={{ marginBottom: 12 }} wrap>
        <Button icon={<ReloadOutlined />} onClick={reload}>刷新</Button>
      </Space>
      <Table<AuditLogRow>
        rowKey="id" loading={loading} dataSource={rows} size="small"
        tableLayout="fixed"
        pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: [10, 20, 50] }}
        columns={[
          { title: '时间', dataIndex: 'created_at', width: 170 },
          { title: '操作人', dataIndex: 'username', width: 110 },
          { title: '动作', dataIndex: 'action', width: 150,
            render: (_v, r) => (
              <Tooltip title={`原始动作码: ${r.action}`}>
                <Tag color={r.action === 'login_failed' ? 'red' : undefined}>{r.action_label ?? r.action}</Tag>
              </Tooltip>
            ) },
          { title: '明细', dataIndex: 'detail', ellipsis: true,
            render: (_v, r) => (
              <a style={{ wordBreak: 'break-all' }} onClick={() => setViewing(r)}>
                {r.summary || JSON.stringify(r.detail ?? {})}
              </a>
            ) },
          { title: 'IP', dataIndex: 'ip', width: 130, render: (v) => v || '—' },
        ]}
      />
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
    </>
  )
}
