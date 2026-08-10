import { create } from 'zustand';
import type { UserInfo, UserConfig } from '@/types';

interface AppState {
  user: UserInfo | null;
  setUser: (user: UserInfo | null) => void;
  config: UserConfig | null;
  setConfig: (config: UserConfig | null) => void;
  loading: boolean;
  setLoading: (loading: boolean) => void;
}

export const useAppStore = create<AppState>((set) => ({
  user: null,
  setUser: (user) => set({ user }),
  config: null,
  setConfig: (config) => set({ config }),
  loading: false,
  setLoading: (loading) => set({ loading }),
}));
