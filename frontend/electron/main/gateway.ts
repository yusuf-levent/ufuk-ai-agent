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
  const client = new GatewayClient(auth, baseURL);
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
