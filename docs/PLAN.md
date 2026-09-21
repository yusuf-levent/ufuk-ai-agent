# Ufuk — Plan

Milestones adapted from the brief; reality checks are recorded inline. The
rule after every milestone: run **all** test suites (agent, backend, frontend),
lint, typecheck; small conventional commits; short report appended to
`docs/PROGRESS.md`. Never leave failing tests. Never commit secrets. Windows
only.

## Workspace strategy (decided)

- `frontend/` is created **inside this folder** (`evren agent system`), sibling
  of `evren-agent/` and `evren-backend/`. Product/app name: **Ufuk**.
- Root `pnpm-workspace.yaml`: `evren-agent/packages/*` + `frontend`.
- `evren-agent` stays a self-contained nested git repo (commit there first,
  then update the outer gitlink). Backend files are committed directly in the
  outer repo.
- The frontend's Electron main process imports `@evren/agent-core` and
  `@evren/local-runner` as workspace packages — single source of truth.

## Milestone 1 — Backend fixes (evren-backend)

1. **Plan change keeps the billing period.** Rule: assigning a plan while an
   active subscription exists inherits its `period_start`/`period_end`; the new
   plan's limit applies to credits already used in that period. No active
   subscription → fresh 30-day period (unchanged). The Redis ledger key
   (`credits:{user}:{period_start.date()}`) is preserved automatically.
   Regression tests: usage survives plan change, downgrade below usage → 402,
   period_end unchanged, fresh period when expired.
2. **Credit rates stay data.** Add `scripts/derive_credit_rates.py` (inputs:
   upstream $/1M tokens in/out, margin, credits-per-USD → prints tier rates and
   the admin PATCH body) + README section with the formula
   `rate = usd_per_1k / credits_per_usd × (1 + margin)`. Placeholder prices
   only; documented that operators must use real upstream prices.
3. **OpenRouter by env only.** No code path may hardcode a provider. Verify
   with a mocked OpenRouter-style upstream: usage in the final SSE chunk,
   OpenRouter error bodies (`{"error": {"message", "code"}}` with numeric
   code), 429 with `X-RateLimit-Reset` HTTP-date → forwarded 429 +
   `Retry-After` + `error.resets_at`; never charge for failed requests
   (usage row FAILED, ledger released). Extend `_parse_resets_at` to accept
   HTTP-date / RFC-1123 strings. Strip upstream `usage.cost` from client
   responses (billing-private, same rule as `usage.evren`). Tier
   `upstream_model_id` values remain configurable placeholders (seed env
   overrides + admin API), documented with OpenRouter examples.
4. **Ops.** `docs/backup-restore.md` (pg_dump/restore, Redis is rebuildable
   from DB, volume + secrets handling) and `docker-compose.prod.yml` (no
   DB/Redis host ports, api not published, Caddy reverse proxy for HTTPS).
   Not deployed anywhere.

## Milestone 2 — Agent security suite (evren-agent)

Adversarial vitest suites under `packages/local-runner/test/` (+ agent-core
where the logic lives):
- `path-safety.adversarial.test.ts`: reserved device names, ADS (`:` streams),
  trailing dots/spaces, mixed slashes, drive-letter tricks, UNC, very long
  paths, 8.3, junctions/symlinks out, denylist (.env, *.pem, id_rsa,
  .git/config). Fix `workspace.ts` for whatever fails (expected: reserved
  names, ADS, trailing dots/spaces are currently unchecked).
- `commands.adversarial.test.ts`: obfuscated PowerShell (IEX variants, string
  concatenation, backticks, env indirection), `cmd /c` chaining (&, &&, |, ;),
  download-and-execute variants, registry/disk/shutdown, deletion outside the
  workspace, output flooding (caps), hung processes / orphan cleanup. Extend
  `dangerous.ts` floors for what fails.
- `prompt-injection.test.ts`: README/comments/tool output carrying hidden
  instructions; the permission engine is never bypassed; approval prompt shows
  the real command; unattended mode cannot use non-allowlisted tools.
- Document remaining limits honestly in `docs/SECURITY.md` (workspace root).

## Milestone 3 — Frontend skeleton + security baseline (`frontend/`)

electron-vite, Electron current stable, React 18 + TS strict, Tailwind,
Zustand, vitest, Playwright (Electron).
- Main process hosts agent-core + local-runner (only place with fs/shell/
  network + gateway client + persistence).
- Renderer: UI only; contextIsolation, no nodeIntegration, sandbox,
  no webview/remote content, window.open + navigation blocked, strict CSP,
  permission requests denied.
- Preload: one narrow typed zod-validated API via contextBridge; IPC sender/
  frame validation in main; shared IPC contract file with every channel
  documented.
- Tokens via Electron safeStorage (DPAPI), `TokenStore` implementation
  replacing the file store behind the existing interface (file store stays for
  CLI; migration path handled).
- better-sqlite3 via electron-rebuild; JSONL fallback tested.
- Backend base URL configurable (default `http://localhost:8000`).
- Markdown sanitized (no dangerouslySetInnerHTML, links → system browser after
  confirmation, code blocks inert).

## Milestones 4–8 — Product (frontend)

- M4: login/register/logout/session restore, first-run privacy notice from
  `/privacy/info` (ack once), settings (backend URL, theme dark-default +
  light, default tier, permission mode).
- M5: projects (native folder picker, validate dir, recents, git-repo warning),
  per-project conversations (titles, resume, rename, delete) on the existing
  local store; layout: left sidebar (projects/conversations), main chat,
  model selector + input at the bottom. Out of scope: scheduled tasks, MCP,
  plugins, skill hub, browser control, computer use, OSINT.
- M6: streaming messages, collapsible tool-step timeline (name, args summary,
  result summary, duration), collapsed dimmed reasoning, stop/retry/copy,
  token/credit counter, empty/error states, Enter/Shift+Enter, Esc, Ctrl+N;
  long outputs without UI freezes.
- M7: approval modal (exact command/path, cwd, risk category, model reason;
  Allow once / Always allow (project, pattern shown) / Deny); per-project
  permission mode (ask every time, auto-accept edits in workspace; NO
  allow-everything); diff viewer (inline/side-by-side), per-conversation
  changed files, undo last change, revert to checkpoint; denied actions
  visible in timeline.
- M8: tier selector from `/v1/models` (display name + real upstream in
  details popover; locked tiers explained), credit/usage indicator from
  `/usage`, friendly errors: quota, subscription inactive, rate limited
  (countdown from Retry-After), offline (retry), token expired (single
  re-login), upstream errors.

## Milestone 9 — Hardening pass

Tests: malicious markdown/HTML/script/SVG in model output, navigation and
window.open blocking, IPC validation + sender checks, CSP present, secrets
absent from logs and renderer-accessible state, safeStorage failure handling.
`pnpm audit` + `pip-audit`, results recorded.

## Milestone 10 — E2E, packaging, launch

1. Playwright Electron E2E against the local stack (backend via docker
   compose, test account via API): login → add sample project (copy of
   `evren-agent/apps/cli/fixtures/sample-repo`) → "The test in this repo is
   failing. Fix it and verify." → approve edit + npm test → see diff → undo.
   Screenshots to `docs/screenshots`. Mock gateway fallback if the real
   upstream is unavailable/rate-limited (stated in the report).
2. electron-builder NSIS installer (unsigned; signing + auto-update TODOs
   documented). Report path + size.
3. Start backend stack if needed, then the built app; leave it running; report
   exact restart commands.
4. Final report in `docs/PROGRESS.md` + root README (layout + how to run each
   part). Prioritized next steps: MCP, GitHub integration, scheduled tasks,
   cloud mode, signing/auto-update, payments.

## Definition of done

All suites green; lint/typecheck clean; security suite in place; app launches
and completes the E2E scenario; docs updated; small well-named commits; no
secrets in the repo.
