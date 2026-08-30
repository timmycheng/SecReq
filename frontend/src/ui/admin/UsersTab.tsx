/* 用户管理: 新增 / 重置密码 / 启停。角色固定两个, 越权一律 404。 */
import { useCallback, useEffect, useState } from 'react'
import {
  Button, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, Typography, message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'

import { api, type AdminUserRow } from '../../api'

export default function UsersTab() {
  const [rows, setRows] = useState<AdminUserRow[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [form] = Form.useForm()

  const reload = useCallback(() => {
    api.adminListUsers().then(setRows).catch((e: Error) => message.error(e.message))
  }, [])
  useEffect(reload, [reload])

  return (
    <>
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        新用户未指定密码时由系统生成随机初始密码, 创建后弹窗展示。
      </Typography.Paragraph>
      <Space style={{ marginBottom: 12 }} wrap>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新增用户</Button>
      </Space>
      <Table<AdminUserRow>
        rowKey="username" dataSource={rows} pagination={false} size="small"
        columns={[
          { title: '用户名', dataIndex: 'username' },
          { title: '姓名', dataIndex: 'display_name' },
          { title: '工号', dataIndex: 'employee_id', render: (v) => v || '—' },
          { title: '角色', dataIndex: 'role', width: 100,
            render: (v) => <Tag color={v === 'security' ? 'orange' : 'geekblue'}>{v === 'security' ? '安全' : '开发'}</Tag> },
          { title: '状态', dataIndex: 'active', width: 90,
            render: (v: boolean) => (v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>) },
          {
            title: '操作', width: 220,
            render: (_v, r) => (
              <Space>
                <Popconfirm
                  title={`重置 ${r.display_name} 的密码? 将生成随机密码。`}
                  onConfirm={async () => {
                    try {
                      const res = await api.adminResetPassword(r.username)
                      message.success(`已重置, 新密码 ${res.password ?? '-'}`, 8)
                    } catch (e) { message.error((e as Error).message) }
                  }}
                >
                  <Button size="small">重置密码</Button>
                </Popconfirm>
                <Button size="small" danger={r.active} onClick={async () => {
                  try {
                    const res = await api.adminToggleUser(r.username)
                    message.success(`${r.username} 已${res.active ? '启用' : '停用'}`)
                    reload()
                  } catch (e) { message.error((e as Error).message) }
                }}>
                  {r.active ? '停用' : '启用'}
                </Button>
              </Space>
            ),
          },
        ]}
      />
      <Modal
        title="新增用户" open={createOpen} onCancel={() => setCreateOpen(false)}
        onOk={async () => {
          const values = await form.validateFields()
          try {
            const res = await api.adminCreateUser(values)
            message.success(`已创建, 初始密码 ${res.initial_password}`)
            setCreateOpen(false)
            form.resetFields()
            reload()
          } catch (e) {
            message.error((e as Error).message)
          }
        }}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
            <Input placeholder="如 dev_wang" />
          </Form.Item>
          <Form.Item name="display_name" label="姓名" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="employee_id" label="工号(可选)">
            <Input />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true }]} initialValue="developer">
            <Select options={[
              { value: 'developer', label: '开发' },
              { value: 'security', label: '安全' },
            ]} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
