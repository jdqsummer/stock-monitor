import { Alert } from 'antd';
import type { CSSProperties } from 'react';

/** 纯规则降级分析提示（Analysis 结果卡与个股详情共用，替代各自手写的橙底 div） */
export function DegradedAlert({ style }: { style?: CSSProperties }) {
  return (
    <Alert
      type="warning"
      showIcon
      style={style}
      message="本次为纯规则降级分析（无 LLM 参与）"
      description="只做了确定性计算与规则校验，不含定性/逆向/估值 LLM 判断。结论仅供参考，建议人工复核后再决策。"
    />
  );
}
