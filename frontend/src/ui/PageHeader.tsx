/**
 * 统一页头(布局模式「PageHeader: 标题+主操作」, #268):
 * 左侧标题(可选返回按钮/描述文字), 右侧操作区(主按钮/筛选)。
 * 列表/详情/管理页一律用它, 不再各页面自拼「返回按钮 + Typography.Title」。
 */
import type { ReactNode } from 'react'
import { Button, Space, Typography } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'

export default function PageHeader({ title, description, extra, onBack, backLabel = '返回' }: {
  title: ReactNode
  description?: ReactNode
  extra?: ReactNode
  onBack?: () => void
  backLabel?: string
}) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, marginBottom: 16 }}>
      <div style={{ minWidth: 0 }}>
        <Space align="center" size={12}>
          {onBack && (
            <Button icon={<ArrowLeftOutlined />} onClick={onBack}>{backLabel}</Button>
          )}
          <Typography.Title level={4} style={{ margin: 0 }}>{title}</Typography.Title>
        </Space>
        {description && (
          <Typography.Text type="secondary" style={{ display: 'block', marginTop: 4 }}>
            {description}
          </Typography.Text>
        )}
      </div>
      {extra && <Space wrap style={{ flexShrink: 0, justifyContent: 'flex-end' }}>{extra}</Space>}
    </div>
  )
}
