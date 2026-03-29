import { create } from 'zustand'
import { api } from '../lib/api'

export interface HardwareCaps {
  gpu_vram_gb: number
  ram_gb: number
  npcap: boolean
  libpcap: boolean
  os: string
  disk_free_gb: number
}

interface FeaturesState {
  features: Record<string, boolean>
  capabilities: HardwareCaps | null
  loaded: boolean
  loadFeatures: () => Promise<void>
}

export const useFeaturesStore = create<FeaturesState>((set) => ({
  features: {},
  capabilities: null,
  loaded: false,

  loadFeatures: async () => {
    try {
      const [featRes, capsRes] = await Promise.all([
        api.get<Record<string, boolean>>('/features'),
        api.get<HardwareCaps>('/capabilities'),
      ])
      set({ features: featRes.data, capabilities: capsRes.data, loaded: true })
    } catch {
      // Gateway may not be up yet — features default to all enabled
      set({ loaded: true })
    }
  },
}))

/** Returns true if the named module is installed and enabled. Defaults to true if unknown. */
export const useFeature = (name: string): boolean =>
  useFeaturesStore((s) => s.features[name] ?? true)
