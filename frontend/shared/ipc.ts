/**
 * IPC contract: zod schemas and TypeScript types for every channel in
 * shared/channels.ts. All invoke payloads are validated in the MAIN process
 * against these schemas; responses travel back inside an IpcResult envelope
 * so error shapes survive the bridge (success: { ok: true, value },
 * failure: { ok: false, error: { message, code? } }).
 */
import { z } from "zod";
import type { AgentEvent } from "@evren/agent-core";
import type { EventChannel, InvokeChannel } from "./channels";

// ---------------------------------------------------------------------------
// envelope
// ---------------------------------------------------------------------------

export interface IpcError {
  message: string;
  /** Machine-readable hint for the UI, e.g. 'invalid_credentials'. */
  code?: string;
}

export type IpcResult<T> =
  { ok: true; value: T } | { ok: false; error: IpcError };

export const ok = <T>(value: T): IpcResult<T> => ({ ok: true, value });
export const err = (message: string, code?: string): IpcResult<never> => ({
  ok: false,
  error: { message, code },
});

/** Payload schema per invoke channel (void channels use z.void()-tolerant undefined). */
export type InvokeSchema = z.ZodTypeAny;

// ---------------------------------------------------------------------------
// settings
// ---------------------------------------------------------------------------

/** http(s) only: the gateway is always an HTTP endpoint (z.url() alone accepts ftp: etc.). */
const HttpUrlSchema = z.url().refine(
  (u) => {
    try {
      return (
        new URL(u).protocol === "http:" || new URL(u).protocol === "https:"
      );
    } catch {
      return false;
    }
  },
  { message: "URL must use http or https" },
);

export const SettingsSchema = z.object({
  /** Gateway API root (no /v1). The renderer never fetches it directly. */
  backendUrl: HttpUrlSchema.default("http://localhost:8000"),
  theme: z.enum(["dark", "light"]).default("dark"),
  /** Default tier alias (fast/balanced/strong). */
  defaultTier: z.string().min(1).default("fast"),
  /**
   * Per-project permission mode (Milestone 7): 'ask' prompts for every
   * write/command; 'auto-edits' auto-approves edits inside the workspace.
   * There is intentionally NO allow-everything mode.
   */
  permissionMode: z.enum(["ask", "auto-edits"]).default("ask"),
  /** First-run privacy notice acknowledged (explains gateway routing). */
  privacyAcknowledged: z.boolean().default(false),
});
export type Settings = z.infer<typeof SettingsSchema>;

export const SettingsPatchSchema = SettingsSchema.partial();
export type SettingsPatch = z.infer<typeof SettingsPatchSchema>;

// ---------------------------------------------------------------------------
// auth / session
// ---------------------------------------------------------------------------

export const LoginRequestSchema = z.object({
  email: z.email(),
  password: z.string().min(1),
});
export type LoginRequest = z.infer<typeof LoginRequestSchema>;

export const RegisterRequestSchema = LoginRequestSchema.extend({
  password: z.string().min(8, "password must be at least 8 characters"),
  displayName: z.string().min(1).max(100).optional(),
});
export type RegisterRequest = z.infer<typeof RegisterRequestSchema>;

export const SessionInfoSchema = z.object({
  userId: z.string(),
  email: z.string(),
  displayName: z.string().nullable(),
  /** true when tokens are stored WITHOUT OS-level encryption (DPAPI unavailable). */
  usingPlainTokenStore: z.boolean().default(false),
});
export type SessionInfo = z.infer<typeof SessionInfoSchema>;

/** GET /privacy/info (proxied by main; shape matches the backend contract). */
export const PrivacyInfoSchema = z.object({
  providers: z.array(z.string()).default([]),
  upstreamHost: z.string().nullable().default(null),
  dataHandling: z.string().default(""),
  accountDeletion: z.string().default(""),
});
export type PrivacyInfo = z.infer<typeof PrivacyInfoSchema>;

export const OpenExternalRequestSchema = z.object({
  url: z.url(),
});
export type OpenExternalRequest = z.infer<typeof OpenExternalRequestSchema>;

// ---------------------------------------------------------------------------
// projects & conversations (Milestone 5)
// ---------------------------------------------------------------------------

export const ProjectInfoSchema = z.object({
  /** Normalized workspace root (the project identity everywhere). */
  root: z.string().min(1),
  name: z.string().min(1),
  addedAt: z.string().min(1),
  lastOpenedAt: z.string().min(1),
  /** Per-project permission override ('ask' | 'auto-edits'). */
  permissionMode: z.enum(["ask", "auto-edits"]).optional(),
  /** Informational: the UI warns when a project is not a git repo. */
  isGitRepo: z.boolean(),
});
export type ProjectInfo = z.infer<typeof ProjectInfoSchema>;

export const ProjectPathRequestSchema = z.object({
  path: z.string().min(1),
});
export type ProjectPathRequest = z.infer<typeof ProjectPathRequestSchema>;

export const ProjectRootRequestSchema = z.object({
  root: z.string().min(1),
});
export type ProjectRootRequest = z.infer<typeof ProjectRootRequestSchema>;

/** Summary of a stored conversation (mirrors agent-core). */
export const ConversationSummarySchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  createdAt: z.string().min(1),
  updatedAt: z.string().min(1),
  model: z.string().optional(),
});
export type ConversationSummary = z.infer<typeof ConversationSummarySchema>;

/** Serializable chat message (mirrors agent-core Message). */
export const ChatMessageSchema = z.union([
  z.object({ role: z.literal("system"), content: z.string() }),
  z.object({ role: z.literal("user"), content: z.string() }),
  z.object({
    role: z.literal("assistant"),
    content: z.string().nullable(),
    toolCalls: z
      .array(
        z.object({
          id: z.string(),
          name: z.string(),
          arguments: z.string(),
        }),
      )
      .optional(),
  }),
  z.object({
    role: z.literal("tool"),
    toolCallId: z.string(),
    name: z.string(),
    content: z.string(),
  }),
]);
export type ChatMessage = z.infer<typeof ChatMessageSchema>;

export const ConversationDetailSchema = z.object({
  summary: ConversationSummarySchema,
  messages: z.array(ChatMessageSchema),
});
export type ConversationDetail = z.infer<typeof ConversationDetailSchema>;

export const ConversationIdRequestSchema = z.object({
  root: z.string().min(1),
  id: z.string().min(1),
});
export type ConversationIdRequest = z.infer<typeof ConversationIdRequestSchema>;

export const ConversationRenameRequestSchema =
  ConversationIdRequestSchema.extend({
    title: z.string().min(1).max(200),
  });
export type ConversationRenameRequest = z.infer<
  typeof ConversationRenameRequestSchema
>;

// ---------------------------------------------------------------------------
// chat runs & approvals (Milestone 6)
// ---------------------------------------------------------------------------

export const ChatSendRequestSchema = z.object({
  root: z.string().min(1),
  conversationId: z.string().min(1),
  message: z.string().min(1).max(100_000),
  /** Tier alias override; falls back to conversation/settings default. */
  model: z.string().min(1).max(64).optional(),
});
export type ChatSendRequest = z.infer<typeof ChatSendRequestSchema>;

export const ChatStopRequestSchema = z.object({
  conversationId: z.string().min(1),
});
export type ChatStopRequest = z.infer<typeof ChatStopRequestSchema>;

export const ApprovalRespondRequestSchema = z.object({
  conversationId: z.string().min(1),
  approvalId: z.string().min(1),
  approved: z.boolean(),
  /** "Always allow" (this project) — rule derived in main. */
  remember: z.boolean().default(false),
});
export type ApprovalRespondRequest = z.infer<typeof ApprovalRespondRequestSchema>;

// ---------------------------------------------------------------------------
// approvals, permission modes, checkpoints, diffs (Milestone 7)
// ---------------------------------------------------------------------------

export const ApprovalPreviewRequestSchema = z.object({
  conversationId: z.string().min(1),
  approvalId: z.string().min(1),
});
export type ApprovalPreviewRequest = z.infer<typeof ApprovalPreviewRequestSchema>;

export const ApprovalPreviewSchema = z.object({
  tool: z.string().min(1),
  pattern: z.string().optional(),
});
export type ApprovalPreview = z.infer<typeof ApprovalPreviewSchema>;

export const SetPermissionModeRequestSchema = z.object({
  root: z.string().min(1),
  mode: z.enum(["ask", "auto-edits"]),
});
export type SetPermissionModeRequest = z.infer<
  typeof SetPermissionModeRequestSchema
>;

export const CheckpointInfoSchema = z.object({
  id: z.string().min(1),
  createdAt: z.string().min(1),
  tool: z.string(),
  files: z.array(
    z.object({
      path: z.string(),
      existedBefore: z.boolean(),
    }),
  ),
});
export type CheckpointInfo = z.infer<typeof CheckpointInfoSchema>;

export const CheckpointRevertRequestSchema = z.object({
  root: z.string().min(1),
  id: z.string().min(1),
});
export type CheckpointRevertRequest = z.infer<typeof CheckpointRevertRequestSchema>;

export const DiffRequestSchema = z.object({
  root: z.string().min(1),
  path: z.string().min(1),
  checkpointId: z.string().min(1).optional(),
});
export type DiffRequest = z.infer<typeof DiffRequestSchema>;

export const DiffLineSchema = z.object({
  kind: z.enum(["add", "del", "ctx"]),
  text: z.string(),
  oldLine: z.number().nullable(),
  newLine: z.number().nullable(),
});
export type DiffLine = z.infer<typeof DiffLineSchema>;

export const DiffHunkSchema = z.object({
  oldStart: z.number(),
  newStart: z.number(),
  lines: z.array(DiffLineSchema),
});
export type DiffHunk = z.infer<typeof DiffHunkSchema>;

export const DiffResponseSchema = z.object({
  path: z.string(),
  /** true when no checkpoint retains the pre-change content */
  snapshotMissing: z.boolean(),
  identical: z.boolean(),
  oldLines: z.number(),
  newLines: z.number(),
  hunks: z.array(DiffHunkSchema),
});
export type DiffResponse = z.infer<typeof DiffResponseSchema>;

export const ChangedFileSchema = z.object({
  path: z.string(),
  tool: z.string(),
  ok: z.boolean(),
  at: z.string(),
});
export type ChangedFile = z.infer<typeof ChangedFileSchema>;

// ---------------------------------------------------------------------------
// tiers & usage (Milestone 8)
// ---------------------------------------------------------------------------

/** A tier the current plan allows (details from /v1/models). */
export const TierOptionSchema = z.object({
  id: z.string().min(1),
  displayName: z.string().optional(),
  upstreamProvider: z.string().optional(),
  upstreamModel: z.string().optional(),
  maxOutputTokens: z.number().optional(),
  contextWindow: z.number().optional(),
});
export type TierOption = z.infer<typeof TierOptionSchema>;

/** A tier that exists but is not on the current plan. */
export const LockedTierSchema = z.object({
  id: z.string().min(1),
  reason: z.string().min(1),
});
export type LockedTier = z.infer<typeof LockedTierSchema>;

export const TierCatalogSchema = z.object({
  allowed: z.array(TierOptionSchema),
  locked: z.array(LockedTierSchema),
});
export type TierCatalog = z.infer<typeof TierCatalogSchema>;

export const UsageInfoSchema = z.object({
  planName: z.string(),
  creditLimit: z.number(),
  creditsUsed: z.number(),
  creditsRemaining: z.number(),
  requestsPerMinute: z.number(),
  periodEnd: z.string().optional(),
});
export type UsageInfo = z.infer<typeof UsageInfoSchema>;

/** Structured chat error info (actionable UI in the renderer). */
export const ChatErrorInfoSchema = z.object({
  code: z.enum([
    "quota_exceeded",
    "subscription_inactive",
    "model_not_allowed",
    "rate_limited",
    "reauth_required",
    "gateway_unreachable",
    "upstream_unavailable",
    "upstream_error",
    "timeout",
  ]),
  /** Milliseconds to wait (rate limit / circuit breaker), when known. */
  retryAfterMs: z.number().optional(),
});
export type ChatErrorInfo = z.infer<typeof ChatErrorInfoSchema>;

export const AppVersionResponseSchema = z.object({
  version: z.string(),
  electron: z.string(),
  node: z.string(),
});
export type AppVersionResponse = z.infer<typeof AppVersionResponseSchema>;

// ---------------------------------------------------------------------------
// main -> renderer events
// ---------------------------------------------------------------------------

/** Payload of the chatEvent channel: an agent event tagged with the run. */
export interface ChatEventPayload {
  conversationId: string;
  event: AgentEvent;
  /** Structured error info attached to fatal error events (M8). */
  errorInfo?: ChatErrorInfo;
}

// ---------------------------------------------------------------------------
// request/response mapping (type-level table)
// ---------------------------------------------------------------------------

export interface InvokeMap {
  "app:version": { request: undefined; response: AppVersionResponse };
  "settings:get": { request: undefined; response: Settings };
  "settings:set": { request: SettingsPatch; response: Settings };
  "auth:login": { request: LoginRequest; response: null };
  "auth:register": { request: RegisterRequest; response: null };
  "auth:logout": { request: undefined; response: null };
  "auth:session": { request: undefined; response: SessionInfo | null };
  "privacy:info": { request: undefined; response: PrivacyInfo };
  "shell:open-external": { request: OpenExternalRequest; response: boolean };
  "projects:list": { request: undefined; response: ProjectInfo[] };
  "projects:add": { request: ProjectPathRequest; response: ProjectInfo };
  "projects:remove": { request: ProjectPathRequest; response: null };
  "projects:pick-folder": { request: undefined; response: string | null };
  "conversations:list": {
    request: ProjectRootRequest;
    response: ConversationSummary[];
  };
  "conversations:create": {
    request: ProjectRootRequest;
    response: ConversationSummary;
  };
  "conversations:load": {
    request: ConversationIdRequest;
    response: ConversationDetail | null;
  };
  "conversations:rename": {
    request: ConversationRenameRequest;
    response: boolean;
  };
  "conversations:delete": {
    request: ConversationIdRequest;
    response: boolean;
  };
  "chat:send": { request: ChatSendRequest; response: null };
  "chat:stop": { request: ChatStopRequest; response: boolean };
  "approvals:respond": {
    request: ApprovalRespondRequest;
    response: boolean;
  };
  "approvals:preview": {
    request: ApprovalPreviewRequest;
    response: ApprovalPreview | null;
  };
  "projects:set-permission-mode": {
    request: SetPermissionModeRequest;
    response: ProjectInfo;
  };
  "checkpoints:list": {
    request: ProjectRootRequest;
    response: CheckpointInfo[];
  };
  "checkpoints:undo": {
    request: ProjectRootRequest;
    response: CheckpointInfo | null;
  };
  "checkpoints:revert": {
    request: CheckpointRevertRequest;
    response: CheckpointInfo | null;
  };
  "checkpoints:diff": { request: DiffRequest; response: DiffResponse };
  "conversations:changed-files": {
    request: ConversationIdRequest;
    response: ChangedFile[];
  };
  "models:list": { request: undefined; response: TierCatalog };
  "usage:get": { request: undefined; response: UsageInfo };
}

/** Typed invoke signature used by the renderer client. */
export type TypedInvoke = <C extends InvokeChannel>(
  channel: C,
  ...args: InvokeMap[C]["request"] extends undefined
    ? [payload?: undefined]
    : [payload: InvokeMap[C]["request"]]
) => Promise<IpcResult<InvokeMap[C]["response"]>>;

export interface EventMap {
  "chat:event": ChatEventPayload;
}

export type TypedSubscribe = <C extends EventChannel>(
  channel: C,
  listener: (payload: EventMap[C]) => void,
) => () => void;
