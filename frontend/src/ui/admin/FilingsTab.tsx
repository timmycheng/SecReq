/* 定级备案管理(#270, 自系统清单页迁入系统管理): 备案是对外备案测评的少数主体,
   定级事实由安全侧权威维护(#192), 系统挂靠备案后自动继承定级。
   本 Tab 仅安全角色可达(AdminPage 外壳已 403 兜底, 后端写端点再校验一道)。 */
import { useCallback, useEffect, useState } from 'react'
import {
  Button, Divider, Empty, Form, Input, Modal, Popconfirm, Select, Space, Table, Typography,
  message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'

import { api } from '../../api'
import { LevelTag, RoundCell } from '../SystemsPage'
import type { FilingRow } from '../../types'

export default function FilingsTab() {
  const [rows, setRows] = useState<FilingRow[]>([])
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState<Partial<FilingRow> | null>(null)

  const reload = useCallback(() => {
    setLoading(true)
    api.listFilings()
      .then(setRows)
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoading(false))
  }, [])
  useEffect(reload, [reload])

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing({ level: '二级' })}>
          新增备案
        </Button>
        <Typography.Text type="secondary">
          备案是对外备案测评的少数主体, 定级在此登记; 系统挂靠备案后自动继承定级
        </Typography.Text>
      </Space>
      <Table<FilingRow>
        rowKey="id"
        loading={loading}
        dataSource={rows}
        pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: [10, 20, 50] }}
        locale={{ emptyText: (
          <Empty description="还没有备案登记">
            {/* #273: 弹窗按 editing !== null 挂载, 空态新增必须给非空初值 */}
            <Button type="primary" onClick={() => setEditing({ level: '二级' })}>新建备案</Button>
          </Empty>
) }}
        columns={[
          { title: '备案名称', dataIndex: 'name' },
          { title: '备案编号', dataIndex: 'code', width: 160, render: (v: string | null) => v || '—' },
          { title: '定级', dataIndex: 'level', width: 110, render: (v: string) => <LevelTag level={v} /> },
          { title: '下挂系统数', dataIndex: 'system_count', width: 110 },
          { title: '备注', dataIndex: 'note', ellipsis: true, render: (v: string | null) => v || '—' },
          { title: '最新评估', dataIndex: 'latest_round', width: 300, render: (_: unknown, r: FilingRow) => <RoundCell round={r.latest_round} /> },
          {
            title: '操作', width: 120,
            render: (_: unknown, record: FilingRow) => (
              <Space size={0} split={<Divider type="vertical" />}>
                <Button type="link" size="small" onClick={() => setEditing(record)}>编辑</Button>
                <Popconfirm
                  title="删除该备案?"
                  description="下挂系统需先解除关联"
                  onConfirm={async () => {
                    try {
                      await api.deleteFiling(record.id)
                      message.success('已删除')
                      reload()
                    } catch (e) {
                      message.error((e as Error).message)
                    }
                  }}
                >
                  <Button type="link" size="small" danger>删除</Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      {editing !== null && (
        <FilingModal
          value={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); reload() }}
        />
      )}
    </>
  )
}

function FilingModal({ value, onSaved, onClose }: {
  value: Partial<FilingRow>
  onSaved: () => void
  onClose: () => void
}) {
  const [form] = Form.useForm<Partial<FilingRow>>()
  const isEdit = value.id !== undefined
  return (
    <Modal
      title={isEdit ? '编辑备案' : '新增备案'}
      open
      onCancel={onClose}
      onOk={() => form.validateFields()
        .then(async (v) => {
          try {
            if (isEdit) await api.updateFiling(value.id!, v)
            else await api.createFiling(v)
            message.success('已保存')
            onSaved()
          } catch (e) {
            message.error((e as Error).message)
          }
        })
        .catch(() => { /* 校验失败留在弹窗 */ })}
    >
      <Form form={form} layout="vertical" initialValues={value}>
        <Form.Item name="name" label="备案名称" rules={[{ required: true, message: '请输入备案名称' }]}>
          <Input placeholder="如: 个人网银系统(等保三级备案)" />
        </Form.Item>
        <Form.Item name="code" label="备案编号">
          <Input placeholder="备案证明上的编号, 选填" />
        </Form.Item>
        <Form.Item name="level" label="备案定级" rules={[{ required: true, message: '请选择定级' }]}>
          <Select options={['一级', '二级', '三级'].map((l) => ({ value: l, label: `等保${l}` }))} />
        </Form.Item>
        <Form.Item name="note" label="备注">
          <Input.TextArea rows={2} placeholder="如: 备案日期 / 测评机构 / 测评有效期" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
