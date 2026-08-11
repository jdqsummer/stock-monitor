import { useState } from 'react';
import { Button, Form, Input, Modal, message } from 'antd';
import { LockOutlined, MailOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import { authApi } from '@/api/client';
import { getErrorMessage } from '@/utils/error';

interface ForgotPasswordModalProps {
  open: boolean;
  onClose: () => void;
}

export function ForgotPasswordModal({ open, onClose }: ForgotPasswordModalProps) {
  const [step, setStep] = useState(1); // 1=填邮箱发码, 2=填验证码+新密码
  const [email, setEmail] = useState('');
  const [countdown, setCountdown] = useState(0);
  const [sending, setSending] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const sendCode = async () => {
    if (!email) {
      message.warning('请先填写邮箱');
      return;
    }
    setSending(true);
    try {
      await authApi.sendResetCode(email);
      message.success('验证码已发送，请查收邮箱');
      setStep(2);
      let left = 60;
      setCountdown(left);
      const timer = setInterval(() => {
        left -= 1;
        setCountdown(left);
        if (left <= 0) clearInterval(timer);
      }, 1000);
    } catch (err) {
      message.error(getErrorMessage(err, '验证码发送失败，请稍后重试'));
    } finally {
      setSending(false);
    }
  };

  const handleReset = async (values: { code: string; new_password: string }) => {
    setSubmitting(true);
    try {
      await authApi.resetPassword(email, values.code, values.new_password);
      message.success('密码已重置，请登录');
      handleClose();
    } catch (err) {
      message.error(getErrorMessage(err, '重置失败，请稍后重试'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleClose = () => {
    onClose();
    setStep(1);
    setEmail('');
    setCountdown(0);
  };

  return (
    <Modal title="忘记密码" open={open} onCancel={handleClose} footer={null} width={420}>
      {step === 1 ? (
        <Form layout="vertical">
          <Form.Item label="邮箱" required>
            <Input
              prefix={<MailOutlined />}
              placeholder="注册邮箱"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onPressEnter={sendCode}
            />
          </Form.Item>
          <Button type="primary" block loading={sending} onClick={sendCode}>
            发送验证码
          </Button>
        </Form>
      ) : (
        <Form layout="vertical" onFinish={handleReset}>
          <Form.Item label="邮箱">
            <Input prefix={<MailOutlined />} value={email} disabled />
          </Form.Item>
          <Form.Item name="code" rules={[{ required: true, len: 6, message: '请输入6位数字验证码' }]}>
            <Input prefix={<SafetyCertificateOutlined />} placeholder="验证码" />
          </Form.Item>
          <Form.Item name="new_password" rules={[{ required: true, min: 6, message: '密码至少6个字符' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="新密码（至少6位）" />
          </Form.Item>
          <Form.Item name="confirm" dependencies={['new_password']} rules={[
            { required: true, message: '请再次输入新密码' },
            ({ getFieldValue }) => ({
              validator(_, value) {
                if (!value || getFieldValue('new_password') === value) {
                  return Promise.resolve();
                }
                return Promise.reject(new Error('两次输入的密码不一致'));
              },
            }),
          ]}>
            <Input.Password prefix={<LockOutlined />} placeholder="确认新密码" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={submitting}>
            重置密码
          </Button>
        </Form>
      )}
    </Modal>
  );
}
