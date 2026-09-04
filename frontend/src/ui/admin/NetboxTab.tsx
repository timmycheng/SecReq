/* NetBox 互通(#152): 地址/Token/系统类型 slug/字段映射, 旁路增强不阻塞主流程。
   未配置时显示引导空态; 测试连接对 连接拒绝/超时/认证失败/权限不足 给可读归因。 */
import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Form, Input, Space, Typography, message } from 'antd'

import { api, type NetboxConfig } from '../../api'

export default function NetboxTab() {
  const [cfg, setCfg] = useState<NetboxConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<
    { ok: boolean; latency_ms?: number; version?: string; reason?: string } | null
  >(null)
  const [form] = Form.useForm()

  const reload = useCallback(() => {
    api.getNetboxConfig().then((c) => {
      setCfg(c)
      form.setFieldsValue({
        base_url: c.base_url,
        system_slug: c.system_slug ?? 'system',
        name_key: c.field_map?.name ?? 'name',
        code_key: c.field_map?.code ?? 'code',
        owner_key: c.field_map?.owner ?? 'owner',
      })
    }).catch((e: Error) => message.error(e.message))
  }, [form])
  useEffect(reload, [reload])

  return (
    <div style={{ maxWidth: 640, margin: '0 auto' }}>
      <Alert
        type="info" showIcon style={{ marginBottom: 12 }}
        message="NetBox 是旁路增强, 不是依赖"
        description="未配置或断连时, 系统台账、向导等全部既有流程不受影响; 配置后可从 NetBox
          导入基础设施资产与系统清单, 并可将本系统数据手动推送写回。地址与 Token 只存后端。"
      />
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        目标 NetBox 为 4.x(REST Token 认证); 系统清单来自 netbox-custom-objects 插件,
        类型 slug 默认 system。env 回退: SECREQ_NETBOX_URL / SECREQ_NETBOX_TOKEN。
      </Typography.Paragraph>
      <Form form={form} layout="vertical">
        <Form.Item name="base_url" label="NetBox 地址" extra="如 https://netbox.corp.example.com">
          <Input placeholder="https://..." />
        </Form.Item>
        <Form.Item
          name="token" label="API Token"
          extra={cfg?.token ? `当前: ${cfg.token}` : '未配置'}
        >
          <Input.Password placeholder="Token 只存后端, 回显仅前 4 位" />
        </Form.Item>
        <Form.Item
          name="system_slug" label="系统对象类型 slug"
          extra="custom-objects 插件的类型标识, 与内网实例一致(默认 system)"
        >
          <Input placeholder="system" />
        </Form.Item>
        <Space size={12} style={{ display: 'flex' }}>
          <Form.Item name="name_key" label="名称字段" style={{ width: 140 }}>
            <Input placeholder="name" />
          </Form.Item>
          <Form.Item name="code_key" label="编码字段" style={{ width: 140 }}>
            <Input placeholder="code" />
          </Form.Item>
          <Form.Item name="owner_key" label="负责人字段" style={{ width: 140 }}>
            <Input placeholder="owner" />
          </Form.Item>
        </Space>
        <Space>
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
        </Space>
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
    </div>
  )
}
