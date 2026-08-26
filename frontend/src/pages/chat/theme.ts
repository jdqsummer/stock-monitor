// frontend/src/pages/chat/theme.ts
/** DeepSeek 浅色设计 token — 映射参考 deepseek-chat-replica.html 的 :root 变量。
 *  全部取值来自全局 token（@/theme），此处仅做 chat 惯用的扁平命名映射。 */
import { border as borders, brand, surface, text as texts } from '@/theme';

export const ds = {
  // Brand（单一来源：@/theme）
  ...brand,
  gradientStart: '#4D6EFE',
  gradientEnd: '#7B5BFF',

  // Surfaces
  bgApp: surface.app,
  bgSidebar: surface.sidebar,
  bgHover: surface.hover,
  bgInput: surface.input,
  bgCard: surface.card,
  bgSoft: surface.soft,

  // Text
  textPrimary: texts.primary,
  textSecondary: texts.secondary,
  textTertiary: texts.tertiary,
  textQuaternary: texts.quaternary,
  textOnBrand: '#FFFFFF',

  // Borders
  borderLight: borders.light,
  borderMedium: borders.medium,
  borderInput: borders.input,
} as const;
