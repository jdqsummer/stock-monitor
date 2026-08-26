import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider, App as AntdApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { brand } from '@/theme';
import { syncAuthCookie } from '@/api/authCookie';
import { ErrorBoundary } from '@/components/Common/ErrorBoundary';
import { AppLayout } from '@/components/Layout/AppLayout';
import { Login } from '@/pages/Login';
import { Dashboard } from '@/pages/Dashboard';
import { Watchlist } from '@/pages/Watchlist';
import { StockDetail } from '@/pages/StockDetail';
import { Portfolio } from '@/pages/Portfolio';
import { PositionDetail } from '@/pages/PositionDetail';
import { Analysis } from '@/pages/Analysis';
import { Chat } from '@/pages/Chat';
import { Diary } from '@/pages/Diary';
import { Settings } from '@/pages/Settings';

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('token');
  if (token) {
    syncAuthCookie(); // 已登录但镜像 cookie 缺失/过期 → 补写（<img> 鉴权依赖）
    return <>{children}</>;
  }
  return <Navigate to="/login" />;
}

export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: brand.primary,
          colorInfo: brand.primary,
          borderRadius: 8,
        },
      }}
    >
      <AntdApp>
        <BrowserRouter>
          <ErrorBoundary>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/" element={<PrivateRoute><AppLayout /></PrivateRoute>}>
                <Route index element={<Dashboard />} />
                <Route path="watchlist" element={<Watchlist />} />
                <Route path="stock/:code" element={<StockDetail />} />
                <Route path="portfolio" element={<Portfolio />} />
                <Route path="portfolio/:id" element={<PositionDetail />} />
                <Route path="analysis" element={<Analysis />} />
                <Route path="chat" element={<Chat />} />
                <Route path="diary" element={<Diary />} />
                <Route path="settings" element={<Settings />} />
              </Route>
            </Routes>
          </ErrorBoundary>
        </BrowserRouter>
      </AntdApp>
    </ConfigProvider>
  );
}
