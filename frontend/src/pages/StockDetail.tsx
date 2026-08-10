import { useParams } from 'react-router-dom';
import { Result } from 'antd';

export function StockDetail() {
  const { code } = useParams();
  return <Result title="股票详情" subTitle={`代码: ${code} — Plan-4 实现`} />;
}
