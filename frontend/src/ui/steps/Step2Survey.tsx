/* Step2 等保定级问卷: 题库来自 /api/meta/grading-questions,
   提交后展示系统建议定级与判定理由, 允许人工修正最终定级。 */
import { useEffect, useState } from 'react'
import {
  Alert, Input, Radio, Select, Space, Spin, Typography, message,
} from 'antd'

import { api } from '../../api'
import type { GradingQuestion, SurveyAnswer, SurveyOut } from '../../types'
import { useRegisterStepHandle } from './stepContext'
import type { StepProps } from '../WizardPage'

const LEVEL_OPTIONS = ['一级', '二级', '三级']

export default function Step2Survey({ ws, patch }: StepProps) {
  const [questions, setQuestions] = useState<GradingQuestion[] | null>(null)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [finalLevel, setFinalLevel] = useState<string | undefined>(undefined)
  const [note, setNote] = useState('')

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

  const savedOf = (s: SurveyOut | null) => {
    const map: Record<string, string> = {}
    for (const a of s?.answers_json ?? []) map[a.question_id] = a.option_id
    return {
      answers: map,
      finalLevel: s?.final_level ?? undefined,
      note: s?.manual_adjust_note ?? '',
    }
  }

  const save = async (): Promise<boolean> => {
    if (!questions) return false
    const unanswered = questions.length - questions.filter((q) => answers[q.id]).length
    if (unanswered > 0) {
      message.warning(`还有 ${unanswered} 题未作答, 题目已用橙色标出`)
      return false
    }
    try {
      const payload: SurveyAnswer[] =
        Object.entries(answers).map(([question_id, option_id]) => ({ question_id, option_id }))
      await api.saveSurvey(ws.project.id, payload, finalLevel || null, note || null)
      // 保存后重拉向导状态以获取建议定级/理由
      const fresh = await api.loadWizard(ws.project.id)
      patch({ survey: fresh.survey })
      message.success('问卷已提交')
      return true
    } catch (e) {
      message.error((e as Error).message)
      return false
    }
  }

  useRegisterStepHandle({
    save,
    isDirty: () => {
      if (!questions) return false
      const saved = savedOf(ws.survey)
      return questions.some((q) => answers[q.id] !== saved.answers[q.id])
        || finalLevel !== saved.finalLevel
        || note !== saved.note
    },
  })

  if (!questions) return <Spin />

  const answeredCount = questions.filter((q) => answers[q.id]).length
  const changed = anyAnswerChanged(questions, answers, ws.survey)

  return (
    <div style={{ maxWidth: 860, margin: '0 auto' }}>
      <Space style={{ justifyContent: 'space-between', display: 'flex' }}>
        <Typography.Text type="secondary">
          每题选项带分值, 系统按题库加权计算输出建议定级; 定级结果将作为密码策略、加密策略的默认基线。
        </Typography.Text>
        <Typography.Text type={answeredCount === questions.length ? 'secondary' : 'warning'}>
          已答 {answeredCount}/{questions.length} 题
        </Typography.Text>
      </Space>

      <Space direction="vertical" size={16} style={{ width: '100%', marginTop: 8 }}>
        {questions.map((q, idx) => (
          <Alert
            key={q.id}
            type={answers[q.id] ? 'info' : 'warning'}
            message={<b>{idx + 1}. {q.title}{!answers[q.id] && <span style={{ fontWeight: 400 }}> (未作答)</span>}</b>}
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

      {ws.survey?.suggested_level && (
        <Alert
          style={{ marginTop: 16 }}
          type={changed ? 'info' : 'success'}
          showIcon
          message={`系统建议定级: 等保${ws.survey.suggested_level}（当前生效: ${ws.survey.effective_level || '未定'}）`}
          description={changed
            ? `${ws.survey.suggested_reason}（答案已修改, 重新提交后将按新答案计算）`
            : ws.survey.suggested_reason}
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
    </div>
  )
}

function anyAnswerChanged(
  questions: GradingQuestion[],
  current: Record<string, string>,
  saved: SurveyOut | null,
): boolean {
  if (!saved) return true
  return questions.some((q) => {
    const prev = saved.answers_json?.find((a) => a.question_id === q.id)?.option_id
    return current[q.id] !== prev
  })
}
