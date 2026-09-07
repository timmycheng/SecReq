/* 应用外壳(#280 改版): 未登录显示登录页; 已登录为分组侧边菜单(工作台/安全管理/平台设置)
   + 顶部面包屑与用户区。平台设置组仅安全角色可见, 路由层再做一次 403 兜底。 */
import { useEffect, useMemo, useState } from 'react'
import {
  App as AntdApp, Avatar, Breadcrumb, ConfigProvider, Dropdown, Layout, Menu, Result,
  Space, Tag,
} from 'antd'
import {
  ApartmentOutlined, BookOutlined, CheckCircleOutlined, ClusterOutlined, FileDoneOutlined,
  FileTextOutlined, HistoryOutlined, HomeOutlined, LinkOutlined, LogoutOutlined,
  RobotOutlined, SafetyCertificateOutlined, SettingOutlined, TeamOutlined, UserOutlined,
} from '@ant-design/icons'
import type { MenuProps } from 'antd'
import zhCN from 'antd/locale/zh_CN'

import { api, AUTH_EXPIRED_EVENT, clearAuth, getStoredToken, getStoredUser, isSecuritySideRole, storeAuth } from './api'
import type { StoredUser } from './api'
import { USER_STORAGE_KEY } from './api'
import { EnumsProvider } from './enums'
import { useRoute, navigate } from './router'
import type { Route } from './router'
import { requestLeave } from './ui/dirtyGuard'
import { themeConfig } from './ui/theme'
import { ROLE_COLOR } from './ui/tokens'
import ChangePasswordModal from './ui/ChangePasswordModal'
import LoginPage from './ui/LoginPage'
import DashboardPage from './ui/DashboardPage'
import SystemsPage from './ui/SystemsPage'
import SystemDetailPage from './ui/SystemDetailPage'
import ProjectListPage from './ui/ProjectListPage'
import WizardPage from './ui/WizardPage'
import ResultPage from './ui/ResultPage'
import ReviewPage from './ui/ReviewPage'
import AdminPage from './ui/AdminPage'
import FilingsPage from './ui/FilingsPage'
import KnowledgePage from './ui/KnowledgePage'
import UsersPage from './ui/UsersPage'
import LdapPage from './ui/LdapPage'
import LlmPage from './ui/LlmPage'
import NetboxPage from './ui/NetboxPage'
import AuditPage from './ui/AuditPage'
import ChangelogPage from './ui/ChangelogPage'
import type { LoginInfo } from './types'

const { Sider, Header, Content } = Layout

/** 侧边菜单: 分组标签 + 扁平条目(#280, 不再使用可展开子菜单)。 */
interface MenuGroup {
  label: string
  /** securityOnly: 仅安全角色可见(平台设置组整组)。 */
  securityOnly?: boolean
  items: { key: string; label: string; icon: React.ReactNode }[]
}

const MENUS: MenuGroup[] = [
  {
    label: '工作台',
    items: [{ key: '/', label: '安全工作台', icon: <HomeOutlined /> }],
  },
  {
    label: '安全管理',
    items: [
      { key: '/systems', label: '系统清单', icon: <ApartmentOutlined /> },
      { key: '/evaluations', label: '评估清单', icon: <CheckCircleOutlined /> },
    ],
  },
  {
    label: '平台设置',
    securityOnly: true,
    items: [
      { key: '/admin', label: '系统管理', icon: <SettingOutlined /> },
      { key: '/filings', label: '备案管理', icon: <FileDoneOutlined /> },
      { key: '/knowledge', label: '知识库管理', icon: <BookOutlined /> },
      { key: '/users', label: '用户管理', icon: <TeamOutlined /> },
      { key: '/ldap', label: 'LDAP/AD 对接', icon: <LinkOutlined /> },
      { key: '/llm', label: 'LLM 管理', icon: <RobotOutlined /> },
      { key: '/netbox', label: 'Netbox 管理', icon: <ClusterOutlined /> },
      { key: '/audit', label: '日志审计', icon: <FileTextOutlined /> },
      { key: '/changelog', label: '更新日志', icon: <HistoryOutlined /> },
    ],
  },
]

/** 菜单 key → 面包屑名。 */
const CRUMB: Record<string, string> = {
  systems: '系统清单', evaluations: '评估清单', admin: '系统管理', filings: '备案管理',
  knowledge: '知识库管理', users: '用户管理', ldap: 'LDAP/AD 对接', llm: 'LLM 管理',
  netbox: 'Netbox 管理', audit: '日志审计', changelog: '更新日志',
}

/** 平台设置组路由 → 页面组件(安全角色专用, 外壳统一 403 兜底)。 */
const SECURITY_ROUTES: Partial<Record<Route['name'], React.ReactNode>> = {
  admin: <AdminPage />,
  filings: <FilingsPage />,
  knowledge: <KnowledgePage />,
  users: <UsersPage />,
  ldap: <LdapPage />,
  llm: <LlmPage />,
  netbox: <NetboxPage />,
  audit: <AuditPage />,
  changelog: <ChangelogPage />,
}

function renderPage(route: Route, isSecurity: boolean) {
  if (route.name in SECURITY_ROUTES) {
    return isSecurity
      ? SECURITY_ROUTES[route.name]
      : <Result status="403" title="403" subTitle="该页面仅安全角色可访问" style={{ padding: 64 }} />
  }
  switch (route.name) {
    case 'dashboard': return <DashboardPage />
    case 'systems': return <SystemsPage />
    case 'systemDetail': return <SystemDetailPage key={route.systemId} systemId={route.systemId} />
    case 'evaluations': return <ProjectListPage />
    case 'wizard': return <WizardPage key={route.projectId} projectId={route.projectId} />
    case 'result': return <ResultPage key={route.projectId} projectId={route.projectId} />
    case 'review': return <ReviewPage key={route.projectId} projectId={route.projectId} />
    default: return <DashboardPage />
  }
}

function AppBody() {
  const { message } = AntdApp.useApp()
  const route = useRoute()
  const [user, setUser] = useState<StoredUser | null>(getStoredUser())
  const [pwdOpen, setPwdOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const isSecurity = isSecuritySideRole(user?.role)

  // token 已过期时(任何请求 401)回到登录页
  useEffect(() => {
    const onExpired = () => {
      clearAuth()
      setUser(null)
    }
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired)
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired)
  }, [])

  // 有本地 token 时先验证一次, 失效立即回登录页; 刷新登录态并为旧版本会话回填 id(#219)
  useEffect(() => {
    if (!getStoredToken()) return
    api.me().then((info) => {
      if (!info) return
      const next: StoredUser = {
        id: info.id, username: info.username, display_name: info.display_name,
        role: info.role, role_label: info.role_label,
      }
      setUser(next)
      localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(next))
    }).catch(() => undefined)
  }, [])

  const onLogin = (info: LoginInfo) => {
    storeAuth(info) // 持久化 token 与用户信息(缺失将导致登录后被守卫弹回登录页)
    setUser({
      id: info.id,
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

  const selectedKey = useMemo(() => {
    if (route.name === 'systemDetail') return '/systems'
    if (route.name === 'wizard' || route.name === 'result' || route.name === 'review') return '/evaluations'
    const seg = route.name === 'dashboard' ? '/' : `/${route.name}`
    return seg
  }, [route])

  if (!user || !getStoredToken()) {
    // 主题与 AntdApp 上下文均由 Shell 单点提供, 登录页不再重复挂载(#268)
    return <LoginPage onLogin={onLogin} />
  }

  const goMenu = (key: string) => {
    void requestLeave().then((ok) => ok && navigate(key))
  }

  const menuItems: MenuProps['items'] = MENUS
    .filter((g) => !g.securityOnly || isSecurity)
    .map((g) => ({
      type: 'group' as const,
      label: g.label,
      children: g.items,
    }))

  const crumbs = [{ title: '首页', href: '#/' }]
  const crumbKey = selectedKey === '/' ? '' : CRUMB[selectedKey.slice(1)] ?? ''
  if (crumbKey) {
    crumbs.push({
      title: route.name === 'systemDetail' ? '系统详情'
        : route.name === 'wizard' ? '评估问卷'
          : route.name === 'result' ? '评估产物'
            : route.name === 'review' ? '评审中心'
              : crumbKey,
      href: route.name === 'systemDetail' || route.name === 'wizard'
          || route.name === 'result' || route.name === 'review' ? `#${selectedKey}` : '',
    })
  }

  const userMenu = {
    items: [
      { key: 'pwd', icon: <SettingOutlined />, label: '修改密码' },
      { type: 'divider' as const },
      { key: 'logout', icon: <LogoutOutlined />, label: '退出登录' },
    ],
    onClick: ({ key }: { key: string }) => {
      if (key === 'pwd') setPwdOpen(true)
      if (key === 'logout') void logout()
    },
  }

  return (
    <>
      <Layout style={{ minHeight: '100vh' }}>
        <Sider
          className="sidebar" collapsible
          collapsed={collapsed} onCollapse={setCollapsed}
          theme="dark" width={216}
        >
          <div
            className="brand-block"
            onClick={() => goMenu('/')}
            style={{ height: 56, paddingLeft: collapsed ? 20 : 24, cursor: 'pointer' }}
          >
            <div className="brand-logo"><SafetyCertificateOutlined /></div>
            {!collapsed && <b style={{ fontSize: 15 }}>SecReq</b>}
          </div>
          <Menu
            theme="dark" mode="inline" items={menuItems}
            selectedKeys={[selectedKey]}
            onClick={({ key }) => goMenu(String(key))}
          />
        </Sider>
        <Layout>
          <Header
            style={{
              background: '#fff', padding: '0 24px', display: 'flex',
              alignItems: 'center', justifyContent: 'space-between',
              borderBottom: '1px solid #f0f0f0', height: 56, lineHeight: '56px',
            }}
          >
            <Breadcrumb items={crumbs.map((c) => ({ title: c.href ? <a href={c.href}>{c.title}</a> : c.title }))} />
            <Dropdown menu={userMenu}>
              <Space style={{ cursor: 'pointer' }} size={8}>
                <Avatar size={28} icon={<UserOutlined />} style={{ background: 'var(--secreq-primary)' }} />
                <span>{user.display_name}</span>
                <Tag color={ROLE_COLOR[user.role] ?? 'default'}>{user.role_label}</Tag>
              </Space>
            </Dropdown>
          </Header>
          <Content>
            <div style={{ maxWidth: 1440, margin: '0 auto' }}>{renderPage(route, isSecurity)}</div>
          </Content>
        </Layout>
      </Layout>
      <ChangePasswordModal open={pwdOpen} onClose={() => setPwdOpen(false)} />
    </>
  )
}

function Shell() {
  return (
    <ConfigProvider locale={zhCN} theme={themeConfig}>
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
