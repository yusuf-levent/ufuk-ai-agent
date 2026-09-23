/**
 * Tier catalog + usage state (M8): fetched through the IPC bridge,
 * refreshed on login/session changes and after finished runs.
 */
import { create } from "zustand";
import { api } from "../ipc/client";
import type { TierCatalog, UsageInfo } from "@shared/ipc";

export interface ModelsStore {
  catalog: TierCatalog | null;
  catalogError: string | null;
  catalogErrorCode: string | null;
  usage: UsageInfo | null;
  usageError: string | null;
  usageErrorCode: string | null;
  refresh: () => Promise<void>;
  refreshUsage: () => Promise<void>;
}

export const useModelsStore = create<ModelsStore>((set) => ({
  catalog: null,
  catalogError: null,
  catalogErrorCode: null,
  usage: null,
  usageError: null,
  usageErrorCode: null,

  refresh: async () => {
    try {
      const catalog = await api.tierCatalog();
      set({
        catalog,
        catalogError: null,
        catalogErrorCode: null,
      });
    } catch (err) {
      set({
        catalog: null,
        catalogError: err instanceof Error ? err.message : String(err),
        catalogErrorCode:
          typeof err === "object" && err !== null && "code" in err
            ? String((err as { code?: unknown }).code ?? "")
            : null,
      });
    }
    await useModelsStore.getState().refreshUsage();
  },

  refreshUsage: async () => {
    try {
      const usage = await api.usage();
      set({ usage, usageError: null, usageErrorCode: null });
    } catch (err) {
      set({
        usage: null,
        usageError: err instanceof Error ? err.message : String(err),
        usageErrorCode:
          typeof err === "object" && err !== null && "code" in err
            ? String((err as { code?: unknown }).code ?? "")
            : null,
      });
    }
  },
}));
