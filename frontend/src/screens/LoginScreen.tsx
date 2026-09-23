/**
 * Login / register screen. Errors from the main process arrive as coded
 * IpcErrors and are rendered via friendlyError(); the backend URL can be
 * changed from here (gear icon) because login itself may need it.
 */
import { useState } from "react";
import { useAppStore } from "../stores/app";
import { friendlyError } from "../ipc/errors";

type Mode = "login" | "register";

export function LoginScreen({
  onOpenSettings,
}: {
  onOpenSettings: () => void;
}) {
  const { login, register } = useAppStore();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorDetail, setErrorDetail] = useState<string | null>(null);

  const submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setErrorDetail(null);
    if (mode === "register" && password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    setBusy(true);
    try {
      if (mode === "login") {
        await login({ email, password });
      } else {
        await register({
          email,
          password,
          displayName: displayName.trim() || undefined,
        });
      }
      // session store refresh navigates away on success
    } catch (err) {
      const friendly = friendlyError(err);
      setError(friendly.title);
      setErrorDetail(friendly.detail ?? null);
    } finally {
      setBusy(false);
    }
  };

  const inputClass =
    "w-full rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-100 placeholder-neutral-500 outline-none focus:border-sky-500";

  return (
    <div className="flex h-full items-center justify-center bg-neutral-950 p-6 text-neutral-100">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500 to-indigo-600 text-lg font-bold text-white shadow-lg">
            U
          </div>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Ufuk</h1>
            <p className="text-xs text-neutral-500">yerel kodlama ajanı</p>
          </div>
          <button
            type="button"
            onClick={onOpenSettings}
            title="Settings"
            aria-label="Settings"
            className="ml-auto rounded-md border border-neutral-700 px-2 py-1 text-xs text-neutral-400 hover:bg-neutral-800"
          >
            ⚙
          </button>
        </div>

        <form onSubmit={submit} className="space-y-3" noValidate>
          {mode === "register" && (
            <label className="block">
              <span className="mb-1 block text-xs text-neutral-400">
                Name (optional)
              </span>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className={inputClass}
                placeholder="Ada Lovelace"
                maxLength={100}
                autoComplete="name"
              />
            </label>
          )}
          <label className="block">
            <span className="mb-1 block text-xs text-neutral-400">Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={inputClass}
              placeholder="you@example.com"
              autoComplete="email"
              required
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-neutral-400">
              Password
              {mode === "register" && (
                <span className="text-neutral-600"> (min 8 characters)</span>
              )}
            </span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputClass}
              autoComplete={
                mode === "login" ? "current-password" : "new-password"
              }
              required
            />
          </label>

          {error && (
            <div
              role="alert"
              className="rounded-md border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-300"
            >
              <div className="font-medium">{error}</div>
              {errorDetail && (
                <div className="mt-0.5 text-xs text-red-400/80">
                  {errorDetail}
                </div>
              )}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-md bg-sky-600 px-3 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "…" : mode === "login" ? "Log in" : "Create account"}
          </button>
        </form>

        <button
          type="button"
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError(null);
            setErrorDetail(null);
          }}
          className="mt-4 w-full text-center text-xs text-neutral-400 hover:text-sky-400"
        >
          {mode === "login"
            ? "No account yet? Register"
            : "Already have an account? Log in"}
        </button>
      </div>
    </div>
  );
}
