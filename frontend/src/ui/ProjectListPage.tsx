/* 项目列表: 全部项目表格, 新建项目入口; 空状态带首次使用引导。 */
import { useCallback, useEffect, useState } from 'react'
import {
  Button, Card, Empty, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag, message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'

import { api } from '../api'
import { labelOf, optionsOf, useEnums } from '../enums'
import { navigate } from '../router'
import type { ProjectDetail } from '../types'

interface CreateForm {
  name: string
  code: string
  type: string
  user_scale: string
  is_public: boolean
}

export default function ProjectListPage() {
  const enums = useEnums()
  const [projects, setProjects] = useState<ProjectDetail[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm<CreateForm>()

  const reload = useCallback(() => {
    setLoading(true)
    api.listProjects()
      .then(setProjects)
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoading(false))
  }, [])
  useEffect(reload, [reload])

  const handleCreate = async () => {
    const values = await form.validateFields()
    try {
      const detail = await api.createProject({
        ...values,
        deploy_env: ['private_cloud'],
        compliance_targets: [],
      })
      message.success('项目已创建, 即将进入 8 步向导')
      setOpen(false)
      form.resetFields()
      navigate(`/wizard/${detail.id}`)
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  return (
    <div style={{ padding: 24 }}>
      <Card
        title="项目列表"
        extra={(
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
            新建项目
          </Button>
        )}
      >
        <Table<ProjectDetail>
          rowKey="id"
          loading={loading}
          dataSource={projects}
          pagination={false}
          locale={{
            emptyText: (
              <Empty
                style={{ padding: '32px 0' }}
                description={(
                  <>
                    <p style={{ fontWeight: 600 }}>还没有项目</p>
                    <p style={{ color: '#888' }}>
                      SecReq 通过 8 步向导采集项目信息, 按行内安全知识库自动生成
                      安全需求、SBOM 漏洞清单与 4 份 Word 文档, 把安全检查前置到设计阶段。
                    </p>
                  </>
                )}
              >
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
                  新建第一个项目
                </Button>
              </Empty>
            ),
          }}
          expandable={{
            expandedRowRender: (record) => (
              <Space size={[24, 8]} wrap>
                {Object.entries(record.counts).map(([key, count]) => (
                  <span key={key}>
                    <Tag>{count}</Tag>
                    {COUNT_LABELS[key] ?? key}
                  </span>
                ))}
              </Space>
            ),
          }}
          columns={[
            { title: '项目名称', dataIndex: 'name' },
            { title: '项目编码', dataIndex: 'code' },
            { title: '类型', dataIndex: 'type', render: (v: string) => labelOf(enums, 'project_types', v) },
            {
              title: '定级', dataIndex: 'grading_level',
              render: (v: string | null) => (v ? <Tag color="blue">{v}</Tag> : <Tag>未定级</Tag>),
            },
            {
              title: '状态', dataIndex: 'status',
              render: (v: string) =>
                v === 'generated'
                  ? <Tag color="green">已生成基线</Tag>
                  : v === 'draft' ? <Tag color="orange">草稿</Tag> : <Tag>{labelOf(enums, 'project_status', v)}</Tag>,
            },
            { title: '安全需求', dataIndex: ['counts', 'requirements'], width: 90 },
            {
              title: '操作', width: 260,
              render: (_, record) => (
                <Space>
                  <Button size="small" onClick={() => navigate(`/wizard/${record.id}`)}>填写向导</Button>
                  <Button size="small" onClick={() => navigate(`/result/${record.id}`)}>查看产物</Button>
                  <Popconfirm
                    title="删除项目及其全部数据?"
                    onConfirm={async () => {
                      try {
                        await api.deleteProject(record.id)
                        message.success('已删除')
                      } catch (e) {
                        message.error((e as Error).message)
                      }
                      reload()
                    }}
                  >
                    <Button size="small" danger>删除</Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title="新建项目"
        open={open}
        onOk={handleCreate}
        onCancel={() => setOpen(false)}
        okText="创建并进入向导"
        destroyOnHidden
      >
        <Form form={form} layout="vertical" initialValues={{ is_public: false }}>
          <Form.Item name="name" label="项目名称" rules={[{ required: true }]}>
            <Input placeholder="如: 个人网银系统" />
          </Form.Item>
          <Form.Item name="code" label="项目编码" rules={[{ required: true }]} extra="创建后不可修改">
            <Input placeholder="如: PRJ-IBANK-2026" />
          </Form.Item>
          <Form.Item name="type" label="项目类型" rules={[{ required: true }]}>
            <Select options={optionsOf(enums, 'project_types')} />
          </Form.Item>
          <Form.Item name="user_scale" label="用户规模" rules={[{ required: true }]}>
            <Select options={optionsOf(enums, 'user_scales')} />
          </Form.Item>
          <Form.Item name="is_public" label="是否涉及公网访问" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

const COUNT_LABELS: Record<string, string> = {
  features: '功能',
  data_assets: '数据资产',
  roles: '角色',
  resources: '资源',
  permission_entries: '权限授权项',
  components: '组件',
  api_endpoints: '接口',
  infra_assets: '基础设施资产',
  requirements: '安全需求',
  vulnerabilities: '漏洞记录',
}
