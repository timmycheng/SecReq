/* 定级题库: 选项分值与判定依据维护, 保存后对新提交的问卷立即生效。 */
import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Input, InputNumber, Space, Spin, Tag, Typography, message } from 'antd'

import { api, type QuestionBank } from '../../api'

export default function QuestionTab() {
  const [bank, setBank] = useState<QuestionBank | null>(null)
  const [saving, setSaving] = useState(false)

  const reload = useCallback(() => {
    api.getQuestionBank().then(setBank).catch((e: Error) => message.error(e.message))
  }, [])
  useEffect(reload, [reload])

  const save = async () => {
    if (!bank) return
    setSaving(true)
    try {
      await api.saveQuestionBank(bank)
      message.success('题库已保存并即时生效')
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  if (!bank) return <Spin style={{ display: 'block', margin: '40px auto' }} />

  const updateOption = (qi: number, oi: number, patch: Partial<QuestionBank['questions'][0]['options'][0]>) => {
    const copy: QuestionBank = JSON.parse(JSON.stringify(bank))
    Object.assign(copy.questions[qi].options[oi], patch)
    setBank(copy)
  }

  return (
    <>
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        题目分值与组合规则决定自动定级建议。此处调整选项分值; 保存后立即对新提交的问卷生效。
      </Typography.Paragraph>
      {bank.questions.map((q, qi) => (
        <Card
          key={q.id} size="small" title={`${q.id}. ${q.title}`} style={{ marginBottom: 12 }}
          extra={<Tag>命中组合: {bank.levels.find((l) => l.level)?.level ?? ''}</Tag>}
        >
          {q.options.map((o, oi) => (
            <Space key={o.id} size={8} style={{ display: 'flex', marginBottom: 6 }} wrap>
              <Tag style={{ minWidth: 28, textAlign: 'center' }}>{o.id}</Tag>
              <Input style={{ width: 300 }} value={o.label}
                onChange={(e) => updateOption(qi, oi, { label: e.target.value })} />
              <InputNumber min={0} max={20} value={o.score}
                onChange={(v) => updateOption(qi, oi, { score: typeof v === 'number' ? v : 0 })} />
              <Typography.Text type="secondary">分</Typography.Text>
              <Input style={{ width: 320 }} value={o.basis ?? ''} placeholder="判定依据文案"
                onChange={(e) => updateOption(qi, oi, { basis: e.target.value })} />
            </Space>
          ))}
        </Card>
      ))}
      <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid #f0f0f0' }}>
        <Button type="primary" loading={saving} onClick={() => void save()}>保存题库</Button>
      </div>
    </>
  )
}
