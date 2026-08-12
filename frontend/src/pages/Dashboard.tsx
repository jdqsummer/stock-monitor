import { useState, useEffect, useCallback } from 'react';
import { Card, Divider } from 'antd';
import { OverviewCards } from '@/components/Dashboard/OverviewCards';
import { SignalBoard } from '@/components/Dashboard/SignalBoard';
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
    } catch (err) {
      console.error('Dashboard fetch failed:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  usePolling(fetchData, 30 * 60 * 1000);

  if (loading && !overview) return <Loading tip="加载仪表盘..." />;

  return (
    <div>
      <h2>📊 仪表盘</h2>
      {overview && <OverviewCards data={overview} />}

      <Divider />

      <Card title="🔔 安全边际监控看板" style={{ marginBottom: 16 }}>
        <SignalBoard data={watchlist} loading={loading} onRefresh={fetchData} />
      </Card>

      <Card title="💼 持仓分析">
        <PortfolioPanel data={positions} loading={loading} />
      </Card>
    </div>
  );
}
