import { Spin } from 'antd';

export function Loading({ tip = '加载中...' }: { tip?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 200 }}>
      <Spin size="large" tip={tip} />
    </div>
  );
}
