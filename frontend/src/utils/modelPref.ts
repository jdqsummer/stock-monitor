// 模型偏好：localStorage 持久化跨刷新，跨页面隔离 key；chat 与分析页分开存。
//
// 优先级（resolveModel）：
//   1) normalizeModelSpec(localStorage 旧值) ← 用户最近一次选择
//   2) normalizeModelSpec(系统设置 llm_model) ← 全局兜底
//   3) '' ← 让 <Select> 显示 placeholder（不显示假数据）
//
// 归一化应对三种历史脏值（参考 Chat.tsx:47-66 同源逻辑）：
//   - 裸 id：'deepseek-v4-flash' / 'minimax/minimax-m2.7:free'
//   - 双/三前缀：'openrouter:openrouter:deepseek/deepseek-v4-flash'
//   - 列表外的旧 spec：不在当前 catalog 但合法（跳过）

export type ModelPrefPage = 'watchlist' | 'portfolio' | 'analysis' | 'chat';

const ANALYSIS_PREFIX = 'analysis_model:';
const CHAT_KEY = 'chat_model';

function keyOf(page: ModelPrefPage): string {
  return page === 'chat' ? CHAT_KEY : `${ANALYSIS_PREFIX}${page}`;
}

function safeStorage(): Storage | null {
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null;
  } catch {
    return null;
  }
}

/** 读取页面级模型选择（chat 与分析页分开 key）。SSR/无 localStorage 退回空串。 */
export function getStoredModel(page: ModelPrefPage): string {
  return safeStorage()?.getItem(keyOf(page)) || '';
}

/** 写入页面级模型选择。下拉 onChange 调用。 */
export function setStoredModel(page: ModelPrefPage, spec: string): void {
  safeStorage()?.setItem(keyOf(page), spec);
}

/**
 * 把可能脏的 spec 归一化到当前 catalog 的 model_id。
 * 命中返回 spec；不命中返回 ''（让上层走兜底链）。
 */
export function normalizeModelSpec(
  raw: string,
  models: ReadonlyArray<{ model_id: string }>,
): string {
  if (!raw) return '';
  // 1) 列表中直中
  const hit = models.find((m) => m.model_id === raw);
  if (hit) return hit.model_id;
  // 2) 旧 bug：前端 ${provider}:${model_id} 拼出双/三前缀 → 循环剥首段
  let cur = raw;
  while (cur.includes(':')) {
    const idx = cur.indexOf(':');
    const stripped = cur.slice(idx + 1);
    if (!stripped || stripped === cur) break;
    const hit2 = models.find((m) => m.model_id === stripped);
    if (hit2) return hit2.model_id;
    cur = stripped;
  }
  // 3) 旧 spec（裸 id 或带斜杠的 free 模型）→ 按 model_id 后缀匹配
  const hit3 = models.find((m) => m.model_id.endsWith(`:${raw}`));
  return hit3 ? hit3.model_id : '';
}

/**
 * 解析页面级模型选择：localStorage 优先 → 系统设置兜底。
 * 命中且归一化后写回 localStorage（清理脏值），返回最终 spec；都无 → ''。
 */
export function resolveModel(
  page: ModelPrefPage,
  cfgModel: string,
  models: ReadonlyArray<{ model_id: string }>,
): string {
  const stored = getStoredModel(page);
  const normalizedStored = normalizeModelSpec(stored, models);
  const normalizedCfg = normalizeModelSpec(cfgModel, models);
  const final = normalizedStored || normalizedCfg;
  if (final) setStoredModel(page, final);
  return final;
}
