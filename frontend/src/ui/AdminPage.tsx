/* 系统管理(仅安全角色): 知识库/定级题库/策略基线/大模型接入/漏洞库/用户/审计, 共七个 Tab。

   各 Tab 拆分为 src/ui/admin/ 下各自独立的组件, 本文件只保留外壳与路由;
   Tab 组件经 React.lazy 按需加载, 切换到哪个 Tab 才下载并渲染对应代码(#40)。 */
import { Suspense, lazy } from 'react'
import { Card, Result, Spin, Tabs } from 'antd'

import { getStoredUser, isSecuritySideRole } from '../api'
import PageHeader from './PageHeader'

const KbTab = lazy(() => import('./admin/KbTab'))
const QuestionTab = lazy(() => import('./admin/QuestionTab'))
const FilingsTab = lazy(() => import('./admin/FilingsTab'))
const PolicyTab = lazy(() => import('./admin/PolicyTab'))
const LlmTab = lazy(() => import('./admin/LlmTab'))
const NetboxTab = lazy(() => import('./admin/NetboxTab'))
const VulnDbTab = lazy(() => import('./admin/VulnDbTab'))
const UsersTab = lazy(() => import('./admin/UsersTab'))
const AuditTab = lazy(() => import('./admin/AuditTab'))
const SystemSettingsTab = lazy(() => import('./admin/SystemSettingsTab'))
const ChangelogTab = lazy(() => import('./admin/ChangelogTab'))

/** Tab 切换时的加载态: 统一占位, 避免各 Tab 自己写一遍 Spin。 */
function TabLoading() {
  return (
    <div style={{ display: 'grid', placeItems: 'center', minHeight: 240 }}>
      <Spin tip="正在加载…" />
    </div>
  )
}

export default function AdminPage() {
  // 后端安全侧角色(评审员/负责人)可访问(#216); 前端同步给其他角色明确的 403 提示
  if (!isSecuritySideRole(getStoredUser()?.role)) {
    return (
      <div style={{ minHeight: '60vh', display: 'grid', placeItems: 'center', padding: 24 }}>
        <Card style={{ width: '100%', maxWidth: 480 }}>
          <Result status="403" title="403" subTitle="系统管理仅安全角色可访问" />
        </Card>
      </div>
    )
  }
  return (
    <div style={{ padding: 24 }}>
      <PageHeader
        title="系统管理"
        description={
          '知识库、定级题库、定级备案、密码策略基线、大模型接入、离线漏洞库、用户、' +
          '审计日志、系统设置与更新日志的统一维护入口(仅安全角色)'
        }
      />
      <Card variant="borderless">
        <Suspense fallback={<TabLoading />}>
          <Tabs
            items={[
              { key: 'kb', label: '知识库', children: <KbTab /> },
              { key: 'vulndb', label: '漏洞库', children: <VulnDbTab /> },
              { key: 'questions', label: '定级题库', children: <QuestionTab /> },
              { key: 'filings', label: '定级备案', children: <FilingsTab /> },
              { key: 'policy', label: '密码策略基线', children: <PolicyTab /> },
              { key: 'llm', label: '大模型接入', children: <LlmTab /> },
              { key: 'netbox', label: 'NetBox 互通', children: <NetboxTab /> },
              { key: 'users', label: '用户管理', children: <UsersTab /> },
              { key: 'audit', label: '审计日志', children: <AuditTab /> },
              { key: 'settings', label: '系统设置', children: <SystemSettingsTab /> },
              { key: 'changelog', label: '更新日志', children: <ChangelogTab /> },
            ]}
          />
        </Suspense>
      </Card>
    </div>
  )
}
