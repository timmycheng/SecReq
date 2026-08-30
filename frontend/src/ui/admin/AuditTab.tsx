/* 审计日志: 登录/生成/确认/知识库与用户管理变更的留痕。 */
import { useCallback, useEffect, useState } from 'react'
import { Button, Space, Table, Tag, Typography, message } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'

import { api, type AuditLogRow } from '../../api'

export default function AuditTab() {
  const [rows, setRows] = useState<AuditLogRow[]>([])
  const [loading, setLoading] = useState(false)

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
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          { title: '时间', dataIndex: 'created_at', width: 180 },
          { title: '操作人', dataIndex: 'username', width: 120 },
          { title: '动作', dataIndex: 'action', width: 160,
            render: (v) => <Tag>{v}</Tag> },
          { title: '明细', dataIndex: 'detail',
            render: (d: Record<string, unknown>) => <code style={{ fontSize: 12 }}>{JSON.stringify(d)}</code> },
          { title: 'IP', dataIndex: 'ip', width: 130, render: (v) => v || '—' },
        ]}
      />
    </>
  )
}
