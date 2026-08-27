import { create } from 'zustand';
import type { UserInfo, UserConfig } from '@/types';

interface AppState {
  user: UserInfo | null;
  setUser: (user: UserInfo | null) => void;
  config: UserConfig | null;
  setConfig: (config: UserConfig | null) => void;
  loading: boolean;
  setLoading: (loading: boolean) => void;
  /** getMe 是否已返回（含失败）：之前 user 恒为 null，权限判断会误判 → 刷新 /admin 闪「无权限」 */
  userLoaded: boolean;
  setUserLoaded: (loaded: boolean) => void;
}

export const useAppStore = create<AppState>((set) => ({
  user: null,
  setUser: (user) => set({ user }),
  config: null,
  setConfig: (config) => set({ config }),
  loading: false,
  setLoading: (loading) => set({ loading }),
  userLoaded: false,
  setUserLoaded: (loaded) => set({ userLoaded: loaded }),
}));
