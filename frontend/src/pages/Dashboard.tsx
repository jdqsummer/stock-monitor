import { useState, useCallback } from 'react';
import { Alert, Button, Card, Divider } from 'antd';
import { OverviewCards } from '@/components/Dashboard/OverviewCards';
import { WatchlistBoard } from '@/components/Dashboard/WatchlistBoard';
import { PortfolioPanel } from '@/components/Dashboard/PortfolioPanel';
import { Loading } from '@/components/Common/Loading';
import { usePolling } from '@/hooks/usePolling';
import { dashboardApi } from '@/api/client';
import type { DashboardOverview, WatchlistBoardRow, PositionInfo } from '@/types';

export function Dashboard() {
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [watchlist, setWatchlist] = useState<WatchlistBoardRow[]>([]);
  const [positions, setPositions] = useState<PositionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [overviewRes, watchlistRes, positionsRes] = await Promise.all([
        dashboardApi.getOverview(),
        dashboardApi.getWatchlistStatus(),
        dashboardApi.getPositions(),
      ]);
      setOverview(overviewRes.data.data as DashboardOverview);
      setWatchlist((watchlistRes.data.data || []) as WatchlistBoardRow[]);
      setPositions((positionsRes.data.data || []) as PositionInfo[]);
      setLoadError(false);
    } catch (err) {
      // 不再静默：给出可见错误 + 重试入口（轮询失败时保留已有数据）
      console.error('Dashboard fetch failed:', err);
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  usePolling(fetchData, 30 * 60 * 1000);

  if (loading && !overview) return <Loading tip="加载仪表盘..." />;

  if (loadError && !overview) {
    return (
      <div>
        <h2>仪表盘</h2>
        <Alert type="error" showIcon message="加载仪表盘失败" description="网络异常或服务暂不可用。"
          action={<Button size="small" danger onClick={fetchData}>重试</Button>} />
      </div>
    );
  }

  return (
    <div>
      <h2>仪表盘</h2>
      {loadError && (
        <Alert type="warning" showIcon style={{ marginBottom: 16 }} message="数据刷新失败，以下为上次结果。"
          action={<Button size="small" danger onClick={fetchData}>重试</Button>} />
      )}
      {overview && <OverviewCards data={overview} />}

      <Divider />

      <Card title="持仓股" style={{ marginBottom: 16 }}>
        <PortfolioPanel data={positions} loading={loading} />
      </Card>

      <Card title="自选股">
        <WatchlistBoard data={watchlist} loading={loading} />
      </Card>
    </div>
  );
}
