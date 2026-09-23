/**
 * Gateway session manager (main process only). Owns the GatewayAuth
 * (login/register/logout/refresh) plus a GatewayClient for /v1/models and
 * /usage. Rebuilt when the backend URL setting changes. Tokens live in the
 * safeStorage-backed store and never reach the renderer.
 */
import { createHash } from "node:crypto";
import * as path from "node:path";
import {
  GatewayAuth,
  GatewayClient,
  ReauthRequiredError,
} from "@evren/agent-core";
import {
  createTokenStore,
  type CreatedTokenStore,
  type SafeStorageLike,
} from "./token-store";
import type { Settings } from "@shared/ipc";

export interface GatewaySession {
  auth: GatewayAuth;
  client: GatewayClient;
  tokenStore: CreatedTokenStore;
  /** Absolute path of the (safeStorage-encrypted) token file. */
  tokenFile: string;
  baseURL: string;
  /** Fetch used by every session helper (injectable for tests). */
  fetchImpl: typeof fetch;
}

export function buildGatewaySession(
  settings: Settings,
  userDataDir: string,
  safe: SafeStorageLike,
  /** Injectable fetch for tests (defaults to global fetch). */
  fetchImpl?: typeof fetch,
): GatewaySession {
  const baseURL = settings.backendUrl.replace(/\/+$/, "");
  const hash = createHash("sha256")
    .update(baseURL.toLowerCase())
    .digest("hex")
    .slice(0, 12);
  const tokenFile = path.join(userDataDir, "gateway", `tokens-${hash}.bin`);
  const tokenStore = createTokenStore(tokenFile, safe);
  const auth = new GatewayAuth({ baseURL, store: tokenStore.store, fetchImpl });
  const client = new GatewayClient(auth, baseURL, fetchImpl);
  return {
    auth,
    client,
    tokenStore,
    tokenFile,
    baseURL,
    fetchImpl: fetchImpl ?? fetch,
  };
}

/** Map auth errors to renderer-friendly IpcError codes. */
export function authErrorCode(err: unknown): {
  message: string;
  code?: string;
} {
  if (err instanceof ReauthRequiredError) {
    return { message: err.message, code: "reauth_required" };
  }
  if (err instanceof Error) {
    if (err.message.startsWith("Gateway unreachable")) {
      return {
        message: "Cannot reach the backend. Is it running?",
        code: "gateway_unreachable",
      };
    }
    if (err.message.includes("HTTP 401")) {
      return {
        message: "Invalid email or password.",
        code: "invalid_credentials",
      };
    }
    if (err.message.includes("HTTP 400")) {
      return {
        message: err.message.replace(
          /^Gateway auth error \(HTTP 400\):\s*/,
          "",
        ),
        code: "registration_failed",
      };
    }
    return { message: err.message };
  }
  return { message: String(err) };
}

/** GET /me through the main process (never exposed to the renderer directly). */
export async function fetchSessionInfo(session: GatewaySession): Promise<{
  userId: string;
  email: string;
  displayName: string | null;
} | null> {
  let token: string;
  try {
    token = await session.auth.getAccessToken();
  } catch {
    return null; // not logged in (or refresh failed) — treated as logged out
  }
  const res = await session.fetchImpl(`${session.baseURL}/me`, {
    headers: { authorization: `Bearer ${token}` },
  });
  if (res.status === 401) return null;
  if (!res.ok) {
    throw new Error(`Gateway error (HTTP ${res.status})`);
  }
  const body = (await res.json()) as {
    id?: unknown;
    email?: unknown;
    display_name?: unknown;
  };
  if (typeof body.id !== "string" || typeof body.email !== "string")
    return null;
  return {
    userId: body.id,
    email: body.email,
    displayName:
      typeof body.display_name === "string" ? body.display_name : null,
  };
}

/** GET /privacy/info (public endpoint, proxied through main). */
export async function fetchPrivacyInfo(session: GatewaySession): Promise<{
  providers: string[];
  upstreamHost: string | null;
  dataHandling: string;
  accountDeletion: string;
}> {
  const res = await session.fetchImpl(`${session.baseURL}/privacy/info`);
  if (!res.ok) {
    throw new Error(`Gateway error (HTTP ${res.status})`);
  }
  const body = (await res.json()) as Record<string, unknown>;
  return {
    providers: Array.isArray(body["upstream_providers"])
      ? body["upstream_providers"].filter(
          (p): p is string => typeof p === "string",
        )
      : [],
    upstreamHost:
      typeof body["upstream_base_url_host"] === "string"
        ? body["upstream_base_url_host"]
        : null,
    dataHandling:
      typeof body["data_handling"] === "string" ? body["data_handling"] : "",
    accountDeletion:
      typeof body["account_deletion"] === "string"
        ? body["account_deletion"]
        : "",
  };
}

// ---------------------------------------------------------------------------
// tiers & usage (Milestone 8)
// ---------------------------------------------------------------------------

/** Map GatewayClient/getJson errors to coded IpcErrors for the renderer. */
export function mapClientError(err: unknown): {
  message: string;
  code: string;
} {
  if (err instanceof ReauthRequiredError) {
    return {
      message: "Session expired. Please log in again.",
      code: "reauth_required",
    };
  }
  const message = err instanceof Error ? err.message : String(err);
  if (message.startsWith("Gateway unreachable")) {
    return {
      message: "Cannot reach the backend. Is it running?",
      code: "gateway_unreachable",
    };
  }
  const statusMatch = /Gateway HTTP (\d+)/.exec(message);
  if (statusMatch) {
    const code = /"code"\s*:\s*"([a-z_]+)"/.exec(message)?.[1];
    if (statusMatch[1] === "403" && code === "subscription_inactive") {
      return {
        message: "Your account has no active subscription.",
        code: "subscription_inactive",
      };
    }
    if (code) {
      return { message, code };
    }
    return { message, code: `http_${statusMatch[1]}` };
  }
  return { message, code: "unknown" };
}

export interface FetchedTierCatalog {
  allowed: {
    id: string;
    displayName?: string;
    upstreamProvider?: string;
    upstreamModel?: string;
    maxOutputTokens?: number;
    contextWindow?: number;
  }[];
  locked: { id: string; reason: string }[];
}

/**
 * Tier catalog: allowed tiers from /v1/models (plan-filtered by the
 * backend, with display names + upstream details) plus tiers that exist on
 * other plans (public /plans endpoint) but not on the user's — shown
 * locked with an explanation.
 */
export async function fetchTierCatalog(
  session: GatewaySession,
): Promise<FetchedTierCatalog> {
  const models = await session.client.listModels();
  const allowed = models.map((m) => ({
    id: m.id,
    displayName: m.displayName,
    upstreamProvider: m.upstreamProvider,
    upstreamModel: m.upstreamModel,
    maxOutputTokens: m.maxOutputTokens,
    contextWindow: m.contextWindow,
  }));
  const locked: { id: string; reason: string }[] = [];
  try {
    const res = await session.fetchImpl(`${session.baseURL}/plans`);
    if (res.ok) {
      const plans = (await res.json()) as Array<{
        name?: unknown;
        allowed_tier_aliases?: unknown;
      }>;
      const mine = new Set(allowed.map((t) => t.id));
      const others = new Map<string, string>();
      for (const plan of Array.isArray(plans) ? plans : []) {
        const name =
          typeof plan.name === "string" ? plan.name : "another plan";
        if (!Array.isArray(plan.allowed_tier_aliases)) continue;
        for (const alias of plan.allowed_tier_aliases) {
          if (typeof alias === "string" && !mine.has(alias)) {
            others.set(alias, name);
          }
        }
      }
      for (const [id, planName] of others) {
        locked.push({
          id,
          reason: `Not available on your plan (available on ${planName}).`,
        });
      }
    }
  } catch {
    // plans endpoint unreachable: show only allowed tiers
  }
  return { allowed, locked };
}

export interface FetchedUsage {
  planName: string;
  creditLimit: number;
  creditsUsed: number;
  creditsRemaining: number;
  requestsPerMinute: number;
  periodEnd?: string;
}

/** Credit/usage snapshot from /usage via the GatewayClient. */
export async function fetchUsage(
  session: GatewaySession,
): Promise<FetchedUsage> {
  const usage = await session.client.getUsage();
  return {
    planName: usage.planName,
    creditLimit: usage.creditLimit,
    creditsUsed: usage.creditsUsed,
    creditsRemaining: usage.creditsRemaining,
    requestsPerMinute: usage.requestsPerMinute,
    periodEnd: usage.periodEnd,
  };
}
