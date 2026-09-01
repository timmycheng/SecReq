/* 系统管理(仅安全角色): 知识库/定级题库/策略基线/大模型接入/漏洞库/用户/审计, 共七个 Tab。

   各 Tab 拆分为 src/ui/admin/ 下各自独立的组件, 本文件只保留外壳与路由;
   Tab 组件经 React.lazy 按需加载, 切换到哪个 Tab 才下载并渲染对应代码(#40)。 */
import { Suspense, lazy } from 'react'
import { Card, Result, Spin, Tabs, Typography } from 'antd'

import { getStoredUser } from '../api'

const KbTab = lazy(() => import('./admin/KbTab'))
const QuestionTab = lazy(() => import('./admin/QuestionTab'))
const PolicyTab = lazy(() => import('./admin/PolicyTab'))
const LlmTab = lazy(() => import('./admin/LlmTab'))
const VulnDbTab = lazy(() => import('./admin/VulnDbTab'))
const UsersTab = lazy(() => import('./admin/UsersTab'))
const AuditTab = lazy(() => import('./admin/AuditTab'))

/** Tab 切换时的加载态: 统一占位, 避免各 Tab 自己写一遍 Spin。 */
function TabLoading() {
  return (
    <div style={{ display: 'grid', placeItems: 'center', minHeight: 240 }}>
      <Spin tip="正在加载…" />
    </div>
  )
}

export default function AdminPage() {
  // 后端仅安全角色可访问; 前端同步给非安全角色明确的 403 提示
  if (getStoredUser()?.role !== 'security') {
    return (
      <div style={{ minHeight: '60vh', display: 'grid', placeItems: 'center', padding: 24 }}>
        <Card style={{ width: '100%', maxWidth: 480 }}>
          <Result status="403" title="403" subTitle="系统管理仅安全角色可访问" />
        </Card>
      </div>
    )
  }
  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: 24 }}>
      <div style={{ marginBottom: 16 }}>
        <Typography.Title level={4} style={{ marginBottom: 4 }}>系统管理</Typography.Title>
        <Typography.Text type="secondary">
          知识库、定级题库、密码策略基线、大模型接入、离线漏洞库与用户、审计日志的统一维护入口(仅安全角色)
        </Typography.Text>
      </div>
      <Card>
        <Suspense fallback={<TabLoading />}>
          <Tabs
            items={[
              { key: 'kb', label: '知识库', children: <KbTab /> },
              { key: 'vulndb', label: '漏洞库', children: <VulnDbTab /> },
              { key: 'questions', label: '定级题库', children: <QuestionTab /> },
              { key: 'policy', label: '密码策略基线', children: <PolicyTab /> },
              { key: 'llm', label: '大模型接入', children: <LlmTab /> },
              { key: 'users', label: '用户管理', children: <UsersTab /> },
              { key: 'audit', label: '审计日志', children: <AuditTab /> },
            ]}
          />
        </Suspense>
      </Card>
    </div>
  )
}
