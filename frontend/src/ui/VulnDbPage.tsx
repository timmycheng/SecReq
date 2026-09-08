/* 漏洞库(#285 自系统管理页拆出): 离线漏洞库版本/生态覆盖/记录数/校验与导入。
   内容组件在 ui/admin/(React.lazy 按需加载, #40); 403 由 App 外壳统一兜底。 */
import { Suspense, lazy } from 'react'
import { Spin } from 'antd'

import PageHeader from './PageHeader'

const VulnDbTab = lazy(() => import('./admin/VulnDbTab'))

export default function VulnDbPage() {
  return (
    <div style={{ padding: 24 }}>
      <PageHeader
        title="漏洞库"
        description="离线漏洞库的版本、生态覆盖、完整性校验与手动导入"
      />
      <Suspense fallback={<Spin style={{ display: 'block', margin: '48px auto' }} />}>
        <VulnDbTab />
      </Suspense>
    </div>
  )
}
