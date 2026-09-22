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
const HttpUrlSchema = z
  .url()
  .refine(
    (u) => {
      try {
        return new URL(u).protocol === "http:" || new URL(u).protocol === "https:";
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
