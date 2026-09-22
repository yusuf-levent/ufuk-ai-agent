/**
 * Settings dialog: backend URL, theme (dark default + light), default tier,
 * permission mode. All changes go through the settings:set IPC (validated
 * in main); a backend URL change rebuilds the gateway session there.
 */
import { useEffect, useState } from "react";
import { useAppStore } from "../stores/app";
import type { SettingsPatch } from "@shared/ipc";

const TIERS = [
  { value: "fast", label: "Fast", hint: "quickest, smallest models" },
  { value: "balanced", label: "Balanced", hint: "default mix" },
  { value: "strong", label: "Strong", hint: "most capable, priciest" },
] as const;

const PERMISSION_MODES = [
  {
    value: "ask",
    label: "Ask every time",
    hint: "Approve every file edit and command before it runs.",
  },
  {
    value: "auto-edits",
    label: "Auto-accept edits inside the workspace",
    hint: "File edits in the project folder run without asking; commands still ask.",
  },
] as const;

export function SettingsDialog({ onClose }: { onClose: () => void }) {
  const { settings, patchSettings } = useAppStore();
  const [backendUrl, setBackendUrl] = useState(settings?.backendUrl ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!settings) return null;

  const apply = async (patch: SettingsPatch): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await patchSettings(patch);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const saveBackendUrl = async (): Promise<void> => {
    const trimmed = backendUrl.trim().replace(/\/+$/, "");
    if (trimmed === settings.backendUrl) return;
    if (!/^https?:\/\/.+/i.test(trimmed)) {
      setError("Backend URL must start with http:// or https://");
      return;
    }
    await apply({ backendUrl: trimmed });
  };

  const row = "flex items-center justify-between gap-4 py-2";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-label="Settings"
        className="w-full max-w-md rounded-xl border border-neutral-800 bg-neutral-900 p-5 text-neutral-100 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold">Settings</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close settings"
            className="rounded-md border border-neutral-700 px-2 py-0.5 text-xs text-neutral-400 hover:bg-neutral-800"
          >
            ✕
          </button>
        </div>

        <div className="divide-y divide-neutral-800">
          <div className="py-3">
            <label className="mb-1 block text-xs font-medium text-neutral-400">
              Backend URL (gateway)
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={backendUrl}
                onChange={(e) => setBackendUrl(e.target.value)}
                placeholder="http://localhost:8000"
                spellCheck={false}
                className="w-full rounded-md border border-neutral-700 bg-neutral-950 px-2 py-1.5 font-mono text-xs text-neutral-200 outline-none focus:border-sky-500"
              />
              <button
                type="button"
                onClick={() => void saveBackendUrl()}
                disabled={busy}
                className="shrink-0 rounded-md bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-50"
              >
                Save
              </button>
            </div>
            <p className="mt-1 text-[11px] text-neutral-500">
              Changing this rebuilds the gateway session (fresh login state
              per backend).
            </p>
          </div>

          <div className={row}>
            <div>
              <div className="text-sm">Theme</div>
              <div className="text-[11px] text-neutral-500">
                dark is the default
              </div>
            </div>
            <div className="flex overflow-hidden rounded-md border border-neutral-700 text-xs">
              {(["dark", "light"] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  disabled={busy}
                  onClick={() => void apply({ theme: t })}
                  className={
                    "px-3 py-1 " +
                    (settings.theme === t
                      ? "bg-sky-600 text-white"
                      : "text-neutral-400 hover:bg-neutral-800")
                  }
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          <div className="py-3">
            <div className="mb-1.5 text-sm">Default tier</div>
            <div className="space-y-1">
              {TIERS.map((tier) => (
                <label
                  key={tier.value}
                  className="flex cursor-pointer items-center gap-2 rounded-md px-1 py-1 text-xs hover:bg-neutral-800/60"
                >
                  <input
                    type="radio"
                    name="tier"
                    checked={settings.defaultTier === tier.value}
                    disabled={busy}
                    onChange={() => void apply({ defaultTier: tier.value })}
                    className="accent-sky-500"
                  />
                  <span className="font-medium text-neutral-200">
                    {tier.label}
                  </span>
                  <span className="text-neutral-500">{tier.hint}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="py-3">
            <div className="mb-1.5 text-sm">Permission mode</div>
            <div className="space-y-1">
              {PERMISSION_MODES.map((mode) => (
                <label
                  key={mode.value}
                  className="flex cursor-pointer items-start gap-2 rounded-md px-1 py-1 text-xs hover:bg-neutral-800/60"
                >
                  <input
                    type="radio"
                    name="perm"
                    checked={settings.permissionMode === mode.value}
                    disabled={busy}
                    onChange={() =>
                      void apply({ permissionMode: mode.value })
                    }
                    className="mt-0.5 accent-sky-500"
                  />
                  <span>
                    <span className="block font-medium text-neutral-200">
                      {mode.label}
                    </span>
                    <span className="text-neutral-500">{mode.hint}</span>
                  </span>
                </label>
              ))}
            </div>
            <p className="mt-1 text-[11px] text-neutral-500">
              There is no &quot;allow everything&quot; mode.
            </p>
          </div>
        </div>

        {error && (
          <div
            role="alert"
            className="mt-3 rounded-md border border-red-900 bg-red-950/50 px-3 py-2 text-xs text-red-300"
          >
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
