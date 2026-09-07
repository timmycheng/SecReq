/* 用户管理(#280, 自系统管理 Tab 独立): 新增 / 编辑 / 重置密码 / 启停 / LDAP 导入。
   角色枚举取自 /api/meta/constants(#216); 新用户未指定密码时由系统生成初始密码。 */
import { useCallback, useEffect, useState } from 'react'
import {
  Button, Card, Divider, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, Typography, message,
} from 'antd'
import { CloudDownloadOutlined, PlusOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import { api, type AdminUserRow } from '../api'
import { ROLE_COLOR } from './tokens'
import PageHeader from './PageHeader'

export default function UsersPage() {
  const [rows, setRows] = useState<AdminUserRow[]>([])
  const [roleOptions, setRoleOptions] = useState<{ value: string; label: string }[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<AdminUserRow | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()

  const reload = useCallback(() => {
    api.adminListUsers().then(setRows).catch((e: Error) => message.error(e.message))
  }, [])
  useEffect(reload, [reload])
  useEffect(() => {
    api.constants().then((c) => {
      const roles = (c.platform_roles ?? {}) as Record<string, string>
      setRoleOptions(Object.entries(roles).map(([value, label]) => ({ value, label })))
    }).catch(() => undefined)
  }, [])

  const syncLdap = async () => {
    setSyncing(true)
    try {
      const res = await api.syncLdapUsers()
      message.success(`LDAP 导入完成: 目录 ${res.total} 人, 新增 ${res.created} 人, 跳过 ${res.skipped} 人`)
      reload()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSyncing(false)
    }
  }

  const columns: ColumnsType<AdminUserRow> = [
    { title: '用户名', dataIndex: 'username', width: 140 },
    { title: '姓名', dataIndex: 'display_name', width: 120 },
    { title: '工号', dataIndex: 'employee_id', width: 110, render: (v) => v || '—' },
    { title: '角色', dataIndex: 'role', width: 120,
      render: (v) => {
        const opt = roleOptions.find((o) => o.value === v)
        return <Tag color={ROLE_COLOR[v] ?? 'default'}>{opt?.label ?? v}</Tag>
      } },
    { title: '状态', dataIndex: 'active', width: 90,
      render: (v: boolean) => (v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>) },
    {
      title: '操作', key: 'ops', width: 220, fixed: 'right',
      render: (_v, r) => (
        <Space size={0} split={<Divider type="vertical" />}>
          <Button type="link" size="small"
            onClick={() => { setEditing(r); editForm.setFieldsValue(r) }}>编辑</Button>
          <Popconfirm
            title={`重置 ${r.display_name} 的密码? 将生成随机密码。`}
            onConfirm={async () => {
              try {
                const res = await api.adminResetPassword(r.username)
                // 后端仅在未指定新密码时返回生成的随机密码; 为空不能拿"-"冒充密码展示(#39)
                if (res.password) message.success(`已重置, 新密码 ${res.password}`, 8)
                else message.success('密码已重置')
              } catch (e) { message.error((e as Error).message) }
            }}
          >
            <Button type="link" size="small">重置密码</Button>
          </Popconfirm>
          <Button type="link" size="small" danger={r.active} onClick={async () => {
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
  ]

  return (
    <div style={{ padding: 24 }}>
      <PageHeader
        title="用户管理"
        description="平台账号与角色管理; 角色决定数据可见范围"
        extra={(
          <>
            <Button
              icon={<CloudDownloadOutlined />} loading={syncing}
              onClick={() => void syncLdap()}
            >
              LDAP 导入
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新增用户</Button>
          </>
        )}
      />
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Typography.Text type="secondary">共 {rows.length} 人; 启用 {rows.filter((r) => r.active).length} 人</Typography.Text>
        </Space>
      </Card>
      <Card styles={{ body: { padding: 0 } }}>
        <Table<AdminUserRow>
          rowKey="username"
          dataSource={rows}
          loading={rows.length === 0}
          pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: [10, 20, 50], showTotal: (t) => `共 ${t} 条` }}
          size="small"
          scroll={{ x: 900 }}
          columns={columns}
        />
      </Card>
      <Modal
        title={`编辑用户 ${editing?.username ?? ''}`}
        open={editing !== null}
        onCancel={() => setEditing(null)}
        onOk={async () => {
          if (!editing) return
          const values = await editForm.validateFields()
          try {
            await api.adminUpdateUser(editing.username, values)
            message.success('用户资料已更新')
            setEditing(null)
            reload()
          } catch (e) {
            message.error((e as Error).message)
          }
        }}
      >
        {/* username 建后不可改: 审计留痕与项目归属等多处逻辑按 username 引用(#63) */}
        <Form form={editForm} layout="vertical">
          <Form.Item label="用户名">
            <Input value={editing?.username} disabled />
          </Form.Item>
          <Form.Item name="display_name" label="姓名" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="employee_id" label="工号(可选)">
            <Input />
          </Form.Item>
          <Form.Item
            name="role" label="角色" rules={[{ required: true }]}
            extra="修改自己的角色会被拒绝; 角色变更即时影响数据可见范围"
          >
            <Select options={roleOptions} />
          </Form.Item>
        </Form>
      </Modal>
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
          <Form.Item name="role" label="角色" rules={[{ required: true }]} initialValue="pm">
            <Select options={roleOptions} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
