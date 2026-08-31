import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Form, Input, Button, message, Tabs } from 'antd';
import { MailOutlined, LockOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import { authApi } from '@/api/client';
import { syncAuthCookie } from '@/api/authCookie';
import { surface } from '@/theme';
import { getErrorMessage } from '@/utils/error';
import { ForgotPasswordModal } from '@/components/ForgotPasswordModal';

export function Login() {
  const [activeTab, setActiveTab] = useState('login');
  const [loading, setLoading] = useState(false);
  const [registerLoading, setRegisterLoading] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [regEmail, setRegEmail] = useState('');
  const [forgotOpen, setForgotOpen] = useState(false);
  const navigate = useNavigate();

  // 登录：邮箱 + 密码
  const handleLogin = async (values: { email: string; password: string }) => {
    setLoading(true);
    try {
      const res = await authApi.login(values.email, values.password);
      if (res.data.code === 0) {
        const token = (res.data.data as { access_token: string }).access_token;
        localStorage.setItem('token', token);
        syncAuthCookie();
        message.success('登录成功，欢迎回来');
        navigate('/');
      }
    } catch (err) {
      message.error(getErrorMessage(err, '登录失败，请稍后重试'));
    } finally {
      setLoading(false);
    }
  };

  // 发送注册验证码
  const sendRegisterCode = async () => {
    if (!regEmail) {
      message.warning('请先填写邮箱');
      return;
    }
    try {
      await authApi.sendRegisterCode(regEmail);
      message.success('验证码已发送，请查收邮箱');
      let left = 60;
      setCountdown(left);
      const timer = setInterval(() => {
        left -= 1;
        setCountdown(left);
        if (left <= 0) clearInterval(timer);
      }, 1000);
    } catch (err) {
      const msg = getErrorMessage(err, '验证码发送失败，请稍后重试');
      if (msg.includes('已注册')) {
        message.info(`${msg}，可直接切换登录`);
        setActiveTab('login');
      } else {
        message.error(msg);
      }
    }
  };

  // 注册：邮箱 + 验证码 + 密码
  const handleRegister = async (values: { email: string; code: string; password: string }) => {
    setRegisterLoading(true);
    try {
      const res = await authApi.register(values.email, values.password, values.code);
      if (res.data.code === 0) {
        message.success('注册成功，请登录');
        setActiveTab('login');
      }
    } catch (err) {
      const msg = getErrorMessage(err, '注册失败，请稍后重试');
      if (msg.includes('已注册')) {
        message.info(`${msg}，可直接切换登录`);
        setActiveTab('login');
      } else {
        message.error(msg);
      }
    } finally {
      setRegisterLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh', background: surface.soft }}>
      <Card
        title={
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <img src="/logo.png" alt="logo" style={{ width: 24, height: 24, borderRadius: 6 }} />
            股票监控系统
          </span>
        }
        style={{ width: 420 }}
      >
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
          {
            key: 'login', label: '登录',
            children: (
              <Form onFinish={handleLogin}>
                <Form.Item name="email" rules={[{ required: true, type: 'email', message: '请输入正确的邮箱地址' }]}>
                  <Input prefix={<MailOutlined />} placeholder="邮箱" />
                </Form.Item>
                <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
                  <Input.Password prefix={<LockOutlined />} placeholder="密码" />
                </Form.Item>
                <Form.Item>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <a
                      href="/about/"
                      style={{ color: '#4D6EFE', fontSize: 13, textDecoration: 'none' }}
                      onMouseEnter={(e) => (e.currentTarget.style.textDecoration = 'underline')}
                      onMouseLeave={(e) => (e.currentTarget.style.textDecoration = 'none')}
                    >
                      先了解产品
                    </a>
                    <Button type="link" size="small" style={{ padding: 0 }} onClick={() => setForgotOpen(true)}>
                      忘记密码？
                    </Button>
                  </div>
                </Form.Item>
                <Form.Item>
                  <Button type="primary" htmlType="submit" loading={loading} block>登录</Button>
                </Form.Item>
              </Form>
            ),
          },
          {
            key: 'register', label: '注册',
            children: (
              <Form onFinish={handleRegister}>
                <Form.Item name="email" rules={[{ required: true, type: 'email', message: '请输入正确的邮箱地址' }]}>
                  <Input prefix={<MailOutlined />} placeholder="邮箱" onChange={(e) => setRegEmail(e.target.value)} />
                </Form.Item>
                <Form.Item name="code" rules={[{ required: true, len: 6, message: '请输入6位数字验证码' }]}>
                  <Input prefix={<SafetyCertificateOutlined />} placeholder="验证码" suffix={
                    <Button type="link" size="small" disabled={countdown > 0} onClick={sendRegisterCode}>
                      {countdown > 0 ? `${countdown}s` : '发送验证码'}
                    </Button>
                  } />
                </Form.Item>
                <Form.Item name="password" rules={[{ required: true, min: 6, message: '密码至少6个字符' }]}>
                  <Input.Password prefix={<LockOutlined />} placeholder="密码（至少6位）" />
                </Form.Item>
                <Form.Item>
                  <Button type="primary" htmlType="submit" loading={registerLoading} block>注册</Button>
                </Form.Item>
              </Form>
            ),
          },
        ]} />
      </Card>
      <ForgotPasswordModal open={forgotOpen} onClose={() => setForgotOpen(false)} />
    </div>
  );
}
