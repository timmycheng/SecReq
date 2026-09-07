/* 登录页(#280): 品牌渐变背景 + 白卡; 本地账号或 LDAP/AD 账号均可登录(后端认证顺序见 auth 路由)。 */
import { useState } from 'react'
import { Alert, Button, Form, Input, Typography } from 'antd'
import { LockOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons'

import { api } from '../api'
import type { LoginInfo } from '../types'

export default function LoginPage({ onLogin }: { onLogin: (info: LoginInfo) => void }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const finish = async (values: { username: string; password: string }) => {
    setLoading(true)
    setError(null)
    try {
      onLogin(await api.login(values.username.trim(), values.password))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-bg">
      <div className="login-card">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 28 }}>
          <div className="login-logo"><SafetyCertificateOutlined /></div>
          <div>
            <Typography.Title level={4} style={{ margin: 0 }}>SecReq 安全需求管理平台</Typography.Title>
            <Typography.Text type="secondary">系统安全评估 · 需求自动生成</Typography.Text>
          </div>
        </div>
        {error && <Alert type="error" showIcon style={{ marginBottom: 16 }} message={error} />}
        <Form layout="vertical" onFinish={(v) => void finish(v as { username: string; password: string })}>
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名(本地或 LDAP/AD 账号)" size="large" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" size="large" />
          </Form.Item>
          <Button type="primary" htmlType="submit" size="large" block loading={loading}>登 录</Button>
        </Form>
      </div>
    </div>
  )
}
