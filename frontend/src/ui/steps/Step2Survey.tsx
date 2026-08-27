/* Step2 等保定级问卷: 题库来自 /api/meta/grading-questions,
   提交后展示系统建议定级与判定理由, 允许人工修正最终定级。 */
import { useEffect, useState } from 'react'
import {
  Alert, Button, Input, Radio, Select, Space, Spin, Typography, message,
} from 'antd'

import { api } from '../../api'
import type { GradingQuestion, SurveyAnswer } from '../../types'
import type { StepProps } from '../WizardPage'

const LEVEL_OPTIONS = ['一级', '二级', '三级']

export default function Step2Survey({ ws, patch, advance }: StepProps) {
  const [questions, setQuestions] = useState<GradingQuestion[] | null>(null)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [finalLevel, setFinalLevel] = useState<string | undefined>(undefined)
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.gradingQuestions().then(setQuestions).catch((e: Error) => message.error(e.message))
    if (ws.survey) {
      const existing: Record<string, string> = {}
      for (const a of ws.survey.answers_json ?? []) existing[a.question_id] = a.option_id
      setAnswers(existing)
      if (ws.survey.final_level) {
        setFinalLevel(ws.survey.final_level)
        setNote(ws.survey.manual_adjust_note ?? '')
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!questions) return <Spin />

  const answeredAll = questions.every((q) => answers[q.id])

  const save = async () => {
    if (!answeredAll) {
      message.warning('请先完成全部题目作答')
      return
    }
    setSaving(true)
    try {
      const payload: SurveyAnswer[] =
        Object.entries(answers).map(([question_id, option_id]) => ({ question_id, option_id }))
      await api.saveSurvey(ws.project.id, payload, finalLevel || null, note || null)
      // 保存后重拉向导状态以获取建议定级/理由
      const fresh = await api.loadWizard(ws.project.id)
      patch({ survey: fresh.survey })
      message.success('问卷已提交')
      advance()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ maxWidth: 860 }}>
      <Typography.Paragraph type="secondary">
        每题选项带分值, 系统按题库加权计算输出建议定级; 定级结果将作为密码策略、加密策略的默认基线。
      </Typography.Paragraph>

      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {questions.map((q, idx) => (
          <Alert
            key={q.id}
            type={((ws.survey?.suggested_level && answers[q.id]) ? 'info' : undefined)}
            message={<b>{idx + 1}. {q.title}</b>}
            description={(
              <>
                <Radio.Group
                  value={answers[q.id]}
                  onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })}
                  options={[
                    ...q.options.map((o) => ({
                      value: o.id,
                      label: `${o.label}（+${o.score} 分）`,
                    })),
                  ]}
                />
                {answers[q.id] && (
                  <Typography.Text type="secondary" style={{ display: 'block', marginTop: 4 }}>
                    判定依据: {q.options.find((o) => o.id === answers[q.id])?.basis}
                  </Typography.Text>
                )}
              </>
            )}
          />
        ))}
      </Space>

      {ws.survey?.suggested_level && !anyAnswerChanged(questions, answers, ws.survey.answers_json) && (
        <Alert
          style={{ marginTop: 16 }}
          type="success"
          message={`系统建议定级: 等保${ws.survey.suggested_level}（当前生效: ${ws.survey.effective_level || '未定'}）`}
          description={ws.survey.suggested_reason}
        />
      )}

      <div style={{ marginTop: 16, padding: '12px 16px', border: '1px dashed #d9d9d9', borderRadius: 6 }}>
        <Space size={24} align="center" wrap>
          <span>
            人工修正最终定级(留空则采用系统建议):
            <Select
              allowClear
              style={{ width: 160, marginLeft: 8 }}
              placeholder="选择定级"
              value={finalLevel}
              options={LEVEL_OPTIONS.map((l) => ({ value: l, label: `等保${l}` }))}
              onChange={(v) => setFinalLevel(v)}
            />
          </span>
          {finalLevel && (
            <Input
              style={{ width: 360 }}
              placeholder="修正说明(如: 试点范围有限, 降低一级)"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          )}
        </Space>
      </div>

      <Button type="primary" loading={saving} onClick={save} style={{ marginTop: 16 }} disabled={!answeredAll}>
        提交问卷并下一步
      </Button>
    </div>
  )
}

function anyAnswerChanged(
  questions: GradingQuestion[],
  current: Record<string, string>,
  saved: SurveyAnswer[],
): boolean {
  if (!saved) return true
  return questions.some((q) => {
    const prev = saved.find((a) => a.question_id === q.id)?.option_id
    return current[q.id] !== prev
  })
}
