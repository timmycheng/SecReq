/* Step1 项目基本信息(含合规目标多选)。 */
import { useState } from 'react'
import { Form, Input, Select, Space, Switch, message } from 'antd'

import { api } from '../../api'
import { optionsOf, useEnums } from '../../enums'
import { useRegisterStepHandle } from './stepContext'
import type { StepProps } from '../WizardPage'
import type { ProjectInfo } from '../../types'

export default function Step1BasicInfo({ ws, patch }: StepProps) {
  const enums = useEnums()
  const [form] = Form.useForm<ProjectInfo>()
  const [dirty, setDirty] = useState(false)

  const save = async (): Promise<boolean> => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return false
    try {
      const detail = await api.patchProject(ws.project.id, values)
      patch({ project: detail })
      message.success('项目信息已保存')
      setDirty(false)
      return true
    } catch (e) {
      message.error((e as Error).message)
      return false
    }
  }

  useRegisterStepHandle({ save, isDirty: () => dirty })

  return (
    <Form
      form={form}
      layout="vertical"
      style={{ maxWidth: 720, margin: '0 auto' }}
      onValuesChange={() => setDirty(true)}
      onFinish={() => void save()}
      initialValues={{
        name: ws.project.name,
        code: ws.project.code,
        type: ws.project.type,
        industry: ws.project.industry ?? '银行业',
        user_scale: ws.project.user_scale,
        deploy_env: ws.project.deploy_env ?? [],
        is_public: ws.project.is_public,
        offshore_vendor: ws.project.offshore_vendor ?? false,
        pm_name: ws.project.pm_name ?? '',
        dev_lead_name: ws.project.dev_lead_name ?? '',
        sec_contact_name: ws.project.sec_contact_name ?? '',
        compliance_targets: ws.project.compliance_targets ?? [],
      }}
    >
      <Space size={16} style={{ display: 'flex' }} align="start">
        <Form.Item
          name="name" label="项目名称" rules={[{ required: true, message: '请输入项目名称' }]}
          style={{ flex: '0 0 340px' }}
        >
          <Input placeholder="如: 个人网银系统" />
        </Form.Item>
        <Form.Item name="code" label="项目编码(不可修改)" style={{ flex: '0 0 220px' }}>
          <Input disabled />
        </Form.Item>
      </Space>

      <Space size={16} style={{ display: 'flex' }} align="start">
        <Form.Item name="type" label="项目类型" rules={[{ required: true }]} style={{ width: 200 }}>
          <Select options={optionsOf(enums, 'project_types')} />
        </Form.Item>
        <Form.Item name="user_scale" label="用户规模" rules={[{ required: true }]} style={{ width: 200 }}>
          <Select options={optionsOf(enums, 'user_scales')} />
        </Form.Item>
        <Form.Item name="deploy_env" label="部署环境(多选)" style={{ minWidth: 280 }}>
          <Select mode="multiple" options={optionsOf(enums, 'deploy_envs')} />
        </Form.Item>
      </Space>

      <Form.Item name="industry" label="所属业务条目" style={{ maxWidth: 720 }}>
        <Input placeholder="如: 零售金融-个人业务条线" />
      </Form.Item>

      <Space size={16} style={{ display: 'flex' }}>
        <Form.Item name="pm_name" label="项目经理"><Input /></Form.Item>
        <Form.Item name="dev_lead_name" label="开发负责人"><Input /></Form.Item>
        <Form.Item name="sec_contact_name" label="安全对接人"><Input /></Form.Item>
      </Space>

      <Space size={16} style={{ display: 'flex' }} align="center">
        <Form.Item name="is_public" label="是否涉及公网访问" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Form.Item
          name="offshore_vendor" label="存在境外外包/供应商" valuePropName="checked"
          tooltip="勾选后触发《数据出境安全评估申报》监管报送类需求"
        >
          <Switch />
        </Form.Item>
        <Form.Item name="compliance_targets" label="合规目标(多选)" style={{ minWidth: 400 }}>
          <Select mode="multiple" options={optionsOf(enums, 'compliance_targets')} placeholder="如: 等保三级、个人信息保护法" />
        </Form.Item>
      </Space>
    </Form>
  )
}
