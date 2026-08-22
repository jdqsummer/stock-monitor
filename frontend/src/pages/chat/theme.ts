// frontend/src/pages/chat/theme.ts
/** DeepSeek 浅色设计 token — 映射参考 deepseek-chat-replica.html 的 :root 变量 */
export const ds = {
  // Brand
  primary: '#4D6EFE',
  primaryHover: '#3D5EE0',
  primarySoft: '#E8EEFF',
  primarySelected: '#EEF2FF',
  gradientStart: '#4D6EFE',
  gradientEnd: '#7B5BFF',

  // Surfaces
  bgApp: '#FFFFFF',
  bgSidebar: '#F9F9F9',
  bgHover: '#F3F3F3',
  bgInput: '#F7F8FA',
  bgCard: '#FFFFFF',
  bgSoft: '#F5F7FA',

  // Text
  textPrimary: '#1A1A1A',
  textSecondary: '#555555',
  textTertiary: '#8A8A8A',
  textQuaternary: '#B5B5B5',
  textOnBrand: '#FFFFFF',

  // Borders
  borderLight: '#ECECEC',
  borderMedium: '#E0E0E0',
  borderInput: '#E5E7EB',
} as const;
