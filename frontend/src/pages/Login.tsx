import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Form, Input, Button, message, Tabs } from 'antd';
import { UserOutlined, LockOutlined } from '@ant-design/icons';
import { authApi } from '@/api/client';

export function Login() {
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (values: { username: string; password: string }, isRegister: boolean) => {
    setLoading(true);
    try {
      const api = isRegister ? authApi.register : authApi.login;
      const res = await api(values.username, values.password);
      if (res.data.code === 0) {
        if (!isRegister) {
          const token = (res.data.data as { access_token: string }).access_token;
          localStorage.setItem('token', token);
          navigate('/');
        } else {
          message.success('注册成功，请登录');
        }
      }
    } catch {
      message.error(isRegister ? '注册失败' : '用户名或密码错误');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh', background: '#f0f2f5' }}>
      <Card title="📈 股票监控系统" style={{ width: 400 }}>
        <Tabs items={[
          {
            key: 'login', label: '登录',
            children: (
              <Form onFinish={(v: { username: string; password: string }) => handleSubmit(v, false)}>
                <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
                  <Input prefix={<UserOutlined />} placeholder="用户名" />
                </Form.Item>
                <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
                  <Input.Password prefix={<LockOutlined />} placeholder="密码" />
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
              <Form onFinish={(v: { username: string; password: string }) => handleSubmit(v, true)}>
                <Form.Item name="username" rules={[{ required: true, min: 3, message: '用户名至少3个字符' }]}>
                  <Input prefix={<UserOutlined />} placeholder="用户名" />
                </Form.Item>
                <Form.Item name="password" rules={[{ required: true, min: 6, message: '密码至少6个字符' }]}>
                  <Input.Password prefix={<LockOutlined />} placeholder="密码" />
                </Form.Item>
                <Form.Item>
                  <Button type="primary" htmlType="submit" loading={loading} block>注册</Button>
                </Form.Item>
              </Form>
            ),
          },
        ]} />
      </Card>
    </div>
  );
}
