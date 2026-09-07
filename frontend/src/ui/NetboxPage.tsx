/* Netbox 管理(#280, 自系统管理 Tab 独立): 单向 ETL 同步(SecReq → NetBox 只推不拉, #271)。
   配置区(地址/Token/系统类型/字段映射) + 同步调度(开关/周期/立即同步) + 同步历史。
   其他角色与页面零感知: 系统清单/向导不出现任何 NetBox 入口, 同步在后台执行。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Alert, Button, Card, Col, Form, Input, InputNumber, Row, Space, Switch, Table, Tag, Typography,
  message,
} from 'antd'

import { api, type NetboxConfig, type NetboxSyncLogOut } from '../api'
import PageHeader from './PageHeader'

const SYNC_STATUS_COLOR: Record<string, string> = {
  running: 'blue', success: 'green', partial: 'gold', failed: 'red',
}
const SYNC_STATUS_LABEL: Record<string, string> = {
  running: '执行中', success: '成功', partial: '部分成功', failed: '失败',
}
const TRIGGER_LABEL: Record<string, string> = { manual: '手动', scheduled: '定时' }

/** 统计列渲染: 新建/更新/跳过/失败 四元组。 */
function StatTags({ stats, section }: { stats: Record<string, Record<string, number>>; section: string }) {
  const s = stats?.[section]
  if (!s) return <span>—</span>
  return (
    <Space size={4} wrap>
      <Tag>+{s.created ?? 0}</Tag>
      <Tag color="blue">~{s.updated ?? 0}</Tag>
      <Tag>={s.skipped ?? 0}</Tag>
      {(s.failed ?? 0) > 0 && <Tag color="red">!{s.failed}</Tag>}
    </Space>
  )
}

export default function NetboxPage() {
  const [cfg, setCfg] = useState<NetboxConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<
    { ok: boolean; latency_ms?: number; version?: string; reason?: string } | null
  >(null)
  const [form] = Form.useForm()

  // 同步状态/历史: 运行中每 3s 轮询, 结束后刷历史
  const [syncState, setSyncState] = useState<Awaited<ReturnType<typeof api.getNetboxSyncState>> | null>(null)
  const [logs, setLogs] = useState<NetboxSyncLogOut[]>([])
  const [syncing, setSyncing] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const stopPoll = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }, [])
  const loadLogs = useCallback(() => {
    api.listNetboxSyncLogs().then(setLogs).catch(() => undefined)
  }, [])
  const checkState = useCallback(() => {
    api.getNetboxSyncState().then((s) => {
      setSyncState(s)
      if (s.running && !pollRef.current) {
        // 执行中(如定时线程在跑): 3s 轮询直到结束
        pollRef.current = setInterval(checkStateRef.current, 3000)
      }
      if (!s.running) {
        stopPoll()
        loadLogs()
      }
    }).catch(() => undefined)
  }, [loadLogs, stopPoll])
  const checkStateRef = useRef(checkState)
  checkStateRef.current = checkState
  const reload = useCallback(() => {
    api.getNetboxConfig().then((c) => {
      setCfg(c)
      form.setFieldsValue({
        base_url: c.base_url,
        system_slug: c.system_slug ?? 'system',
        name_key: c.field_map?.name ?? 'name',
        code_key: c.field_map?.code ?? 'code',
        owner_key: c.field_map?.owner ?? 'owner',
        sync_enabled: c.sync_enabled ?? false,
        sync_interval_hours: c.sync_interval_hours ?? 24,
      })
      setSyncState({
        running: false,
        schedule: { enabled: c.sync_enabled ?? false, interval_hours: c.sync_interval_hours ?? 24 },
        last: null,
      })
    }).catch((e: Error) => message.error(e.message))
    checkState()
    loadLogs()
  }, [form, checkState, loadLogs])
  useEffect(reload, [reload])
  useEffect(() => stopPoll, [stopPoll])

  /** 手动触发一轮同步; 运行中进入轮询直到结束。 */
  const runNow = async () => {
    setSyncing(true)
    try {
      await api.runNetboxSync()
      message.success('同步完成')
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSyncing(false)
      stopPoll()
      checkState()
      loadLogs()
    }
  }

  return (
    <div style={{ padding: 24 }}>
      <PageHeader
        title="Netbox 管理"
        description="单向同步: SecReq → NetBox 只推不拉, 作为后备资产库存档"
        extra={(
          <Space>
            <Button
              danger={syncState?.last?.status === 'failed'} loading={syncing || syncState?.running}
              onClick={() => void runNow()}
            >
              立即同步
            </Button>
            <Button
              type="primary" loading={saving}
              onClick={async () => {
                const v = await form.validateFields()
                setSaving(true)
                try {
                  await api.saveNetboxConfig({
                    base_url: v.base_url,
                    token: v.token || '',
                    system_slug: v.system_slug || 'system',
                    field_map: { name: v.name_key || 'name', code: v.code_key || 'code', owner: v.owner_key || 'owner' },
                    sync_enabled: v.sync_enabled ?? false,
                    sync_interval_hours: v.sync_interval_hours ?? 24,
                  })
                  message.success('已保存 NetBox 配置')
                  reload()
                } catch (e) {
                  message.error((e as Error).message)
                } finally {
                  setSaving(false)
                }
              }}
            >
              保存配置
            </Button>
          </Space>
        )}
      />
      <Row gutter={16}>
        <Col xs={24} lg={12}>
          <Card title="对接配置" style={{ marginBottom: 16 }}>
            <Form form={form} layout="vertical">
              <Space size={12} style={{ display: 'flex' }}>
                <Form.Item name="base_url" label="NetBox 地址" extra="如 https://netbox.corp.example.com">
                  <Input placeholder="https://..." style={{ width: 320 }} />
                </Form.Item>
                <Form.Item
                  name="token" label="API Token"
                  extra={cfg?.token ? `当前: ${cfg.token}` : '未配置'}
                >
                  <Input.Password placeholder="Token 只存后端, 回显仅前 4 位" style={{ width: 220 }} />
                </Form.Item>
              </Space>
              <Space size={12} style={{ display: 'flex' }}>
                <Form.Item
                  name="system_slug" label="系统对象类型 slug"
                  extra="custom-objects 插件类型标识(默认 system)"
                >
                  <Input placeholder="system" style={{ width: 140 }} />
                </Form.Item>
                <Form.Item name="name_key" label="名称字段" style={{ width: 120 }}>
                  <Input placeholder="name" />
                </Form.Item>
                <Form.Item name="code_key" label="编码字段" style={{ width: 120 }}>
                  <Input placeholder="code" />
                </Form.Item>
                <Form.Item name="owner_key" label="负责人字段" style={{ width: 120 }}>
                  <Input placeholder="owner" />
                </Form.Item>
              </Space>
              <Button
                loading={testing}
                onClick={async () => {
                  const v = await form.validateFields()
                  setTesting(true)
                  setTestResult(null)
                  try {
                    setTestResult(await api.testNetboxConfig({ base_url: v.base_url, token: v.token || undefined }))
                  } catch (e) {
                    message.error((e as Error).message)
                  } finally {
                    setTesting(false)
                  }
                }}
              >
                测试连接
              </Button>
              {testResult && (
                <Alert
                  style={{ marginTop: 12 }}
                  type={testResult.ok ? 'success' : 'error'}
                  showIcon
                  message={testResult.ok
                    ? `连接成功(${testResult.latency_ms}ms)`
                    : `连接失败: ${testResult.reason ?? '未知原因'}`}
                  description={testResult.ok ? `NetBox 版本: ${testResult.version}` : undefined}
                />
              )}
            </Form>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="同步调度" style={{ marginBottom: 16 }}>
            <Form form={form} layout="vertical">
              <Space size={24} wrap>
                <Form.Item name="sync_enabled" label="定时同步" valuePropName="checked">
                  <Switch checkedChildren="开" unCheckedChildren="关" />
                </Form.Item>
                <Form.Item name="sync_interval_hours" label="周期(小时)" tooltip="到期后自动执行一轮全量比对同步">
                  <InputNumber min={1} max={720} style={{ width: 110 }} />
                </Form.Item>
              </Space>
            </Form>
            {syncState?.schedule.enabled && (
              <Typography.Text type="secondary">
                定时已开启, 每 {syncState.schedule.interval_hours} 小时自动同步。
              </Typography.Text>
            )}
            <Alert
              style={{ marginTop: 12 }} type="info" showIcon
              message="只推不拉"
              description="系统与基础设施的填报永远在本平台维护, 不从 NetBox 导入; 设备同步使用 secreq-* 引导对象(机房/角色/机型), 缺失时自动创建。"
            />
          </Card>
        </Col>
      </Row>

      <Card title="同步历史" styles={{ body: { padding: 0 } }}>
        <Table<NetboxSyncLogOut>
          rowKey="id" size="small"
          dataSource={logs}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          locale={{ emptyText: '还没有同步记录, 点「立即同步」或开启定时后自动执行' }}
          expandable={{
            rowExpandable: (r) => (r.errors?.length ?? 0) > 0,
            expandedRowRender: (r) => (
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {r.errors.map((e, i) => (
                  <li key={i}><Typography.Text type="secondary" style={{ fontSize: 12 }}>{e}</Typography.Text></li>
                ))}
              </ul>
            ),
          }}
          columns={[
            { title: '时间', dataIndex: 'started_at', width: 170,
              render: (v: string | null) => v?.slice(0, 19).replace('T', ' ') ?? '—' },
            { title: '触发', dataIndex: 'trigger', width: 80, render: (v) => TRIGGER_LABEL[v] ?? v },
            { title: '状态', dataIndex: 'status', width: 100,
              render: (v: string) => <Tag color={SYNC_STATUS_COLOR[v] ?? 'default'}>{SYNC_STATUS_LABEL[v] ?? v}</Tag> },
            { title: '系统(建/更/跳/败)', width: 180,
              render: (_: unknown, r) => <StatTags stats={r.stats} section="systems" /> },
            { title: '设备(建/更/跳/败)', width: 180,
              render: (_: unknown, r) => <StatTags stats={r.stats} section="devices" /> },
            { title: 'IP(建/跳/败)', width: 150,
              render: (_: unknown, r) => <StatTags stats={r.stats} section="ips" /> },
            { title: '耗时', width: 90,
              render: (_: unknown, r) => (r.started_at && r.finished_at
                ? `${Math.max(1, Math.round((new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 100) / 10)}s`
                : '—') },
          ]}
        />
      </Card>
    </div>
  )
}
