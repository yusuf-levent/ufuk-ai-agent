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
} as const;

/** Main -> renderer, push events (payload schemas in shared/ipc.ts). */
export const EVENT_CHANNELS = {
  /**
   * Agent run events for the active conversation (message deltas, tool
   * calls/results, approvals, usage, errors, done). Payload: ChatEvent.
   * Wired up in Milestone 5/6; declared now to freeze the contract.
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
