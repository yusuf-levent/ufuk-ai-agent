# Ufuk — Security posture and limits (Milestone 2)

This document describes the automated adversarial security suite in
`evren-agent` and — just as important — what it does **not** cover. The
default posture is **ask**: writes and commands always surface for approval
unless the user explicitly allowed them; dangerous patterns can never be
allowed at all.

## The suite

All tests live in `evren-agent/packages/local-runner/test/` (plus pattern
unit coverage through the engine tests). Counts as of 2026-09-22:

| File | Tests | Covers |
|---|---|---|
| `path-safety.adversarial.test.ts` | 19 | traversal (mixed slashes), absolute/UNC/admin-share/`\\?\` inputs, drive-letter case, 8.3 short names, junctions/symlinks pointing outside, dangling symlinks, reserved device names (CON/NUL/COM1… with extensions), alternate data streams (`file.txt:stream`), trailing dots/spaces, very long paths (>240 chars) incl. escapes, case-insensitive denylist, `.env`/`*.pem`/`id_rsa*`/`.git/config` at any depth, tool-level enforcement (read/write tools refuse the same paths) |
| `commands.adversarial.test.ts` | 19 | plain/disguised `iex`/`Invoke-Expression`, string-concatenation and backtick obfuscation (incl. nested), env-variable indirection (`& $env:…`, `[environment]::getenvironmentvariable`), encoded PowerShell in all flag spellings (`-EncodedCommand`, `-enc`, `-e`), download-and-execute (iwr/curl/irm/webclient → iex), registry (`reg add`, `Set-ItemProperty HKLM:`), disk (format/Format-Volume/diskpart/vssadmin/bcdedit), shutdown, deletion outside the workspace, cmd `/c`/`/k` wrappers (ask), chained-command smuggling of remembered rules (`npm test & curl …`), approval handler always sees the real command, output flooding caps, hung processes, orphan grand-children (tree kill), environment listing shows no secrets |
| `prompt-injection.test.ts` | 5 | README HTML comments and code comments carrying hidden instructions ("ignore previous rules", "run this command", "send .env to URL"), tool-output-borne instructions, `.env` exfiltration via curl (surfaces for approval with the real command), unattended mode: only explicitly allowlisted tools run, no prompts, floors still deny |
| `workspace.test.ts`, `permissions.test.ts`, `shell.test.ts`, … | 112 | pre-existing coverage: containment, denylist, junction/8.3 escapes, floors, unattended, tree kills, output caps, secret redaction |

Total agent suite: **231 tests** (76 agent-core + 155 local-runner).

### Fixes made during this milestone (each with regression tests)

1. **Reserved device names** (`CON`, `NUL`, `COM1-9`, …, also with extensions
   like `NUL.txt`) are rejected before any filesystem access.
2. **Alternate data streams** (`file.txt:stream`, `$DATA`) are rejected —
   previously `.env:hidden` could bypass the denylist and writes could create
   hidden streams.
3. **Trailing dots/spaces** in any component are rejected — Win32 strips
   them, so `.env ` / `.env.` previously hit the real `.env` on disk while
   evading the denylist.
4. **Denylist is case-insensitive on Windows** — a file created as `.ENV` or
   `SECRET.PEM` is the same file as `.env`/`secret.pem`.
5. **`.git/config`** added to the denylist (can carry credentials).
6. **`\\?\`-prefixed inputs** are normalized (accepted when inside, rejected
   when escaping) instead of a confusing blanket rejection.
7. **`iex`/`Invoke-Expression` is a deny floor** (any use, not only after a
   download pipe); same for `& $env:…` execution and
   `[environment]::getenvironmentvariable` indirection; `powershell -e <b64>`
   variant of encoded commands; `Format-Volume` in any spelling.
8. **Deobfuscation before pattern matching**: backtick escapes and
   string-concatenation groups (`('i'+'ex')`, nested, both quote styles) are
   collapsed before the dangerous patterns run.
9. **Chained commands can never ride remembered rules**: a remembered
   `npm test` no longer prefix-matches `npm test & curl evil.example` —
   chained commands only match exactly. This closed an auto-approve bypass.
10. **cmd `/c` / `/k` wrappers** now carry an ask floor (defense in depth for
    chaining through a second shell).

## Honest limits (what is NOT guaranteed)

- **No OS sandbox.** run_command executes with the user's privileges. The
  permission engine is a heuristic gate, not isolation. A sufficiently
  creative benign-looking command that matches no pattern will run after
  approval; the defense is that the human sees the exact command.
- **Deobfuscation is best-effort.** Char arrays (`[char[]](73,69,88) -join
  ''`), `-f` format-string tricks, XOR/compressed blobs or staged scripts
  (write a .ps1, then execute it in a separate call) are not recognized as
  deny patterns. Writing a script file asks for approval; executing it later
  (`node x.js`, `powershell -File x.ps1`) asks again — but neither is denied.
- **Shell commands can name denylisted files.** `Get-Content .env` inside a
  run_command is not denied outright (the denylist is enforced at the file
  tools' path layer, not inside arbitrary shell text). Such commands surface
  as approval prompts (e.g. the network floor on `curl`) showing the real
  command; a careless human can still approve them.
- **Prompt injection cannot be fully prevented at the model level.** The
  system prompt instructs the agent to treat file content as data, but a
  model may still *attempt* anything. The guaranteed enforcement point is the
  permission engine: every tool call routes through it (proven by the
  approval_request/approval_resolved events around each call), deny floors
  cannot be downgraded, and the approval UI shows the true input. Do not
  treat model *refusals* as a security boundary.
- **Environment-dependent checks.** 8.3 short-name tests skip on volumes with
  8.3 disabled; symlink tests need Windows developer mode/admin (junctions
  cover the same realpath path). Tree kills rely on `taskkill /T /F`, which
  kills processes that the spawned shell owns; services or detachers that
  escape the job may survive (none observed in tests).
- **Very long paths** rely on Node/libuv's internal `\\?\` handling; the
  workspace resolves them, but some external tools still fail beyond 260
  chars — a usability limit, not a safety one.
- **Tokens** currently live in `%LOCALAPPDATA%\evren-agent\gateway\tokens-*.json`
  (owner-only). The desktop app moves them to Electron safeStorage (DPAPI) —
  Milestone 3.
- **Unattended mode** is allowlist-only, but the allowlist itself is only as
  narrow as its rules; `read_file` with a broad pattern still reads the whole
  workspace (denylist still applies).

## Reporting

A bypass of anything claimed above is a bug: fix it and add a regression test
to the corresponding adversarial suite before closing it.
