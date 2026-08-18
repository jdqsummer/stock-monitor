export const CATEGORY_META: Record<string, { label: string; color: string }> = {
  strike: { label: '击球区', color: 'green' },
  sell: { label: '卖出区', color: 'red' },
  api_config: { label: 'API 未配置', color: 'orange' },
  dsh_error: { label: 'DSH 错误', color: 'orange' },
  llm_error: { label: 'LLM 错误', color: 'orange' },
};

export function categoryMeta(category: string): { label: string; color: string } {
  return CATEGORY_META[category] || { label: category || '消息', color: 'default' };
}
