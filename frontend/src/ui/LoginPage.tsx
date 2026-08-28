/* 登录页: 账号+密码, 登录成功回调 App 进入主界面。 */
import { useState } from 'react'
import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { LockOutlined, SafetyOutlined, UserOutlined } from '@ant-design/icons'

import { api } from '../api'
import type { LoginInfo } from '../types'

export default function LoginPage({ onLogin }: { onLogin: (info: LoginInfo) => void }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (values: { username: string; password: string }) => {
    setLoading(true)
    setError(null)
    try {
      const info = await api.login(values.username.trim(), values.password)
      onLogin(info)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh', display: 'grid', placeItems: 'center',
        background: 'linear-gradient(160deg, #10234a 0%, #2f5597 60%, #3d6db8 100%)',
      }}
    >
      <Card style={{ width: 380, boxShadow: '0 12px 40px rgba(0,0,0,0.25)' }}>
        <div style={{ textAlign: 'center', marginBottom: 20 }}>
          <SafetyOutlined style={{ fontSize: 40, color: '#2f5597' }} />
          <Typography.Title level={4} style={{ margin: '10px 0 2px' }}>
            安全需求管理平台
          </Typography.Title>
          <Typography.Text type="secondary">请使用行内账号登录</Typography.Text>
        </div>
        {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 14 }} />}
        <Form layout="vertical" onFinish={(v) => void submit(v as { username: string; password: string })}>
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" autoFocus size="large" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" size="large" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block size="large" loading={loading}>
            登 录
          </Button>
        </Form>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 14, marginBottom: 0 }}>
          演示账号: dev_li(开发) / sec_chen(安全), 初始密码 Sec123456, 登录后可在右上角修改。
        </Typography.Paragraph>
      </Card>
    </div>
  )
}
