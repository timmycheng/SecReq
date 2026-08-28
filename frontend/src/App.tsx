import { ConfigProvider, App as AntdApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'

import { EnumsProvider } from './enums'
import { useRoute, navigate } from './router'
import { requestLeave } from './ui/dirtyGuard'
import ProjectListPage from './ui/ProjectListPage'
import WizardPage from './ui/WizardPage'
import ResultPage from './ui/ResultPage'

function Shell() {
  const route = useRoute()
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{ token: { colorPrimary: '#2f5597', borderRadius: 6 } }}
    >
      <AntdApp style={{ minHeight: '100vh', background: '#f5f6fa' }}>
        <div
          onClick={() => void requestLeave().then((ok) => ok && navigate('/'))}
          style={{
            background: '#001529', color: '#fff', padding: '14px 28px',
            fontSize: 18, fontWeight: 600, cursor: 'pointer', letterSpacing: 1,
          }}
        >
          SecReq · 安全需求与设计基线生成工具
        </div>
        {route.name === 'list' && <ProjectListPage />}
        {route.name === 'wizard' && <WizardPage key={route.projectId} projectId={route.projectId} />}
        {route.name === 'result' && <ResultPage key={route.projectId} projectId={route.projectId} />}
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
