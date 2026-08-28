/* 修改本人密码: 成功后服务端吊销全部会话, 需用新密码重新登录。 */
import { useState } from 'react'
import { Form, Input, Modal, message } from 'antd'

import { api, clearAuth } from '../api'

export default function ChangePasswordModal({ open, onClose }: {
  open: boolean
  onClose: () => void
}) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      const res = await api.changePassword(values.old_password, values.new_password)
      message.success(res.message)
      clearAuth()
      window.location.hash = ''
      onClose()
      window.dispatchEvent(new Event('secreq:auth-expired'))
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="修改密码"
      open={open}
      onCancel={() => { form.resetFields(); onClose() }}
      onOk={() => void submit()}
      confirmLoading={saving}
      okText="确认修改"
      destroyOnClose
    >
      <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
        <Form.Item name="old_password" label="原密码" rules={[{ required: true, message: '请输入原密码' }]}>
          <Input.Password />
        </Form.Item>
        <Form.Item
          name="new_password" label="新密码(至少8位)"
          rules={[{ required: true, message: '请输入新密码' }, { min: 8, message: '至少8位' }]}
        >
          <Input.Password />
        </Form.Item>
        <Form.Item
          name="confirm" label="确认新密码" dependencies={['new_password']}
          rules={[
            { required: true, message: '请再次输入新密码' },
            ({ getFieldValue }) => ({
              validator: (_, v) =>
                v === getFieldValue('new_password')
                  ? Promise.resolve()
                  : Promise.reject(new Error('两次输入不一致')),
            }),
          ]}
        >
          <Input.Password />
        </Form.Item>
      </Form>
    </Modal>
  )
}
