/* 系统管理(仅安全角色, #280 收编): 其余管理页已独立为平台设置菜单组,
   本页只保留 系统设置(评估编号规则 + 密码策略基线 + 定级题库)与 漏洞库 两个 Tab。

   各 Tab 拆分为 src/ui/admin/ 下各自独立的组件, 本文件只保留外壳;
   Tab 组件经 React.lazy 按需加载, 切换到哪个 Tab 才下载并渲染对应代码(#40)。 */
import { Suspense, lazy } from 'react'
import { Card, Result, Spin, Tabs } from 'antd'

import { getStoredUser, isSecuritySideRole } from '../api'
import PageHeader from './PageHeader'

const VulnDbTab = lazy(() => import('./admin/VulnDbTab'))
const SystemSettingsTab = lazy(() => import('./admin/SystemSettingsTab'))

/** Tab 切换时的加载态: 统一占位, 避免各 Tab 自己写一遍 Spin。 */
function TabLoading() {
  return (
    <div style={{ display: 'grid', placeItems: 'center', minHeight: 240 }}>
      <Spin tip="正在加载…" />
    </div>
  )
}

export default function AdminPage() {
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
        description="评估编号规则、密码策略基线、定级题库与离线漏洞库的统一维护入口"
      />
      <Card variant="borderless">
        <Suspense fallback={<TabLoading />}>
          <Tabs
            items={[
              { key: 'settings', label: '系统设置', children: <SystemSettingsTab /> },
              { key: 'vulndb', label: '漏洞库', children: <VulnDbTab /> },
            ]}
          />
        </Suspense>
      </Card>
    </div>
  )
}
