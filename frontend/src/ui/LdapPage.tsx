/* LDAP/AD 对接(#280 新功能): 对接企业目录服务, 统一身份认证与用户导入。
   配置存后端 system_settings; 连接测试只测不存; 密码只写不读(留空沿用)。
   用户导入入口在 用户管理 → LDAP 导入。仅安全角色可达。 */
import { useCallback, useEffect, useState } from 'react'
import {
  Alert, Button, Card, Form, Input, InputNumber, Select, Space, Switch, Typography, message,
} from 'antd'
import { ApiOutlined } from '@ant-design/icons'

import { api } from '../api'
import type { LdapConfigRow, LdapTestResult } from '../types'
import PageHeader from './PageHeader'
import { TestResultAlert, useAsyncAction } from './common'

export default function LdapPage() {
  const [form] = Form.useForm()
  const save = useAsyncAction()
  const test = useAsyncAction()
  const [testResult, setTestResult] = useState<LdapTestResult | null>(null)
  const [hasPassword, setHasPassword] = useState(false)

  const reload = useCallback(() => {
    api.getLdapConfig().then((cfg: LdapConfigRow) => {
      form.setFieldsValue({ ...cfg, bind_password: '' })
      setHasPassword(Boolean(cfg.has_password))
    }).catch((e: Error) => message.error(e.message))
  }, [form])
  useEffect(reload, [reload])

  const collect = async () => {
    const values = await form.validateFields()
    // 测试用提交值: 强制按启用态测试(保存前也能测); 密码留空表示沿用已保存密码
    return { ...values, enabled: true, bind_password: values.bind_password || undefined }
  }

  return (
    <div style={{ padding: 24 }}>
      <PageHeader
        title="LDAP / AD 对接"
        description="对接企业目录服务, 实现统一身份认证; 目录用户可在 用户管理 → LDAP 导入"
        extra={(
          <Space>
            <Button
              icon={<ApiOutlined />} loading={test.busy}
              onClick={() => {
                setTestResult(null)
                void test.run(async () => {
                  setTestResult(await api.testLdapConfig(await collect()))
                })
              }}
            >
              连接测试
            </Button>
            <Button
              type="primary" loading={save.busy}
              onClick={() => void save.run(async () => {
                const values = await form.validateFields()
                await api.saveLdapConfig({ ...values, bind_password: values.bind_password || '' })
                reload()
              }, '配置已保存')}
            >
              保存配置
            </Button>
          </Space>
        )}
      />
      {/* DESIGN: 页面整体居中 */}
      <Form form={form} layout="vertical" style={{ maxWidth: 860, margin: '0 auto' }} initialValues={{ port: 389 }}>
        <Card title="对接配置" style={{ marginBottom: 16 }}>
          <Form.Item name="enabled" label="启用 LDAP/AD 登录" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0 32px' }}>
            <Form.Item name="host" label="服务器地址" rules={[{ required: true, message: '请输入服务器地址' }]}>
              <Input placeholder="ldap:// 或 ldaps:// 主机名" />
            </Form.Item>
            <Form.Item name="port" label="端口" rules={[{ required: true }]}>
              <InputNumber min={1} max={65535} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="base_dn" label="Base DN" rules={[{ required: true, message: '请输入 Base DN' }]}>
              <Input placeholder="dc=bank,dc=com,dc=cn" />
            </Form.Item>
            <Form.Item name="bind_dn" label="管理员 Bind DN">
              <Input placeholder="cn=svc-secreq,ou=service,…" />
            </Form.Item>
            <Form.Item
              name="bind_password" label="管理员密码"
              extra={hasPassword ? '已保存; 留空表示沿用' : '首次配置必填'}
            >
              <Input.Password placeholder={hasPassword ? '••••••(留空沿用)' : 'svc-secret'} />
            </Form.Item>
            <Form.Item name="user_filter" label="用户过滤规则">
              <Input placeholder="(objectClass=person)" />
            </Form.Item>
          </div>
        </Card>

        <Card title="属性映射" style={{ marginBottom: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0 32px' }}>
            <Form.Item name="attr_username" label="用户名属性">
              <Select options={['uid', 'sAMAccountName', 'cn'].map((v) => ({ value: v, label: v }))} />
            </Form.Item>
            <Form.Item name="attr_display_name" label="姓名属性">
              <Select options={['cn', 'displayName', 'name'].map((v) => ({ value: v, label: v }))} />
            </Form.Item>
            <Form.Item name="attr_email" label="邮箱属性">
              <Select options={['mail', 'userPrincipalName'].map((v) => ({ value: v, label: v }))} />
            </Form.Item>
          </div>
        </Card>

        <Card title="登录策略">
          <Form.Item
            name="allow_local_fallback"
            label="允许本地账号登录(目录服务不可用时的兜底)"
            valuePropName="checked"
          >
            <Switch checkedChildren="允许" unCheckedChildren="禁止" />
          </Form.Item>
          <Alert
            type="info" showIcon
            message="目录认证通过会自动开通同名本地账号(默认开发侧角色); 关闭本地兜底后, 登录一律走目录认证。"
          />
        </Card>
      </Form>

      <TestResultAlert
        result={testResult}
        style={{ marginTop: 16, maxWidth: 860, marginInline: 'auto' }}
        successDescription={`命中 ${testResult?.user_count ?? 0} 个目录用户`}
      />
      <Typography.Text type="secondary" style={{ display: 'block', marginTop: 12, maxWidth: 860, marginInline: 'auto' }}>
        密码策略与账号锁定沿用目录服务配置; 保存后立即对登录生效。
      </Typography.Text>
    </div>
  )
}
