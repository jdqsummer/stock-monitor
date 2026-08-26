// frontend/src/theme.ts
/** 全局设计 token 单一来源：品牌色对齐 DeepSeek 浅色主题，语义色全站唯一定义处。
 *  chat 子树的 ds（pages/chat/theme.ts）从这里取品牌色；页面代码禁止再写死这些字面量。 */

export const brand = {
  primary: '#4D6EFE',
  primaryHover: '#3D5EE0',
  primarySoft: '#E8EEFF',
  primarySelected: '#EEF2FF',
} as const;

/** 行情涨跌（A股惯例：红涨绿跌） */
export const market = {
  up: '#cf1322',
  down: '#3f8600',
  flat: '#8A8A8A',
} as const;

/** 信号灯三色 + 未分析灰 */
export const signal = {
  green: '#52c41a',
  yellow: '#faad14',
  red: '#ff4d4f',
  none: '#bfbfbf',
} as const;

/** 状态反馈文字色（成功/警示/错误） */
export const status = {
  success: '#52c41a',
  warning: '#faad14',
  error: '#ff4d4f',
} as const;

import type { CSSProperties } from 'react';

/** 品牌色软底 Tag 样式：替代 Tag 预设 'blue'（antd 固定调色板蓝 #1677ff，与品牌主色冲突） */
export const brandTagStyle: CSSProperties = {
  color: brand.primary,
  background: brand.primarySoft,
  borderColor: 'transparent',
};
