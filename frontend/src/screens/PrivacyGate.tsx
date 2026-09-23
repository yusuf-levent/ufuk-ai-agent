/**
 * First-run privacy gate. Fetched from the gateway's /privacy/info (through
 * the main process) and must be acknowledged once before the app is usable.
 * Explains that code and prompts are proxied through our gateway to
 * third-party model providers.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../ipc/client";
import type { PrivacyInfo } from "@shared/ipc";
import { friendlyError } from "../ipc/errors";
import { useAppStore } from "../stores/app";

export function PrivacyGate({
  onOpenSettings,
}: {
  onOpenSettings: () => void;
}) {
  const patchSettings = useAppStore((s) => s.patchSettings);
  const [info, setInfo] = useState<PrivacyInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retryable, setRetryable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [understood, setUnderstood] = useState(false);
  const [acknowledging, setAcknowledging] = useState(false);

  const load = useCallback((): void => {
    setError(null);
    setBusy(true);
    api
      .privacyInfo()
      .then(setInfo)
      .catch((err: unknown) => {
        const friendly = friendlyError(err);
        setError(friendly.title);
        setRetryable(friendly.retryable);
      })
      .finally(() => setBusy(false));
  }, []);

  useEffect(() => load(), [load]);

  const acknowledge = async (): Promise<void> => {
    if (acknowledging || !understood) return;
    setAcknowledging(true);
    try {
      await patchSettings({ privacyAcknowledged: true });
      // App re-renders past the gate when the setting lands
    } finally {
      setAcknowledging(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center bg-neutral-950 p-6 text-neutral-100">
      <div className="w-full max-w-lg rounded-xl border border-neutral-800 bg-neutral-900/60 p-6">
        <div className="mb-4 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-600/20 text-lg">
            🔒
          </div>
          <div>
            <h1 className="text-lg font-semibold">
              Before you start — how Ufuk handles your data
            </h1>
            <p className="text-xs text-neutral-500">
              shown once · from the gateway&apos;s privacy endpoint
            </p>
          </div>
        </div>

        {busy && <p className="text-sm text-neutral-400">Loading…</p>}

        {error && (
          <div className="space-y-3">
            <div
              role="alert"
              className="rounded-md border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-300"
            >
              {error}
              {retryable && (
                <div className="mt-1 text-xs text-red-400/80">
                  Check that the gateway is running; the backend URL can be
                  changed in Settings.
                </div>
              )}
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={load}
                className="rounded-md bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-500"
              >
                Retry
              </button>
              <button
                type="button"
                onClick={onOpenSettings}
                className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 hover:bg-neutral-800"
              >
                Settings
              </button>
            </div>
          </div>
        )}

        {info && (
          <div className="space-y-4 text-sm">
            <p className="leading-relaxed text-neutral-300">
              Ufuk is a local coding agent, but its model runs in the cloud: the{" "}
              <strong>code and prompts</strong> you work with are sent through
              our gateway to third-party model providers.
            </p>
            <div className="space-y-2 rounded-lg border border-neutral-800 bg-neutral-950/60 p-3 text-xs leading-relaxed text-neutral-400">
              <div>
                <span className="text-neutral-500">Upstream host: </span>
                <code className="text-neutral-300">
                  {info.upstreamHost ?? "unknown"}
                </code>
              </div>
              {info.providers.length > 0 && (
                <div>
                  <span className="text-neutral-500">Providers: </span>
                  {info.providers.join(", ")}
                </div>
              )}
              <p>{info.dataHandling}</p>
              <p className="text-neutral-500">{info.accountDeletion}</p>
            </div>
            <label className="flex items-start gap-2 text-sm text-neutral-300">
              <input
                type="checkbox"
                checked={understood}
                onChange={(e) => setUnderstood(e.target.checked)}
                className="mt-0.5 accent-sky-500"
              />
              <span>
                I understand my code and prompts are processed as described
                above.
              </span>
            </label>
            <button
              type="button"
              onClick={() => void acknowledge()}
              disabled={acknowledging || !understood}
              className="w-full rounded-md bg-sky-600 px-3 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {acknowledging ? "…" : "Continue"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
