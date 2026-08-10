import { Row, Col, Card, Statistic } from 'antd';
import { ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons';
import type { DashboardOverview } from '@/types';

export function OverviewCards({ data }: { data: DashboardOverview }) {
  const plColor = data.total_pl >= 0 ? '#3f8600' : '#cf1322';

  return (
    <Row gutter={16}>
      <Col span={6}>
        <Card><Statistic title="总市值" value={data.total_market_value} precision={2} suffix="万" /></Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic
            title="总盈亏"
            value={data.total_pl}
            precision={2}
            suffix="万"
            valueStyle={{ color: plColor }}
            prefix={data.total_pl >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card><Statistic title="总盈亏率" value={data.total_pl_pct} precision={2} suffix="%" valueStyle={{ color: plColor }} /></Card>
      </Col>
      <Col span={6}>
        <Card>
          <Statistic title="当日盈亏" value={data.daily_pl} precision={2} suffix="万" valueStyle={{ color: data.daily_pl >= 0 ? '#3f8600' : '#cf1322' }} />
        </Card>
      </Col>
      <Col span={6}>
        <Card><Statistic title="持仓数量" value={data.position_count} suffix={` (${data.profit_count}盈/${data.loss_count}亏)`} /></Card>
      </Col>
    </Row>
  );
}
