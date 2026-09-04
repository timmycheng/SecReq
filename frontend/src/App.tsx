/* 应用外壳: 未登录显示登录页; 已登录为 dashboard 布局(左侧菜单 + 顶栏用户区)。 */
import { useEffect, useState } from 'react'
import {
  Avatar, ConfigProvider, App as AntdApp, Dropdown, Layout, Menu, Popover, Space, Tag,
} from 'antd'
import {
  ApartmentOutlined, CloudServerOutlined, QuestionCircleOutlined, SettingOutlined,
  UnorderedListOutlined, UserOutlined,
} from '@ant-design/icons'
import zhCN from 'antd/locale/zh_CN'

import { api, AUTH_EXPIRED_EVENT, clearAuth, getStoredToken, getStoredUser, storeAuth } from './api'
import type { StoredUser } from './api'
import { EnumsProvider } from './enums'
import { useRoute, navigate } from './router'
import { requestLeave } from './ui/dirtyGuard'
import ChangePasswordModal from './ui/ChangePasswordModal'
import LoginPage from './ui/LoginPage'
import ProjectListPage from './ui/ProjectListPage'
import SystemsPage from './ui/SystemsPage'
import SystemDetailPage from './ui/SystemDetailPage'
import WizardPage from './ui/WizardPage'
import ResultPage from './ui/ResultPage'
import AdminPage from './ui/AdminPage'
import type { LoginInfo } from './types'

const HELP_CONTENT = (
  <div style={{ maxWidth: 340, fontSize: 13, lineHeight: 1.7 }}>
    <p style={{ margin: 0, fontWeight: 600 }}>整个平台就是两件事:</p>
    <p style={{ margin: '4px 0 0' }}>
      <b>① 填报</b>(开发): 新建项目 → 按向导逐步填写 → 一键「生成安全基线」。
    </p>
    <p style={{ margin: '2px 0' }}>
      <b>② 确认</b>: 在产物页逐条/批量确认安全需求, 补齐报送事项确认 ——
      缺什么, 页面会用红字列出来。
    </p>
    <p style={{ margin: '6px 0 0', color: '#888' }}>
      开发只能看到自己创建的项目; 安全角色可以看到全部项目。
    </p>
  </div>
)

function AppBody() {
  const { message } = AntdApp.useApp()
  const route = useRoute()
  const [user, setUser] = useState<StoredUser | null>(getStoredUser())
  const [pwdOpen, setPwdOpen] = useState(false)

  // token 已过期时(任何请求 401)回到登录页
  useEffect(() => {
    const onExpired = () => {
      clearAuth()
      setUser(null)
    }
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired)
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired)
  }, [])

  // 有本地 token 时先验证一次, 失效立即回登录页
  useEffect(() => {
    if (getStoredToken()) void api.me().catch(() => undefined)
  }, [])

  const onLogin = (info: LoginInfo) => {
    storeAuth(info) // 持久化 token 与用户信息(缺失将导致登录后被守卫弹回登录页)
    setUser({
      username: info.username,
      display_name: info.display_name,
      role: info.role,
      role_label: info.role_label,
    })
    message.success(`欢迎, ${info.display_name}(${info.role_label})`)
  }

  const logout = async () => {
    try { await api.logout() } catch { /* 会话可能已失效 */ }
    clearAuth()
    setUser(null)
  }

  if (!user || !getStoredToken()) {
    return (
      <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: '#2f5597', borderRadius: 6 } }}>
        <AntdApp>
          <LoginPage onLogin={onLogin} />
        </AntdApp>
      </ConfigProvider>
    )
  }

  const menuKey
    = route.name === 'admin' ? 'admin'
      : route.name === 'systems' || route.name === 'systemDetail' ? 'systems'
        : 'projects'
  const userMenu = {
    items: [
      { key: 'pwd', icon: <SettingOutlined />, label: '修改密码' },
      { type: 'divider' as const },
      { key: 'logout', icon: <UserOutlined />, label: '退出登录' },
    ],
    onClick: ({ key }: { key: string }) => {
      if (key === 'pwd') setPwdOpen(true)
      if (key === 'logout') void logout()
    },
  }

  return (
    <>
      <Layout style={{ minHeight: '100vh' }}>
        <Layout.Sider theme="dark" width={200}>
          <div
            onClick={() => void requestLeave().then((ok) => ok && navigate('/'))}
            style={{
              color: '#fff', fontSize: 16, fontWeight: 600, letterSpacing: 1,
              padding: '16px 16px 12px', cursor: 'pointer', whiteSpace: 'nowrap',
            }}
          >
            安全需求管理平台
          </div>
          <Menu
            theme="dark" mode="inline" selectedKeys={[menuKey]}
            onClick={({ key }) => {
              if (key === 'projects') void requestLeave().then((ok) => ok && navigate('/'))
              if (key === 'systems') void requestLeave().then((ok) => ok && navigate('/systems'))
              if (key === 'admin') navigate('/admin')
            }}
            items={[
              { key: 'projects', icon: <UnorderedListOutlined />, label: '项目管理' },
              { key: 'systems', icon: <ApartmentOutlined />, label: '系统台账' },
              ...(user.role === 'security'
                ? [{ key: 'admin', icon: <CloudServerOutlined />, label: '系统管理' }]
                : []),
            ]}
          />
        </Layout.Sider>
        <Layout>
          <Layout.Header
            style={{
              background: '#fff', padding: '0 24px', display: 'flex',
              justifyContent: 'flex-end', alignItems: 'center', gap: 16,
              borderBottom: '1px solid #f0f0f0',
            }}
          >
            <Popover content={HELP_CONTENT} title="怎么用?" trigger="click">
              <Tag style={{ cursor: 'pointer' }}>
                <QuestionCircleOutlined /> 怎么用
              </Tag>
            </Popover>
            <Dropdown menu={userMenu}>
              <Space style={{ cursor: 'pointer' }} size={8}>
                <Avatar size={28} icon={<UserOutlined />} style={{ background: '#2f5597' }} />
                <span>{user.display_name}</span>
                <Tag color={user.role === 'security' ? 'orange' : 'geekblue'}>{user.role_label}</Tag>
              </Space>
            </Dropdown>
          </Layout.Header>
          <Layout.Content style={{ background: '#f5f6fa' }}>
            {route.name === 'list' && <ProjectListPage />}
            {route.name === 'systems' && <SystemsPage />}
            {route.name === 'systemDetail' && <SystemDetailPage key={route.systemId} systemId={route.systemId} />}
            {route.name === 'wizard' && <WizardPage key={route.projectId} projectId={route.projectId} />}
            {route.name === 'result' && <ResultPage key={route.projectId} projectId={route.projectId} />}
            {route.name === 'admin' && <AdminPage />}
          </Layout.Content>
        </Layout>
      </Layout>
      <ChangePasswordModal open={pwdOpen} onClose={() => setPwdOpen(false)} />
    </>
  )
}

function Shell() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{ token: { colorPrimary: '#2f5597', borderRadius: 6 } }}
    >
      <AntdApp style={{ minHeight: '100vh' }}>
        <AppBody />
      </AntdApp>
    </ConfigProvider>
  )
}

export default function App() {
  return (
    <EnumsProvider>
      <Shell />
    </EnumsProvider>
  )
}
