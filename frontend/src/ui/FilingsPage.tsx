/* 备案管理(#280, 自系统管理 Tab 独立): 备案系统 CRUD + CSV 批量导入 + 统计卡。
   备案是对外备案测评的少数主体, 定级事实由安全侧权威维护(#192),
   系统挂靠备案后自动继承定级。仅安全角色可达(菜单隐藏 + App 外壳 403 兜底)。 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Card, Col, Divider, Empty, Form, Input, Modal, Popconfirm, Row, Select, Space,
  Table, Typography, Upload, message,
} from 'antd'
import type { UploadFile } from 'antd/es/upload/interface'
import { PlusOutlined, UploadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import { api } from '../api'
import { TABLE_PAGINATION, useAsyncAction } from './common'
import { LevelTag, RoundCell } from './tags'
import PageHeader from './PageHeader'
import type { FilingRow, SystemRow } from '../types'

type FilingImportResult = Awaited<ReturnType<typeof api.importFilingsCsv>>

/** 生成 CSV 导入模板(带 BOM, Excel 直接打开不乱码)。 */
function downloadCsvTemplate() {
  const csv = '名称,定级,编号,备注\n示例系统,二级,BA-2026-001,选填\n'
  const blob = new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = '备案导入模板.csv'
  a.click()
  URL.revokeObjectURL(url)
}

export default function FilingsPage() {
  const [rows, setRows] = useState<FilingRow[]>([])
  const [systems, setSystems] = useState<SystemRow[]>([])
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState<Partial<FilingRow> | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importResult, setImportResult] = useState<FilingImportResult | null>(null)
  const doImport = useAsyncAction()

  const reload = useCallback(() => {
    setLoading(true)
    api.listFilings()
      .then(setRows)
      .catch((e: Error) => message.error(e.message))
      .finally(() => setLoading(false))
  }, [])
  useEffect(reload, [reload])
  useEffect(() => { api.listSystems().then(setSystems).catch(() => undefined) }, [])

  const attached = useMemo(() => rows.reduce((n, f) => n + (f.system_count ?? 0), 0), [rows])
  const unattached = useMemo(() => systems.filter((s) => !s.filing_id).length, [systems])

  const columns: ColumnsType<FilingRow> = [
    { title: '备案名称', dataIndex: 'name', width: 260 },
    { title: '备案编号', dataIndex: 'code', width: 160, render: (v: string | null) => v || '—' },
    { title: '定级', dataIndex: 'level', width: 110, render: (v: string) => <LevelTag level={v} /> },
    { title: '下挂系统数', dataIndex: 'system_count', width: 110 },
    { title: '备注', dataIndex: 'note', ellipsis: true, render: (v: string | null) => v || '—' },
    { title: '最新评估', dataIndex: 'latest_round', width: 330, render: (_: unknown, r: FilingRow) => <RoundCell round={r.latest_round} /> },
    {
      title: '操作', key: 'ops', width: 130, fixed: 'right',
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
  ]

  return (
    <div style={{ padding: 24 }}>
      <PageHeader
        title="备案管理"
        description="备案定级由系统挂靠自动继承; 系统与备案的挂靠关系在系统清单维护"
        extra={(
          <Space>
            <Button
              icon={<UploadOutlined />}
              onClick={() => { setImportFile(null); setImportResult(null); setImportOpen(true) }}
            >
              批量导入
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing({ level: '二级' })}>
              新建备案
            </Button>
          </Space>
        )}
      />
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card size="small"><Typography.Text type="secondary">备案总数</Typography.Text>
            <Typography.Title level={3} style={{ margin: 0 }}>{rows.length}</Typography.Title></Card>
        </Col>
        <Col span={8}>
          <Card size="small"><Typography.Text type="secondary">已挂备案的系统</Typography.Text>
            <Typography.Title level={3} style={{ margin: 0 }}>{attached}</Typography.Title></Card>
        </Col>
        <Col span={8}>
          <Card size="small"><Typography.Text type="secondary">未挂备案的系统</Typography.Text>
            <Typography.Title level={3} style={{ margin: 0 }}>{unattached}</Typography.Title></Card>
        </Col>
      </Row>
      <Card styles={{ body: { padding: 0 } }}>
        <Table<FilingRow>
          rowKey="id"
          loading={loading}
          dataSource={rows}
          pagination={TABLE_PAGINATION}
          locale={{ emptyText: (
            <Empty description="还没有备案登记">
              {/* #273: 弹窗按 editing !== null 挂载, 空态新增必须给非空初值 */}
              <Button type="primary" onClick={() => setEditing({ level: '二级' })}>新建备案</Button>
            </Empty>
          ) }}
          columns={columns}
        />
      </Card>
      {editing !== null && (
        <FilingModal
          value={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); reload() }}
        />
      )}
      <Modal
        title="批量导入备案(CSV)" open={importOpen} width={560}
        onCancel={() => setImportOpen(false)}
        footer={[
          <Button key="tpl" type="text" onClick={downloadCsvTemplate}>下载模板</Button>,
          <Button key="cancel" onClick={() => setImportOpen(false)}>关闭</Button>,
          <Button
            key="ok" type="primary" disabled={!importFile} loading={doImport.busy}
            onClick={() => void doImport.run(async () => {
              if (!importFile) return
              const res = await api.importFilingsCsv(importFile)
              setImportResult(res)
              reload()
            })}
          >
            开始导入
          </Button>,
        ]}
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert
            type="info" showIcon
            message="表头: 名称 / 定级 / 编号 / 备注(中英文表头均可)"
            description="定级须为 一级/二级/三级; 编号与备注选填。文件支持 UTF-8 或 GBK 编码; 名称冲突或定级非法的行将跳过, 其余照常导入。"
          />
          <Upload
            accept=".csv" maxCount={1}
            beforeUpload={(file) => { setImportFile(file); setImportResult(null); return false }}
            onRemove={() => { setImportFile(null); setImportResult(null) }}
            fileList={(importFile
              ? [{ uid: 'csv', name: importFile.name, size: importFile.size, status: 'done' } as UploadFile]
              : [])}
          >
            <Button icon={<UploadOutlined />}>选择 CSV 文件</Button>
          </Upload>
          {importResult && (
            <Alert
              type={importResult.skipped.length ? 'warning' : 'success'}
              showIcon
              message={`导入完成: 新增 ${importResult.created} 条${importResult.skipped.length ? `, 跳过 ${importResult.skipped.length} 条` : ''}`}
              description={importResult.skipped.length ? (
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {importResult.skipped.map((s) => (
                    <li key={s.row}>
                      <Typography.Text type="secondary">
                        第 {s.row} 行{s.name ? `「${s.name}」` : ''}: {s.reason}
                      </Typography.Text>
                    </li>
                  ))}
                </ul>
              ) : undefined}
            />
          )}
        </Space>
      </Modal>
    </div>
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
            if (isEdit && value.id != null) await api.updateFiling(value.id, v)
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
