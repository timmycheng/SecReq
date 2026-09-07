/**
 * 统一页头(布局模式「PageHeader: 标题+主操作」, #268; #280 对齐原型):
 * 左侧返回图标 + 标题 + 描述, 右侧操作区。列表/详情/管理页一律用它。
 */
import type { ReactNode } from 'react'
import { Button, Space, Typography } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'

export default function PageHeader({ title, description, extra, onBack }: {
  title: ReactNode
  description?: ReactNode
  extra?: ReactNode
  onBack?: () => void
}) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, marginBottom: 16 }}>
      <div style={{ minWidth: 0 }}>
        <Space align="center" size={8}>
          {onBack && (
            <Button type="text" icon={<ArrowLeftOutlined />} onClick={onBack} aria-label="返回" />
          )}
          <Typography.Title level={4} style={{ margin: 0 }}>{title}</Typography.Title>
        </Space>
        {description && (
          <Typography.Paragraph type="secondary" style={{ marginTop: 4, marginBottom: 0 }}>
            {description}
          </Typography.Paragraph>
        )}
      </div>
      {extra && <Space wrap style={{ flexShrink: 0, justifyContent: 'flex-end' }}>{extra}</Space>}
    </div>
  )
}
