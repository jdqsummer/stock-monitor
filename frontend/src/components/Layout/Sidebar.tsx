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
} from '@ant-design/icons';

const menuItems = [
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

  return (
    <Menu
      mode="inline"
      selectedKeys={[location.pathname]}
      items={menuItems}
      onClick={({ key }: { key: string }) => navigate(key)}
      style={{ height: '100%', borderRight: 0 }}
    />
  );
}
