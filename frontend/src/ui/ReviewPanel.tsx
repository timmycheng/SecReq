/* 评审操作面板共享组件(#283 item8): 产物页与评审中心的右侧固定面板
   (布局模式4「内容区 + 右侧固定评审操作面板」的唯一实现)。
   提交/裁定/门禁拦截提示/审批中与通过提示一套实现, 状态与回调由页面持有;
   #309 单步评审: 安全管理员裁定通过即 passed, 不再有独立终审块。
   页面特有区块经 children(顶部状态区)/withdrawSlot/footer 注入。 */
import type { ReactNode } from 'react'
import { Alert, Button, Card, Input, Popconfirm, Radio, Typography } from 'antd'
import { CheckCircleOutlined } from '@ant-design/icons'
import type { CSSProperties } from 'react'

export interface ReviewPanelProps {
  /** 提交评审被门禁拦截的缺项列表(非空即展示错误块)。 */
  blocked?: string[] | null
  canSubmit: boolean
  gateStatus?: string | null
  acting: boolean
  onSubmit: () => void
  /** true 时不渲染提交按钮(如产物页尚无需求时)。 */
  hideSubmit?: boolean
  /** 提交按钮禁用态(如评审中心需求为空)。 */
  disableSubmit?: boolean
  /** 提供则提交按钮外包确认弹窗(评审中心口径)。 */
  submitConfirmTitle?: string
  canDecide: boolean
  /** 裁定块标题(产物页「整体裁定(安全侧)」/评审中心「整体裁定(评审员)」)。 */
  decideTitle: string
  decide: string | null
  onDecideChange: (v: string | null) => void
  decideComment: string
  onDecideCommentChange: (v: string) => void
  onDecideSubmit: () => void
  /** 审批中的附加块(产物页提交人撤回按钮)。 */
  withdrawSlot?: ReactNode
  /** 顶部状态区: 页面自有描述/进度/汇总。 */
  children?: ReactNode
  /** 底部区块(产物页「评审中心」入口)。 */
  footer?: ReactNode
  auditorHint?: string
  style?: CSSProperties
}

export default function ReviewPanel({
  blocked, canSubmit, gateStatus, acting, onSubmit, hideSubmit, disableSubmit,
  submitConfirmTitle,
  canDecide, decideTitle, decide, onDecideChange, decideComment, onDecideCommentChange,
  onDecideSubmit, withdrawSlot, children, footer, auditorHint, style,
}: ReviewPanelProps) {
  const inReview = gateStatus === 'in_review'
  const submitButton = (
    <Button type="primary" block loading={acting} disabled={disableSubmit} onClick={onSubmit}>
      {gateStatus === 'rectifying' || gateStatus === 'rejected' ? '整改后重新提交评审' : '提交评审'}
    </Button>
  )
  return (
    <Card size="small" title="评审操作面板" style={style}>
      {children}

      {blocked != null && blocked.length > 0 && (
        <Alert
          type="error" showIcon style={{ marginBottom: 12 }}
          message="门禁校验未通过"
          description={
            <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
              {blocked.map((m) => <li key={m}><Typography.Text style={{ fontSize: 12 }}>{m}</Typography.Text></li>)}
            </ul>
          }
        />
      )}

      {canSubmit && !hideSubmit && gateStatus !== 'in_review' && gateStatus !== 'passed' && (
        submitConfirmTitle
          ? (
            <Popconfirm title={submitConfirmTitle} onConfirm={onSubmit}>
              {submitButton}
            </Popconfirm>
          )
          : submitButton
      )}
      {canSubmit && inReview && (
        <>
          <Typography.Text type="secondary">评审进行中, 各项信息已锁定为只读。</Typography.Text>
          {withdrawSlot}
        </>
      )}
      {canSubmit && gateStatus === 'passed' && (
        <Typography.Text type="secondary">
          <CheckCircleOutlined style={{ color: 'var(--ant-color-success, #52c41a)' }} /> 评审已通过, 本轮归档。
        </Typography.Text>
      )}

      {canDecide && (
        <div style={{ marginTop: 12 }}>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>{decideTitle}</Typography.Paragraph>
          <Radio.Group
            value={decide}
            onChange={(e) => onDecideChange(e.target.value)}
            options={[
              { value: 'approve', label: '通过' },
              { value: 'request_change', label: '退回整改' },
              { value: 'reject', label: '否决' },
            ]}
            style={{ marginBottom: 8 }}
          />
          <Input.TextArea
            rows={2} placeholder="裁定意见(可空)" value={decideComment}
            onChange={(e) => onDecideCommentChange(e.target.value)} style={{ marginBottom: 8 }}
          />
          <Button
            type="primary" block disabled={!decide} loading={acting}
            onClick={onDecideSubmit}
          >
            提交裁定
          </Button>
        </div>
      )}

      {auditorHint && (
        <Typography.Text type="secondary">{auditorHint}</Typography.Text>
      )}
      {footer && <div style={{ marginTop: 12 }}>{footer}</div>}
    </Card>
  )
}
