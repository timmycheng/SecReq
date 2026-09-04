/* NetBox 系统清单导入弹窗(#154): 系统台账页与向导 Step1「所属系统」共用。
   只负责搜索/勾选 NetBox 行, 创建与查重由调用方处理; 未配置/断连给可读空态+重试。 */
import { useEffect, useState } from 'react'
import { Alert, Button, Input, Modal, Table, Typography } from 'antd'

import { api } from '../api'
import type { NetboxSystemRow } from '../types'

export default function NetboxSystemImportModal({ open, onClose, onSelected }: {
  open: boolean
  onClose: () => void
  onSelected: (rows: NetboxSystemRow[]) => void
}) {
  const [rows, setRows] = useState<NetboxSystemRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<NetboxSystemRow[]>([])

  const load = (kw: string, nextPage: number) => {
    setLoading(true)
    setError(null)
    api.listNetboxSystems(kw, 10, (nextPage - 1) * 10)
      .then((data) => {
        setRows(data.results ?? [])
        setTotal(data.count ?? 0)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (open) {
      setKeyword(''); setPage(1); setSelected([]); setRows([]); setTotal(0); setError(null)
      load('', 1)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  return (
    <Modal
      title="从 NetBox 导入系统" open={open} onCancel={onClose} width={720}
      footer={[
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button key="ok" type="primary" disabled={selected.length === 0}
          onClick={() => onSelected(selected)}>
          导入所选 {selected.length} 个
        </Button>,
      ]}
    >
      {error ? (
        <Alert
          type="warning" showIcon
          message={`NetBox 暂不可用: ${error}`}
          description="系统台账与建项流程不受影响; 可在 系统管理 → NetBox 互通 检查配置后重试。"
          action={<Button size="small" onClick={() => load(keyword, page)}>重试</Button>}
        />
      ) : (
        <>
          <Input.Search
            style={{ width: 280, marginBottom: 12 }} placeholder="关键字搜索" allowClear
            onSearch={(kw) => { setKeyword(kw); setPage(1); load(kw, 1) }}
          />
          <Table<NetboxSystemRow>
            rowKey="id"
            size="small"
            loading={loading}
            dataSource={rows}
            pagination={{ current: page, pageSize: 10, total, showSizeChanger: false }}
            onChange={(pagination) => { setPage(pagination.current ?? 1); load(keyword, pagination.current ?? 1) }}
            rowSelection={{ selectedRowKeys: selected.map((r) => r.id), onChange: (_, rs) => setSelected(rs) }}
            locale={{ emptyText: '无匹配系统' }}
            columns={[
              { title: '系统名称', dataIndex: 'name' },
              { title: '编码', dataIndex: 'code', width: 150, render: (v: string | null) => v || '—' },
              { title: '负责人', dataIndex: 'owner', width: 120, render: (v: string | null) => v || '—' },
            ]}
          />
        </>
      )}
      <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
        导入后即登记为本系统台账; 与已有系统按名称或 NetBox 对象查重, 重复行自动跳过。
      </Typography.Text>
    </Modal>
  )
}
