/* 系统设置(#285 自系统管理页拆出): 评估编号规则 + 密码策略基线 + 定级题库。
   内容组件在 ui/admin/(React.lazy 按需加载, #40); 403 由 App 外壳统一兜底。 */
import { Suspense, lazy } from 'react'
import { Spin } from 'antd'

import PageHeader from './PageHeader'

const SystemSettingsTab = lazy(() => import('./admin/SystemSettingsTab'))

export default function SystemSettingsPage() {
  return (
    <div style={{ padding: 24 }}>
      <PageHeader
        title="系统设置"
        description="评估编号规则、密码策略基线与定级题库的统一维护入口"
      />
      <Suspense fallback={<Spin style={{ display: 'block', margin: '48px auto' }} />}>
        <SystemSettingsTab />
      </Suspense>
    </div>
  )
}
