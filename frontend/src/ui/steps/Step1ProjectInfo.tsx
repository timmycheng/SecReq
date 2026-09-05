/* Step1 评估信息与定级(合并原 1/2/6 三步):
   基本信息与合规目标 → 外部系统连接清单 → 等保定级(问卷内联, 可直接指定)
   → 定级后即时展示密码策略基线与合规要求(可展开覆盖认证策略)。 */
import { useEffect, useRef, useState } from 'react'
import {
  Alert, Button, Card, Checkbox, Col, Collapse, Form, Input, InputNumber, Modal,
  Popconfirm, Radio, Row, Select, Space, Table, Tag, Typography, message,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'

import { api, getStoredUser } from '../../api'
import type { GradingBaseline } from '../../api'
import { labelMapOf, optionsOf, useEnums } from '../../enums'
import type {
  AuthConfigRow, ExternalSystemRow, FilingRow, GradingQuestion, ProjectInfo,
  NetboxSystemRow, SurveyAnswer, SystemRow,
} from '../../types'
import GlossaryTip from '../GlossaryTip'
import NetboxSystemImportModal from '../NetboxSystemImportModal'
import { useRegisterStepHandle } from './stepContext'
import type { StepProps } from '../WizardPage'

const LEVEL_OPTIONS = ['一级', '二级', '三级']

const DEFAULT_CFG: AuthConfigRow = {
  auth_methods: ['password'],
  pwd_min_length: null, pwd_complexity: null, pwd_valid_days: null,
  lockout_threshold: null, pwd_history_limit: null,
  force_2fa: false, session_timeout_min: null, concurrent_limit: null,
}

const EMPTY_EXT: ExternalSystemRow = {
  name: '', purpose: '', direction: 'bidirectional', involves_sensitive: false,
}

export default function Step1ProjectInfo({ ws, patch }: StepProps) {
  const enums = useEnums()
  const isSecurity = getStoredUser()?.role === 'security'
  const [form] = Form.useForm<ProjectInfo>()

  // ── 外部系统 ──
  const [extRows, setExtRows] = useState<ExternalSystemRow[]>(ws.external_systems)
  const [extEditing, setExtEditing] = useState<ExternalSystemRow | null>(null)
  const [extEditIndex, setExtEditIndex] = useState(-1)

  // ── 定级 ──
  const [questions, setQuestions] = useState<GradingQuestion[] | null>(null)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [finalLevel, setFinalLevel] = useState<string | undefined>(undefined)
  const [note, setNote] = useState('')

  // ── 认证与密码策略(原 Step6) ──
  const [cfg, setCfg] = useState<AuthConfigRow>(ws.auth_config ?? DEFAULT_CFG)
  const [baseline, setBaseline] = useState<GradingBaseline | null>(null)

  // ── 所属系统(台账): 绑定在「发起新评估」时确定(#203), 向导内锁定只读(#209/#210);
  //    未归属的存量评估仍可在此绑定(就地新建/NetBox 导入救援), 绑定保存后同样锁定。
  //    已绑定时数据动作默认走「复制上一轮」, 与创建弹窗"按上一轮复制"口径一致(#186)。
  const systemBound = Boolean(ws.project.system_id)
  const [systems, setSystems] = useState<SystemRow[]>([])
  const [filings, setFilings] = useState<FilingRow[]>([])
  const [sysCreating, setSysCreating] = useState(false)
  const [sysImporting, setSysImporting] = useState(false)
  const watchedSystemId = Form.useWatch('system_id', form)
  const selectedSystem = systems.find((s) => s.id === watchedSystemId) ?? null
  const latestRound = selectedSystem?.latest_round ?? selectedSystem?.rounds?.[0] ?? null
  const [copying, setCopying] = useState(false)

  /** 就地复制上一轮(#172): 当前项目已落库, 走 copy-from 先清后拷; 全部步骤数据变化, 整页重载 */
  const doCopyFromLatest = async () => {
    if (!latestRound) return
    setCopying(true)
    try {
      await api.copyProjectFrom(ws.project.id, latestRound.project_id)
      message.success(`已复制「${latestRound.project_name}」的向导数据, 页面将刷新`)
      window.location.reload()
    } catch (e) {
      message.error((e as Error).message)
      setCopying(false)
    }
  }

  /** 一键清空(#172→#210): 已上收到向导吸底导航(WizardPage), 需输入评估编码二次确认 */

  const savedRef = useRef(JSON.stringify(snapshotOf(ws, cfg)))

  function snapshotOf(state: typeof ws, config: AuthConfigRow) {
    return {
      project: {
        name: state.project.name,
        system_id: state.project.system_id ?? null,
        pm_name: state.project.pm_name ?? '',
        dev_lead_name: state.project.dev_lead_name ?? '',
        sec_contact_name: state.project.sec_contact_name ?? '',
        compliance_targets: state.project.compliance_targets ?? [],
      },
      ext: state.external_systems,
      survey: state.survey,
      cfg: config,
    }
  }

  useEffect(() => {
    api.gradingQuestions().then(setQuestions).catch(() => setQuestions([]))
    api.getGradingBaseline(ws.project.id).then(setBaseline).catch(() => undefined)
    api.listSystems().then(setSystems).catch(() => undefined)
    api.listFilings().then(setFilings).catch(() => undefined)
    if (ws.survey) {
      const map: Record<string, string> = {}
      for (const a of ws.survey.answers_json ?? []) map[a.question_id] = a.option_id
      setAnswers(map)
      setFinalLevel(ws.survey.final_level ?? undefined)
      setNote(ws.survey.manual_adjust_note ?? '')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /** 选择系统后: 若尚无任何定级, 用备案定级预填"直接指定等级"。
      仅未归属的存量评估会走到这里(已绑定的 Select 锁定只读, 不可更换)。 */
  const onSystemChange = (systemId: number | undefined) => {
    const target = systems.find((s) => s.id === systemId) ?? null
    if (target?.filing_level && !finalLevel && !ws.survey?.effective_level
      && Object.keys(answers).length === 0) {
      setFinalLevel(target.filing_level)
      message.info(`已按备案「${target.filing_name}」预填定级: 等保${target.filing_level}, 可调整`)
    }
  }

  const reloadBaseline = () => {
    api.getGradingBaseline(ws.project.id).then(setBaseline).catch(() => undefined)
  }

  const save = async (): Promise<boolean> => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return false
    try {
      const detail = await api.patchProject(ws.project.id, values)
      const ext = await api.saveExternalSystems(ws.project.id, extRows)
      // 定级: 已答完问卷则走打分; 未答完但显式选了等级则直接指定; 两者皆无则跳过
      // 旧形态 answers_json 可能缺 option_id(存量数据), 过滤避免整卷提交被 422 拦下(#98)
      const answeredAll = questions ? questions.every((q) => answers[q.id]) : false
      const surveyPayload: SurveyAnswer[] = Object.entries(answers)
        .filter(([, option_id]) => option_id)
        .map(([question_id, option_id]) => ({ question_id, option_id }))
      let level = finalLevel ?? null
      if (questions && surveyPayload.length > 0 && !answeredAll && !level) {
        message.warning('定级问卷未答完: 请答完全部题目, 或清空答案后直接指定等级')
        return false
      }
      if (!surveyPayload.length && !level) {
        level = ws.survey?.effective_level || null // 未改动且已有定级 → 保持
      }
      let freshSurvey = ws.survey
      if (surveyPayload.length || level) {
        await api.saveSurvey(ws.project.id, surveyPayload, level, note || null)
        const fresh = await api.loadWizard(ws.project.id)
        freshSurvey = fresh.survey
      }
      const savedCfg = await api.saveAuthConfig(ws.project.id, cfg)
      patch({
        project: { ...ws.project, ...detail },
        external_systems: ext,
        survey: freshSurvey,
        auth_config: savedCfg,
      })
      savedRef.current = JSON.stringify(snapshotOf({ ...ws, survey: freshSurvey }, cfg))
      message.success('评估信息与定级已保存')
      reloadBaseline()
      return true
    } catch (e) {
      message.error((e as Error).message)
      return false
    }
  }

  useRegisterStepHandle({ save, isDirty: () => JSON.stringify(snapshotOf(ws, cfg)) !== savedRef.current })

  const effectiveLevel = ws.survey?.effective_level || ''
  const pwd = baseline?.pwd_defaults

  return (
    <div style={{ maxWidth: 980, margin: '0 auto' }}>
      {/* ── 基本信息 ── */}
      <Typography.Title level={5}>基本信息</Typography.Title>
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          name: ws.project.name,
          code: ws.project.code,
          system_id: ws.project.system_id ?? undefined,
          types: ws.project.types ?? [],
          pm_name: ws.project.pm_name ?? '',
          dev_lead_name: ws.project.dev_lead_name ?? '',
          sec_contact_name: ws.project.sec_contact_name ?? '',
          compliance_targets: ws.project.compliance_targets ?? [],
        }}
      >
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              name="name" label="评估名称" rules={[{ required: true, message: '请输入评估名称' }]}
            >
              <Input placeholder="如: 个人网银系统" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="code" label="评估编码(自动生成)">
              <Input disabled />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item
          name="system_id"
          label="所属系统(台账)"
          tooltip="归属系统后, 同一系统多次评估在系统台账下形成时间线, 最新一轮即当前基线"
          extra={(
            <Space size={4} wrap>
              {systemBound ? (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  所属系统在发起新评估时绑定, 向导内不可更换
                </Typography.Text>
              ) : (
                <>
                  <span>找不到?</span>
                  <Button type="link" size="small" style={{ padding: 0 }} onClick={() => setSysCreating(true)}>
                    就地新建系统
                  </Button>
                  <span>(登记系统并挂靠定级备案; 规模/类型等基本信息在系统台账维护)</span>
                  {isSecurity && (
                    <Button type="link" size="small" style={{ padding: 0 }} onClick={() => setSysImporting(true)}>
                      从 NetBox 导入
                    </Button>
                  )}
                </>
              )}
              {selectedSystem && (
                latestRound ? (
                  <Button type="link" size="small" style={{ padding: 0 }} loading={copying}
                    onClick={() => void doCopyFromLatest()}>
                    复制上一轮({latestRound.created_at?.slice(0, 10) || latestRound.project_name})
                  </Button>
                ) : (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    该系统暂无历史评估可复制
                  </Typography.Text>
                )
              )}
            </Space>
          )}
        >
          <Select
            showSearch
            disabled={systemBound}
            placeholder="选择该评估所属的系统"
            optionFilterProp="label"
            options={systems.map((s) => ({
              value: s.id,
              label: s.filing_name ? `${s.name}(备案: ${s.filing_name})` : s.name,
            }))}
            onChange={onSystemChange}
          />
        </Form.Item>
        <Form.Item
          name="types" label="评估类型(可多选)"
          extra="系统业务形态在系统台账维护; 此处展示当前系统的类型(评估不再单独填写)"
        >
          <Select mode="multiple" options={optionsOf(enums, 'project_types')} disabled placeholder="在系统台账中维护" />
        </Form.Item>
        <Row gutter={16}>
          <Col span={8}>
            <Form.Item name="pm_name" label="项目经理">
              <Input placeholder="选填" />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="dev_lead_name" label="开发负责人">
              <Input placeholder="选填" />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="sec_contact_name" label="安全对接人">
              <Input placeholder="选填" />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item
          name="compliance_targets" label="合规目标(多选)"
          extra="勾选后按目标生成对应合规要求; 等级保护按最终定级出具测评与备案要求"
        >
          <Checkbox.Group
            options={Object.entries(labelMapOf(enums, 'compliance_targets')).map(([value, label]) => ({
              value, label,
            }))}
          />
        </Form.Item>
      </Form>

      {/* ── 外部系统连接 ── */}
      <Typography.Title level={5} style={{ marginTop: 8 }}>外部系统连接</Typography.Title>
      <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
        与本项目交互的外部系统(如: 支付网关、短信平台、行内核心系统)。有交互即触发边界安全要求,
        涉敏感数据会追加数据交互管控要求; 没有可以留空。
      </Typography.Text>
      <Space style={{ marginBottom: 8 }}>
        <Button size="small" icon={<PlusOutlined />}
          onClick={() => { setExtEditIndex(-1); setExtEditing({ ...EMPTY_EXT }) }}>
          新增外部系统
        </Button>
        <Typography.Text type="secondary">共 {extRows.length} 个</Typography.Text>
      </Space>
      <Table<ExternalSystemRow>
        rowKey={(_, i) => String(i)}
        dataSource={extRows}
        pagination={false}
        size="small"
        columns={[
          { title: '系统名称', dataIndex: 'name' },
          { title: '对接内容/用途', dataIndex: 'purpose' },
          { title: '数据方向', dataIndex: 'direction', width: 150,
            render: (v) => labelMapOf(enums, 'external_system_directions')[v] ?? v },
          { title: '涉敏感数据', dataIndex: 'involves_sensitive', width: 110,
            render: (v: boolean) => (v ? <Tag color="red">是</Tag> : '否') },
          {
            title: '操作', width: 110,
            render: (_v, _r, index) => (
              <Space>
                <Button size="small" icon={<EditOutlined />}
                  onClick={() => { setExtEditIndex(index); setExtEditing({ ...extRows[index] }) }} />
                <Popconfirm title="删除该外部系统?" onConfirm={() => setExtRows(extRows.filter((_, i) => i !== index))}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      {/* ── 等保定级 ── */}
      <Typography.Title level={5} style={{ marginTop: 20 }}>
        <GlossaryTip term="grading">等保定级</GlossaryTip>
      </Typography.Title>
      <Alert
        type={effectiveLevel ? 'success' : 'warning'}
        showIcon
        message={effectiveLevel
          ? `当前生效定级: 等保${effectiveLevel}${ws.survey?.suggested_level && ws.survey.final_level ? '(人工修正)' : ws.survey?.suggested_level ? '(系统建议)' : '(直接指定)'}`
          : '尚未定级: 回答下方问卷自动计算, 或直接指定等级'}
        description={(
          <>
            {ws.survey?.suggested_reason || '定级决定密码策略、加密与审计要求的基线档位'}
            {selectedSystem?.filing_level && (
              <div style={{ marginTop: 4 }}>
                定级来源: 备案「{selectedSystem.filing_name}」(等保{selectedSystem.filing_level});
                若评估后调整定级, 结果页会提示与备案不一致。
              </div>
            )}
          </>
        )}
      />
      <div style={{ marginTop: 12, padding: '12px 16px', border: '1px dashed #d9d9d9', borderRadius: 6 }}>
        <Space size={24} align="center" wrap>
          <span>
            直接指定等级:
            <Select
              allowClear style={{ width: 160, marginLeft: 8 }}
              placeholder="不走问卷时直接选择"
              value={finalLevel}
              options={LEVEL_OPTIONS.map((l) => ({ value: l, label: `等保${l}` }))}
              onChange={(v) => setFinalLevel(v)}
            />
          </span>
          {finalLevel && (
            <Input
              style={{ width: 360 }} placeholder="定级说明(可选, 如: 试点范围有限)"
              value={note} onChange={(e) => setNote(e.target.value)}
            />
          )}
        </Space>
      </div>
      {questions && questions.length > 0 && (
        <Collapse
          style={{ marginTop: 12 }}
          items={[{
            key: 'survey',
            label: `定级问卷(${Object.values(answers).filter(Boolean).length}/${questions.length} 题已答, 答完自动计算建议等级)`,
            children: (
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                {questions.map((q, idx) => (
                  <Alert
                    key={q.id}
                    type={answers[q.id] ? 'info' : 'warning'}
                    message={<b>{idx + 1}. {q.title}</b>}
                    description={(
                      <>
                        <Radio.Group
                          value={answers[q.id]}
                          onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })}
                          options={q.options.map((o) => ({ value: o.id, label: `${o.label}(+${o.score} 分)` }))}
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
                <Typography.Text type="secondary">
                  说明: 答完问卷后点「保存并下一步」, 系统按题库打分给出建议定级;
                  直接指定等级与问卷可任选其一。
                </Typography.Text>
              </Space>
            ),
          }]}
        />
      )}

      {/* 基线要求预览已收敛到第 8 步「试算预览」与结果页, 此处不再逐条重复(#87);
          baseline 仍用于下方「认证与密码策略」卡片的默认档位展示 */}

      {/* ── 认证与密码策略(默认基线, 可展开覆盖) ── */}
      <Card
        size="small"
        style={{ marginTop: 16 }}
        title="认证方式与密码策略"
        extra={pwd ? (
          <Typography.Text type="secondary">
            基线: 最小长度 {pwd.pwd_min_length} · 复杂度 {pwd.pwd_complexity}/4 · 有效期 {pwd.pwd_valid_days} 天
            (留空即按基线)
          </Typography.Text>
        ) : undefined}
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <div>
            <Typography.Text type="secondary">认证方式(多选): </Typography.Text>
            <Checkbox.Group
              value={cfg.auth_methods}
              options={optionsOf(enums, 'auth_methods')}
              onChange={(vals) => setCfg({ ...cfg, auth_methods: vals as string[] })}
            />
          </div>
          <Collapse
            items={[{
              key: 'policy',
              label: '密码与会话策略微调(可选, 默认按定级基线自动取值)',
              children: (
                <Space size={20} wrap>
                  <NumField label="最小长度" value={cfg.pwd_min_length} placeholder={pwd ? `${pwd.pwd_min_length}(默认)` : ''}
                    min={6} max={64} onChange={(v) => setCfg({ ...cfg, pwd_min_length: v })} />
                  <NumField label="有效期(天)" value={cfg.pwd_valid_days} placeholder={pwd ? `${pwd.pwd_valid_days}(默认)` : ''}
                    min={1} max={3650} onChange={(v) => setCfg({ ...cfg, pwd_valid_days: v })} />
                  <NumField label="错误锁定阈值(次)" value={cfg.lockout_threshold} placeholder={pwd ? `${pwd.lockout_threshold}(默认)` : ''}
                    min={1} max={100} onChange={(v) => setCfg({ ...cfg, lockout_threshold: v })} />
                  <NumField label="会话超时(分钟)" value={cfg.session_timeout_min} placeholder={pwd ? `${pwd.session_timeout_min}(默认)` : ''}
                    min={1} max={1440} onChange={(v) => setCfg({ ...cfg, session_timeout_min: v })} />
                  <Checkbox checked={cfg.force_2fa}
                    onChange={(e) => setCfg({ ...cfg, force_2fa: e.target.checked })}>
                    强制双因素认证(2FA)
                  </Checkbox>
                </Space>
              ),
            }]}
          />
        </Space>
      </Card>

      {extEditing !== null && (
        <ExternalSystemModal
          key={`ext-${extEditIndex}-${extEditing.name}`}
          value={extEditing}
          enums={enums}
          onCancel={() => setExtEditing(null)}
          onOk={(next) => {
            const copy = [...extRows]
            if (extEditIndex >= 0) copy[extEditIndex] = next
            else copy.push(next)
            setExtRows(copy)
            setExtEditing(null)
          }}
        />
      )}

      {sysCreating && (
        <>
        {isSecurity && (
        <NetboxSystemImportModal
          open={sysImporting}
          onClose={() => setSysImporting(false)}
          onSelected={(selected: NetboxSystemRow[]) => {
            void (async () => {
              let firstId: number | undefined
              for (const row of selected) {
                const refId = String(row.id)
                const dup = systems.some((sy) => sy.netbox_object_id === refId
                  || sy.name.toLowerCase() === (row.name || '').toLowerCase())
                if (dup) continue
                try {
                  const created = await api.createSystem({
                    name: row.name || `NetBox#${row.id}`,
                    code: row.code ?? undefined,
                    owner_name: row.owner ?? undefined,
                    netbox_object_id: refId,
                  })
                  firstId ??= created.id
                } catch (e) {
                  message.error(`${row.name || refId}: ${(e as Error).message}`)
                }
              }
              setSysImporting(false)
              if (firstId !== undefined) {
                api.listSystems().then(setSystems).catch(() => undefined)
                form.setFieldValue('system_id', firstId)
                message.success('已从 NetBox 导入并选中系统')
              }
            })()
          }}
        />
        )}
        <SystemQuickCreateModal
          filings={filings}
          onClose={() => setSysCreating(false)}
          onCreated={(created) => {
            setSysCreating(false)
            api.listSystems().then((rows) => {
              setSystems(rows)
              form.setFieldValue('system_id', created.id)
              onSystemChange(created.id)
            }).catch(() => undefined)
          }}
        />
        </>
      )}
    </div>
  )
}

/** 就地新建系统: 台账登记(名称/挂靠备案/负责人), 成功后自动选中。 */
function SystemQuickCreateModal({ filings, onClose, onCreated }: {
  filings: FilingRow[]
  onClose: () => void
  onCreated: (s: SystemRow) => void
}) {
  const [form] = Form.useForm<{ name: string; filing_id?: number; owner_name?: string }>()
  return (
    <Modal
      title="就地新建系统" open onCancel={onClose}
      onOk={() => form.validateFields()
        .then(async (v) => {
          try {
            const created = await api.createSystem(v)
            message.success('系统已登记')
            onCreated(created)
          } catch (e) {
            message.error((e as Error).message)
          }
        })
        .catch(() => { /* 校验失败留在弹窗 */ })}
    >
      <Form form={form} layout="vertical">
        <Form.Item name="name" label="系统名称" rules={[{ required: true, message: '请输入系统名称' }]}>
          <Input placeholder="如: 个人网银系统" />
        </Form.Item>
        <Form.Item
          name="filing_id" label="挂靠定级备案"
          extra="挂靠后系统继承备案定级; 备案由安全管理员维护, 暂无合适项可先跳过并联系安全管理员"
        >
          <Select
            allowClear placeholder="选择备案(选填)"
            options={filings.map((f) => ({
              value: f.id, label: `${f.name}(${f.code ? `${f.code} / ` : ''}等保${f.level})`,
            }))}
          />
        </Form.Item>
        <Form.Item name="owner_name" label="系统负责人">
          <Input placeholder="选填" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function ExternalSystemModal({ value, onOk, onCancel, enums }: {
  value: ExternalSystemRow | null
  onOk: (row: ExternalSystemRow) => void
  onCancel: () => void
  enums: ReturnType<typeof useEnums>
}) {
  const [form] = Form.useForm<ExternalSystemRow>()
  return (
    <Modal
      title="外部系统连接" open={value !== null} onCancel={onCancel}
      onOk={() => form.validateFields()
        .then((v) => onOk({ ...(value ?? EMPTY_EXT), ...v }))
        .catch(() => { /* 校验失败留在弹窗 */ })}
      forceRender
    >
      <Form form={form} layout="vertical" initialValues={value ?? EMPTY_EXT}>
        <Form.Item name="name" label="外部系统名称" rules={[{ required: true, message: '请输入名称' }]}>
          <Input placeholder="如: 行内短信平台" />
        </Form.Item>
        <Form.Item name="purpose" label="对接内容/用途">
          <Input placeholder="如: 发送验证码短信" />
        </Form.Item>
        <Form.Item name="direction" label="数据方向" rules={[{ required: true }]}>
          <Select options={optionsOf(enums, 'external_system_directions')} />
        </Form.Item>
        <Form.Item name="involves_sensitive" label="是否传输敏感数据" valuePropName="checked">
          <Checkbox>传输个人敏感信息/金融账户等敏感数据</Checkbox>
        </Form.Item>
      </Form>
    </Modal>
  )
}

function NumField({ label, value, onChange, placeholder, min, max }: {
  label: string
  value: number | null | undefined
  onChange: (v: number | null) => void
  placeholder?: string
  min?: number
  max?: number
}) {
  return (
    <Space direction="vertical" size={0}>
      <Typography.Text type="secondary">{label}</Typography.Text>
      <InputNumber
        style={{ width: 150 }}
        value={value ?? undefined}
        placeholder={placeholder}
        min={min}
        max={max}
        onChange={(v) => onChange(typeof v === 'number' ? v : null)}
      />
    </Space>
  )
}
