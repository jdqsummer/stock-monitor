import { useEffect } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { Layout, Button, Dropdown } from 'antd';
import { UserOutlined, LogoutOutlined } from '@ant-design/icons';
import { Sidebar } from './Sidebar';
import { ReminderBell } from './ReminderBell';
import { HeaderTicker } from './HeaderTicker';
import { useUnreadMessages } from '@/hooks/useUnreadMessages';
import { useAppStore } from '@/store';
import { authApi } from '@/api/client';

const { Header, Sider, Content } = Layout;

export function AppLayout() {
  const navigate = useNavigate();
  const { user, setUser } = useAppStore();
  const { items, enabled, markAllRead } = useUnreadMessages();

  useEffect(() => {
    authApi.getMe().then((res) => {
      setUser(res.data.data as never);
    }).catch(() => {
      localStorage.removeItem('token');
      navigate('/login');
    });
  }, []);

  const handleLogout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={200} theme="light">
        <div style={{ height: 64, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, fontWeight: 'bold', fontSize: 16 }}>
          <img src="/logo.png" alt="logo" style={{ width: 28, height: 28, borderRadius: 6 }} />
          股票监控系统
        </div>
        <Sidebar />
      </Sider>
      <Layout style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
        <Header style={{ background: '#fff', flexShrink: 0, display: 'flex', justifyContent: 'flex-end', alignItems: 'center', padding: '0 24px', gap: 12 }}>
          <ReminderBell items={items} enabled={enabled} markAllRead={markAllRead} />
          <Dropdown menu={{ items: [{ key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: handleLogout }] }}>
            <Button icon={<UserOutlined />}>{user?.email || user?.username || '用户'}</Button>
          </Dropdown>
        </Header>
        <HeaderTicker items={items} enabled={enabled} />
        <Content style={{ flex: 1, minHeight: 0, overflow: 'auto', margin: 16, padding: 24, background: '#fff', borderRadius: 8 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
