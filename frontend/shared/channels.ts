/**
 * IPC channel names — the single source of truth for the Ufuk bridge.
 *
 * The preload exposes exactly two functions (invoke/subscribe) and only
 * forwards the channels allowlisted here. The main process re-validates the
 * sender for every invoke and zod-validates every payload (shared/ipc.ts).
 * Adding a channel requires: a constant here, a zod schema + handler in
 * shared/ipc.ts + electron/main/ipc.ts, and a typed wrapper in
 * src/ipc/client.ts. Renderer -> main is always `invoke` (request/response);
 * main -> renderer streaming uses `subscribe` (chat events, approvals).
 */

/** Renderer -> main, request/response (zod-validated in main). */
export const INVOKE_CHANNELS = {
  /** App metadata. Request: void. Response: AppVersionResponse. */
  appVersion: "app:version",
  /** Read all settings. Request: void. Response: Settings. */
  settingsGet: "settings:get",
  /** Patch settings (partial). Request: SettingsPatch. Response: Settings. */
  settingsSet: "settings:set",
  /**
   * Log in against the gateway. Request: LoginRequest. Response: void.
   * Errors: invalid credentials, gateway unreachable.
   */
  authLogin: "auth:login",
  /**
   * Register + log in. Request: RegisterRequest. Response: void.
   */
  authRegister: "auth:register",
  /** Revoke the session and clear stored tokens. Request: void. Response: void. */
  authLogout: "auth:logout",
  /**
   * Current session (from /me) or null when logged out.
   * Request: void. Response: SessionInfo | null.
   */
  authSession: "auth:session",
  /**
   * First-run privacy notice (proxied from the gateway's /privacy/info).
   * Request: void. Response: PrivacyInfo.
   */
  privacyInfo: "privacy:info",
  /**
   * Open an http(s) URL in the system browser AFTER a native confirmation
   * dialog (used by rendered markdown links). Request: { url }.
   * Response: boolean (true when opened).
   */
  openExternal: "shell:open-external",
  /** Recent projects (validated workspace roots). Response: ProjectInfo[]. */
  projectsList: "projects:list",
  /**
   * Validate + remember a project folder. Request: { path } (absolute).
   * Response: ProjectInfo. Errors: not_a_directory, path_unsafe.
   */
  projectsAdd: "projects:add",
  /** Forget a project (conversations stay on disk). Request: { path }. */
  projectsRemove: "projects:remove",
  /**
   * Native folder picker (OS dialog, main process only).
   * Response: absolute path or null when cancelled.
   */
  projectsPickFolder: "projects:pick-folder",
  /**
   * Conversations of a project. Request: { root }. Response:
   * ConversationSummary[] (updatedAt DESC).
   */
  conversationsList: "conversations:list",
  /**
   * Create a conversation in a project (model = settings.defaultTier).
   * Request: { root }. Response: ConversationSummary.
   */
  conversationsCreate: "conversations:create",
  /**
   * Load one conversation (resume/preview). Request: { root, id }.
   * Response: ConversationDetail | null.
   */
  conversationsLoad: "conversations:load",
  /**
   * Rename a conversation. Request: { root, id, title } (1-200 chars).
   * Response: boolean (false when the id is unknown).
   */
  conversationsRename: "conversations:rename",
  /**
   * Delete a conversation (messages + tool calls). Request: { root, id }.
   * Response: boolean.
   */
  conversationsDelete: "conversations:delete",
  /**
   * Send a user message to a conversation (starts an agent run). Request:
   * { root, conversationId, message, model? }. Response: null. All further
   * updates arrive as chat:event pushes (agent events + run lifecycle).
   */
  chatSend: "chat:send",
  /**
   * Abort the active run of a conversation. Partial work is persisted.
   * Request: { conversationId }. Response: boolean (false = no run).
   */
  chatStop: "chat:stop",
  /**
   * Answer an approval_request pushed via chat:event. Request:
   * { conversationId, approvalId, approved, remember }. Response: boolean.
   */
  approvalsRespond: "approvals:respond",
  /**
   * Preview the "always allow" rule for a pending approval (shown in the
   * modal). Request: { conversationId, approvalId }. Response:
   * { tool, pattern? } | null.
   */
  approvalsPreview: "approvals:preview",
  /**
   * Set the per-project permission mode (ask / auto-edits). Request:
   * { root, mode }. Response: ProjectInfo.
   */
  projectsSetPermissionMode: "projects:set-permission-mode",
  /**
   * Checkpoints of a project (newest first). Request: { root }.
   * Response: CheckpointInfo[].
   */
  checkpointsList: "checkpoints:list",
  /** Undo the newest checkpoint. Request: { root }. Response: CheckpointInfo | null. */
  checkpointsUndo: "checkpoints:undo",
  /** Revert to a checkpoint (consumes it and everything newer). Request: { root, id }. */
  checkpointsRevert: "checkpoints:revert",
  /**
   * Diff a file against its newest checkpoint snapshot (pre-change
   * content). Request: { root, path, checkpointId? }. Response:
   * DiffResponse (current content + hunks; snapshotMissing flag when no
   * checkpoint retains the file).
   */
  checkpointsDiff: "checkpoints:diff",
  /**
   * Files changed by a conversation (from its recorded tool calls).
   * Request: { root, id }. Response: ChangedFile[].
   */
  conversationsChangedFiles: "conversations:changed-files",
  /**
   * Tier catalog for the selector: allowed tiers (from /v1/models, with
   * display names + upstream details) and tiers locked by the plan (from
   * /plans, with an explanation). Request: void. Response: TierCatalog.
   * Errors: reauth_required, subscription_inactive, gateway_unreachable.
   */
  modelsList: "models:list",
  /**
   * Credit/usage snapshot from /usage. Request: void. Response: UsageInfo.
   * Errors: subscription_inactive (no active plan), reauth_required,
   * gateway_unreachable.
   */
  usageGet: "usage:get",
  /**
   * Connectivity check for Settings: fetches GET {backendUrl}/health through
   * the gateway session (no auth needed). Request: void. Response:
   * GatewayHealthResponse { ok, detail } — ok is false on HTTP/network
   * errors, the channel itself never rejects.
   */
  gatewayTest: "gateway:test",
  /**
   * Open the Electron user-data folder in the OS file explorer. Request:
   * void. Response: boolean. The path itself is never returned to the
   * renderer (path disclosure stays in main).
   */
  appOpenUserData: "app:open-user-data",
} as const;

/** Main -> renderer, push events (payload schemas in shared/ipc.ts). */
export const EVENT_CHANNELS = {
  /**
   * Agent run events for a conversation: message deltas, reasoning deltas,
   * tool calls/results, approval requests, usage, errors, done — tagged
   * with the conversationId (payload: ChatEventPayload).
   */
  chatEvent: "chat:event",
} as const;

export type InvokeChannel =
  (typeof INVOKE_CHANNELS)[keyof typeof INVOKE_CHANNELS];
export type EventChannel = (typeof EVENT_CHANNELS)[keyof typeof EVENT_CHANNELS];

export const INVOKE_CHANNEL_SET: ReadonlySet<string> = new Set(
  Object.values(INVOKE_CHANNELS),
);
export const EVENT_CHANNEL_SET: ReadonlySet<string> = new Set(
  Object.values(EVENT_CHANNELS),
);
