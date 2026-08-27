import { useNavigate, useLocation } from 'react-router-dom';
import { Menu } from 'antd';
import {
  DashboardOutlined,
  StarOutlined,
  PieChartOutlined,
  RobotOutlined,
  MessageOutlined,
  BookOutlined,
  SettingOutlined,
  SafetyOutlined,
} from '@ant-design/icons';
import { useAppStore } from '@/store';

const ADMIN_EMAIL = '1140467720@qq.com';

const baseMenuItems = [
  { key: '/', icon: <DashboardOutlined />, label: '仪表盘' },
  { key: '/watchlist', icon: <StarOutlined />, label: '自选股' },
  { key: '/portfolio', icon: <PieChartOutlined />, label: '持仓分析' },
  { key: '/analysis', icon: <RobotOutlined />, label: 'AI 分析' },
  { key: '/chat', icon: <MessageOutlined />, label: '投资聊天' },
  { key: '/diary', icon: <BookOutlined />, label: '投资日记' },
  { key: '/settings', icon: <SettingOutlined />, label: '系统设置' },
];

export function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const user = useAppStore((s) => s.user);

  // 管理后台：仅管理员邮箱可见（前端隐藏 + 后端 require_admin 双重保护）
  const isAdmin = user?.email?.toLowerCase() === ADMIN_EMAIL.toLowerCase();
  const items = isAdmin
    ? [...baseMenuItems, { key: '/admin', icon: <SafetyOutlined />, label: '管理后台' }]
    : baseMenuItems;

  return (
    <Menu
      mode="inline"
      selectedKeys={[location.pathname]}
      items={items}
      onClick={({ key }: { key: string }) => navigate(key)}
      style={{ height: '100%', borderRight: 0 }}
    />
  );
}
