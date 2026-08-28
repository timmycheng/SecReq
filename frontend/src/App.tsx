import { useEffect, useState } from 'react'
import { ConfigProvider, App as AntdApp, Popover, Select, Space, Tag } from 'antd'
import { QuestionCircleOutlined, UserOutlined } from '@ant-design/icons'
import zhCN from 'antd/locale/zh_CN'

import { api, getStoredUsername, storeUsername } from './api'
import type { PlatformUserRow } from './types'
import { EnumsProvider } from './enums'
import { useRoute, navigate } from './router'
import { requestLeave } from './ui/dirtyGuard'
import ProjectListPage from './ui/ProjectListPage'
import WizardPage from './ui/WizardPage'
import ResultPage from './ui/ResultPage'
import ReviewPage from './ui/ReviewPage'

const ROLE_COLOR: Record<string, string> = {
  pm: 'blue', developer: 'geekblue', security_reviewer: 'orange',
  security_lead: 'volcano', risk_manager: 'purple', auditor: 'default',
}

const HELP_CONTENT = (
  <div style={{ maxWidth: 340, fontSize: 13, lineHeight: 1.7 }}>
    <p style={{ margin: 0, fontWeight: 600 }}>整个平台就是三件事:</p>
    <p style={{ margin: '4px 0 0' }}>
      <b>① 填报</b>(项目经理): 新建项目 → 按 1~9 步向导填写 → 一键「生成安全基线」。
    </p>
    <p style={{ margin: '2px 0' }}>
      <b>② 补齐</b>: 在产物页或评审页按提示一键补责任人、确认报送事项 ——
      缺什么, 页面会用红字列出来。
    </p>
    <p style={{ margin: '2px 0' }}>
      <b>③ 评审</b>: 项目经理「提交评审」→ 右上角切换成「陈评审」点审核通过 →
      切换成「赵负责人」终审签核。
    </p>
    <p style={{ margin: '6px 0 0', color: '#888' }}>
      平时不用管右上角身份(默认项目经理); 只有替别人做审核/终审时才需要切换。
    </p>
  </div>
)

/** 顶栏身份切换: 默认自动以「项目经理」身份进入, 替他人操作时才需要切换。 */
function UserSwitcher() {
  const { message } = AntdApp.useApp()
  const [users, setUsers] = useState<PlatformUserRow[]>([])
  const [current, setCurrent] = useState<string | null>(getStoredUsername())

  useEffect(() => {
    api.listUsers().then(setUsers).catch(() => setUsers([]))
  }, [])

  // 首次打开(或身份失效)自动登录为项目经理, 避免新用户遇到"未登录"报错
  useEffect(() => {
    if (current) return
    api.login('pm_wang')
      .then((info) => {
        storeUsername(info.username)
        setCurrent(info.username)
      })
      .catch(() => undefined)
  }, [current])

  const pick = async (username?: string) => {
    if (!username) return
    try {
      const info = await api.login(username)
      storeUsername(username)
      setCurrent(username)
      message.success(`已切换身份: ${info.display_name}(${info.role_label})`)
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const me = users.find((u) => u.username === current)
  return (
    <Space size={10} align="center">
      <Popover content={HELP_CONTENT} title="怎么用?" trigger="click">
        <Tag style={{ cursor: 'pointer' }}>
          <QuestionCircleOutlined /> 怎么用
        </Tag>
      </Popover>
      <UserOutlined />
      <Select
        size="small"
        showSearch
        optionFilterProp="label"
        style={{ minWidth: 200 }}
        placeholder="选择身份"
        value={current ?? undefined}
        onChange={(v) => void pick(v)}
        options={users.map((u) => ({
          value: u.username,
          label: `${u.display_name} · ${u.username}`,
        }))}
      />
      {me && <Tag color={ROLE_COLOR[me.role] ?? 'default'}>{me.role}</Tag>}
    </Space>
  )
}

function Shell() {
  const route = useRoute()
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{ token: { colorPrimary: '#2f5597', borderRadius: 6 } }}
    >
      <AntdApp style={{ minHeight: '100vh', background: '#f5f6fa' }}>
        <div
          style={{
            background: '#001529', color: '#fff', padding: '12px 28px',
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            flexWrap: 'wrap', gap: 8,
          }}
        >
          <div
            onClick={() => void requestLeave().then((ok) => ok && navigate('/'))}
            style={{ fontSize: 18, fontWeight: 600, cursor: 'pointer', letterSpacing: 1 }}
          >
            SecReq · 安全准入管理平台(需求+设计阶段)
          </div>
          <div onClick={(e) => e.stopPropagation()}>
            <UserSwitcher />
          </div>
        </div>
        {route.name === 'list' && <ProjectListPage />}
        {route.name === 'wizard' && <WizardPage key={route.projectId} projectId={route.projectId} />}
        {route.name === 'result' && <ResultPage key={route.projectId} projectId={route.projectId} />}
        {route.name === 'review' && <ReviewPage key={route.projectId} projectId={route.projectId} />}
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
