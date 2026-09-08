/* 系统设置(#280 收编): 评估编号规则(前缀/年份/位数, #85) + 密码策略基线 + 定级题库,
   三块以分组卡片纵向排布; 密码策略与题库原为独立 Tab, 业务逻辑原样迁入。
   编号规则未配置时后端回退历史格式 XM<年份>-<三位序号>, 老评估编号不受影响。 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, Card, Checkbox, Form, Input, InputNumber, Select, Space, Spin, Tag, Typography, message } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'

import { api, type PolicyBaselines, type QuestionBank } from '../../api'
import { NumField } from './shared'
import { useAsyncAction } from '../common'

export default function SystemSettingsTab() {
  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <CodeRuleCard />
      <PolicyBaselineCard />
      <QuestionBankCard />
      <InfraEnvsCard />
      <SystemDictsCard />
    </Space>
  )
}

/* ── 评估编号规则 ──────────────────────────────────── */

interface CodeRule {
  prefix: string
  include_year: boolean
  digits: number
}

function CodeRuleCard() {
  const [rule, setRule] = useState<CodeRule | null>(null)
  const save = useAsyncAction()
  const [form] = Form.useForm<CodeRule>()

  const reload = useCallback(() => {
    api.getProjectCodeRule()
      .then((r) => { setRule(r); form.setFieldsValue(r) })
      .catch((e: Error) => message.error(e.message))
  }, [form])
  useEffect(reload, [reload])

  const watched = Form.useWatch([], form)
  const preview = useMemo(() => {
    const current = watched ?? rule
    if (!current?.prefix) return '—'
    const year = new Date().getFullYear()
    const digits = typeof current.digits === 'number' ? current.digits : 3
    return `${current.prefix}${current.include_year ? year : ''}-${'0'.repeat(Math.max(digits - 1, 0))}1`
  }, [watched, rule])

  return (
    <Card
      size="small" title="评估编号规则"
      extra={<Typography.Text type="secondary">修改规则只影响新评估</Typography.Text>}
    >
      <Form form={form} layout="vertical" initialValues={rule ?? undefined}>
        <Space size={16} wrap align="start">
          <Form.Item
            name="prefix" label="前缀(1-10 位字母数字)"
            rules={[{ required: true }, { pattern: /^[A-Za-z0-9]+$/, message: '仅字母数字' }]}
          >
            <Input placeholder="如 XM / PRJ" maxLength={10} style={{ width: 160 }} />
          </Form.Item>
          <Form.Item name="include_year" valuePropName="checked" style={{ marginTop: 30 }}>
            <Checkbox>编号包含当前年份</Checkbox>
          </Form.Item>
          <Form.Item name="digits" label="序号位数" extra="1-6 位, 不足补零">
            <InputNumber min={1} max={6} style={{ width: 100 }} />
          </Form.Item>
          <Form.Item label="下一个编号" style={{ marginTop: 0 }}>
            <Typography.Text code>{preview}</Typography.Text>
          </Form.Item>
        </Space>
        <div>
          <Button
            type="primary" size="small" loading={save.busy}
            onClick={() => void save.run(async () => {
              const values = await form.validateFields()
              setRule(await api.saveProjectCodeRule(values))
            }, '编号规则已保存')}
          >
            保存规则
          </Button>
        </div>
      </Form>
    </Card>
  )
}

/* ── 密码策略基线(原 PolicyTab 逻辑迁入) ───────────── */

function PolicyBaselineCard() {
  const [data, setData] = useState<PolicyBaselines | null>(null)
  const save = useAsyncAction()

  useEffect(() => {
    api.getPolicyBaselines().then(setData).catch((e: Error) => message.error(e.message))
  }, [])

  if (!data) return <Spin style={{ display: 'block', margin: '24px auto' }} />

  const update = (level: string, key: string, value: number | null) => {
    const copy = structuredClone(data)
    if (value !== null) copy.baselines[level][key as keyof PolicyBaselines['baselines'][string]] = value
    setData(copy)
  }

  return (
    <Card
      size="small" title="密码策略基线"
      extra={<Typography.Text type="secondary">评估未显式覆盖时按档位默认取值</Typography.Text>}
    >
      {Object.entries(data.baselines).map(([level, base]) => (
        <Card key={level} type="inner" size="small" title={`等保${level}`} style={{ marginBottom: 12 }}>
          <Space size={24} wrap>
            <NumField label="最小长度" value={base.pwd_min_length}
              onChange={(v) => update(level, 'pwd_min_length', v)} />
            <NumField label="复杂度类别数" value={base.pwd_complexity}
              onChange={(v) => update(level, 'pwd_complexity', v)} />
            <NumField label="有效期(天)" value={base.pwd_valid_days}
              onChange={(v) => update(level, 'pwd_valid_days', v)} />
          </Space>
        </Card>
      ))}
      <Space size={24} style={{ marginBottom: 16 }} wrap>
        <NumField label="全局锁定阈值(次)" value={data.lockout_threshold}
          onChange={(v) => v !== null && setData({ ...data, lockout_threshold: v })} />
        <NumField label="全局会话超时(分钟)" value={data.session_timeout_min}
          onChange={(v) => v !== null && setData({ ...data, session_timeout_min: v })} />
      </Space>
      <div>
        <Button
          type="primary" size="small" loading={save.busy}
          onClick={() => void save.run(() => api.savePolicyBaselines(data), '策略基线已保存')}
        >
          保存基线
        </Button>
      </div>
    </Card>
  )
}

/* ── 定级题库(原 QuestionTab 逻辑迁入) ─────────────── */

function QuestionBankCard() {
  const [bank, setBank] = useState<QuestionBank | null>(null)
  const save = useAsyncAction()

  useEffect(() => {
    api.getQuestionBank().then(setBank).catch((e: Error) => message.error(e.message))
  }, [])

  if (!bank) return <Spin style={{ display: 'block', margin: '24px auto' }} />

  const updateOption = (qi: number, oi: number, patch: Partial<QuestionBank['questions'][0]['options'][0]>) => {
    const copy = structuredClone(bank)
    Object.assign(copy.questions[qi].options[oi], patch)
    setBank(copy)
  }

  return (
    <Card
      size="small" title="定级题库"
      extra={<Typography.Text type="secondary">题目分值决定自动定级建议, 保存后对新问卷立即生效</Typography.Text>}
    >
      <Card size="small" type="inner" title="定级阈值(总分 → 等级建议)" style={{ marginBottom: 12 }}>
        <Space size={8} wrap>
          {bank.levels.map((l) => (
            <Tag key={l.level}>{l.level}: 总分 ≥ {l.min_score}</Tag>
          ))}
        </Space>
      </Card>
      {bank.questions.map((q, qi) => (
        <Card
          key={q.id} type="inner" size="small" title={`${q.id}. ${q.title}`} style={{ marginBottom: 12 }}
          extra={<Tag>本题最高 {Math.max(0, ...q.options.map((o) => o.score))} 分</Tag>}
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
      <Button
        type="primary" size="small" loading={save.busy}
        onClick={() => bank && void save.run(() => api.saveQuestionBank(bank), '题库已保存并即时生效')}
      >
        保存题库
      </Button>
    </Card>
  )
}

/* ── 基础资源环境(#289, DESIGN 分环境可配置) ────────── */

interface InfraEnv {
  code: string
  name: string
}

function InfraEnvsCard() {
  const [envs, setEnvs] = useState<InfraEnv[] | null>(null)
  const [initialCodes, setInitialCodes] = useState<Set<string>>(new Set())
  const save = useAsyncAction()

  useEffect(() => {
    api.getInfraEnvs().then((r) => {
      setEnvs(r.envs)
      setInitialCodes(new Set(r.envs.map((e) => e.code)))
    }).catch((e: Error) => message.error(e.message))
  }, [])

  if (!envs) return <Spin style={{ display: 'block', margin: '24px auto' }} />

  const update = (index: number, patch: Partial<InfraEnv>) => {
    setEnvs(envs.map((e, i) => (i === index ? { ...e, ...patch } : e)))
  }

  return (
    <Card
      size="small" title="基础资源环境"
      extra={<Typography.Text type="secondary">评估向导与系统详情的基础设施环境列表</Typography.Text>}
    >
      <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
        环境 code 存入资产与架构图数据, 已有环境的 code 不可改; 移除环境不会删除已有数据, 重新添加同 code 环境即可恢复展示。
      </Typography.Text>
      <Space direction="vertical" size={8} style={{ width: '100%', marginBottom: 12 }}>
        {envs.map((e, i) => (
          <Space key={initialCodes.has(e.code) ? e.code : `new-${i}`} size={8} style={{ display: 'flex' }}>
            <Input
              style={{ width: 180 }} placeholder="code(如 sit)"
              disabled={initialCodes.has(e.code)}
              value={e.code} maxLength={20}
              onChange={(ev) => update(i, { code: ev.target.value.toLowerCase() })}
            />
            <Input
              style={{ width: 240 }} placeholder="名称(如 SIT 环境)"
              value={e.name} maxLength={30}
              onChange={(ev) => update(i, { name: ev.target.value })}
            />
            <Button
              size="small" danger icon={<DeleteOutlined />} disabled={envs.length <= 1}
              onClick={() => setEnvs(envs.filter((_, idx) => idx !== i))}
            />
          </Space>
        ))}
      </Space>
      <Space>
        <Button size="small" icon={<PlusOutlined />} onClick={() => setEnvs([...envs, { code: '', name: '' }])}>
          添加环境
        </Button>
        <Button
          type="primary" size="small" loading={save.busy}
          onClick={() => void save.run(async () => {
            const bad = envs.find((e) => !/^[a-z0-9_-]{1,20}$/.test(e.code) || !e.name.trim())
            if (bad) throw new Error(`环境配置不合法: code 需为小写字母/数字且非空, 名称非空(问题在「${bad.code || '未填写 code'}」)`)
            const dup = envs.find((e, i) => envs.findIndex((x) => x.code === e.code) !== i)
            if (dup) throw new Error(`环境 code 重复: ${dup.code}`)
            setEnvs((await api.saveInfraEnvs(envs)).envs)
            setInitialCodes(new Set(envs.map((e) => e.code)))
          }, '基础资源环境已保存')}
        >
          保存环境
        </Button>
      </Space>
    </Card>
  )
}


/* ── 系统字典(#283, DESIGN 系统标签/系统类型枚举设置) ── */

interface DictType {
  code: string
  label: string
}

function SystemDictsCard() {
  const [tags, setTags] = useState<string[] | null>(null)
  const [types, setTypes] = useState<DictType[] | null>(null)
  const save = useAsyncAction()

  useEffect(() => {
    api.getSystemDicts().then((d) => {
      setTags(d.tags)
      setTypes(Object.entries(d.types).map(([code, label]) => ({ code, label })))
    }).catch((e: Error) => message.error(e.message))
  }, [])

  if (!tags || !types) return <Spin style={{ display: 'block', margin: '24px auto' }} />

  return (
    <Card
      size="small" title="系统字典(标签 / 系统类型枚举)"
      extra={<Typography.Text type="secondary">系统清单的标签与业务类型下拉来源; 类型 code 录入后不可改</Typography.Text>}
    >
      <Typography.Paragraph type="secondary" style={{ marginBottom: 4 }}>系统标签:</Typography.Paragraph>
      <Select
        mode="tags" style={{ width: '100%', marginBottom: 16 }} placeholder="输入标签后回车, 可删除"
        value={tags}
        options={tags.map((t) => ({ value: t, label: t }))}
        onChange={(v: string[]) => setTags(v)}
      />
      <Typography.Paragraph type="secondary" style={{ marginBottom: 4 }}>
        系统类型枚举(code 为小写字母/数字/下划线, 用于存储与规则触发; 未配置时回退内置枚举):
      </Typography.Paragraph>
      <Space direction="vertical" size={8} style={{ width: '100%', marginBottom: 12 }}>
        {types.map((t, i) => (
          <Space key={t.code} size={8} style={{ display: 'flex' }}>
            <Input
              style={{ width: 220 }} value={t.code} disabled
              addonBefore="code"
            />
            <Input
              style={{ width: 300 }} value={t.label} placeholder="显示名(如 业务平台)"
              onChange={(e) => setTypes(types.map((x, idx) => (idx === i ? { ...x, label: e.target.value } : x)))}
            />
            <Button
              size="small" danger icon={<DeleteOutlined />} disabled={types.length <= 1}
              onClick={() => setTypes(types.filter((_, idx) => idx !== i))}
            />
          </Space>
        ))}
      </Space>
      <Space>
        <Button
          size="small" icon={<PlusOutlined />}
          onClick={() => setTypes([...types, { code: `custom_${Date.now().toString(36)}`, label: '' }])}
        >
          添加类型
        </Button>
        <Button
          type="primary" size="small" loading={save.busy}
          onClick={() => void save.run(async () => {
            const bad = types.find((t) => !t.label.trim())
            if (bad) throw new Error(`类型「${bad.code}」显示名为空`)
            const res = await api.saveSystemDicts({ tags, types })
            setTypes(Object.entries(res.types).map(([code, label]) => ({ code, label })))
          }, '系统字典已保存')}
        >
          保存字典
        </Button>
      </Space>
    </Card>
  )
}
