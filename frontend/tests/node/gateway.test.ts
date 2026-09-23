// @vitest-environment node
/** Gateway session wiring: token namespacing per backend URL, error mapping. */
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterAll, describe, expect, it, vi } from "vitest";
import { ReauthRequiredError } from "@evren/agent-core";
import {
  authErrorCode,
  buildGatewaySession,
  fetchSessionInfo,
  fetchTierCatalog,
  fetchUsage,
  mapClientError,
} from "../../electron/main/gateway";
import { fakeSafe } from "./helpers/fake-safe-storage";

const dirs: string[] = [];
const tmp = (): string => {
  const d = mkdtempSync(path.join(tmpdir(), "ufuk-gw-"));
  dirs.push(d);
  return d;
};
afterAll(() => {
  for (const d of dirs) rmSync(d, { recursive: true, force: true });
});

const settings = (backendUrl: string) => ({
  backendUrl,
  theme: "dark" as const,
  defaultTier: "fast",
  permissionMode: "ask" as const,
  privacyAcknowledged: true,
});

/** Mock gateway: /auth/login + /auth/refresh tokens, /me profile. */
const gatewayMock = () =>
  vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.endsWith("/auth/login")) {
      expect(init?.method).toBe("POST");
      return new Response(
        JSON.stringify({
          access_token: "acc-1",
          refresh_token: "ref-1",
          token_type: "bearer",
          expires_in: 900,
        }),
        { status: 200 },
      );
    }
    if (url.endsWith("/auth/refresh")) {
      return new Response(
        JSON.stringify({
          access_token: "acc-2",
          refresh_token: "ref-2",
          token_type: "bearer",
          expires_in: 900,
        }),
        { status: 200 },
      );
    }
    if (url.endsWith("/me")) {
      const auth =
        (init?.headers as Record<string, string>)?.authorization ?? "";
      if (auth === "Bearer acc-1" || auth === "Bearer acc-2") {
        return new Response(
          JSON.stringify({
            id: "u1",
            email: "u@example.com",
            display_name: "U",
          }),
          { status: 200 },
        );
      }
      return new Response("{}", { status: 401 });
    }
    throw new Error(`unexpected fetch: ${url}`);
  });

describe("buildGatewaySession", () => {
  it("namespaces token files per backend URL (no cross-backend token reuse)", () => {
    const dir = tmp();
    const a = buildGatewaySession(
      settings("http://localhost:8000"),
      dir,
      fakeSafe(),
    );
    const b = buildGatewaySession(
      settings("http://other.example"),
      dir,
      fakeSafe(),
    );
    expect(a.tokenFile).not.toBe(b.tokenFile);
    expect(path.dirname(a.tokenFile)).toBe(path.join(dir, "gateway"));
    expect(path.basename(a.tokenFile)).toMatch(/^tokens-[0-9a-f]{12}\.bin$/);
  });

  it("normalizes trailing slashes so the same backend shares one namespace", () => {
    const dir = tmp();
    const a = buildGatewaySession(
      settings("http://localhost:8000/"),
      dir,
      fakeSafe(),
    );
    const b = buildGatewaySession(
      settings("http://localhost:8000"),
      dir,
      fakeSafe(),
    );
    expect(a.baseURL).toBe("http://localhost:8000");
    expect(b.baseURL).toBe("http://localhost:8000");
    expect(a.tokenFile).toBe(b.tokenFile);
  });

  it("uses the plain fallback (flagged) when safeStorage is unavailable", () => {
    const s = buildGatewaySession(
      settings("http://localhost:8000"),
      tmp(),
      fakeSafe(false),
    );
    expect(s.tokenStore.usingPlainFallback).toBe(true);
  });
});

describe("authErrorCode", () => {
  it("maps ReauthRequiredError to reauth_required", () => {
    expect(authErrorCode(new ReauthRequiredError())).toEqual({
      message: expect.any(String),
      code: "reauth_required",
    });
  });

  it("maps gateway-unreachable errors to a friendly message", () => {
    const mapped = authErrorCode(
      new Error("Gateway unreachable: connection refused"),
    );
    expect(mapped.code).toBe("gateway_unreachable");
    expect(mapped.message).toContain("Cannot reach the backend");
  });

  it("maps HTTP 401 to invalid_credentials", () => {
    expect(
      authErrorCode(new Error("Gateway auth error (HTTP 401): bad credentials"))
        .code,
    ).toBe("invalid_credentials");
  });

  it("maps HTTP 400 to registration_failed with the backend detail", () => {
    const mapped = authErrorCode(
      new Error("Gateway auth error (HTTP 400): email already registered"),
    );
    expect(mapped.code).toBe("registration_failed");
    expect(mapped.message).toBe("email already registered");
  });

  it("passes unknown errors through without inventing codes", () => {
    expect(authErrorCode(new Error("boom"))).toEqual({ message: "boom" });
    expect(authErrorCode("not an error")).toEqual({ message: "not an error" });
  });
});

describe("fetchSessionInfo", () => {
  it("returns null when there is no stored session (logged out)", async () => {
    const fetchMock = gatewayMock();
    const s = buildGatewaySession(
      settings("http://localhost:8000"),
      tmp(),
      fakeSafe(),
      fetchMock,
    );
    expect(await fetchSessionInfo(s)).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns the /me profile with the access token attached to the request", async () => {
    const fetchMock = gatewayMock();
    const s = buildGatewaySession(
      settings("http://localhost:8000"),
      tmp(),
      fakeSafe(),
      fetchMock,
    );
    await s.auth.login("u@example.com", "pw");
    const info = await fetchSessionInfo(s);
    expect(info).toEqual({
      userId: "u1",
      email: "u@example.com",
      displayName: "U",
    });
    const meCall = fetchMock.mock.calls.find(([url]) =>
      url.toString().endsWith("/me"),
    );
    expect((meCall?.[1] as RequestInit | undefined)?.headers).toMatchObject({
      authorization: expect.stringMatching(/^Bearer /),
    });
  });

  it("returns null on 401 (expired session)", async () => {
    const fetchMock = gatewayMock();
    const s = buildGatewaySession(
      settings("http://localhost:8000"),
      tmp(),
      fakeSafe(),
      fetchMock,
    );
    await s.auth.login("u@example.com", "pw");
    // make /me reject every token after login
    fetchMock.mockImplementation(
      async () => new Response("{}", { status: 401 }),
    );
    expect(await fetchSessionInfo(s)).toBeNull();
  });

  it("surfaces gateway errors for non-auth failures", async () => {
    const fetchMock = gatewayMock();
    const s = buildGatewaySession(
      settings("http://localhost:8000"),
      tmp(),
      fakeSafe(),
      fetchMock,
    );
    await s.auth.login("u@example.com", "pw");
    fetchMock.mockImplementation(
      async () => new Response("{}", { status: 500 }),
    );
    await expect(fetchSessionInfo(s)).rejects.toThrow("HTTP 500");
  });
});

describe("mapClientError (M8 error codes)", () => {
  it("maps reauth, unreachable and HTTP-status client errors", () => {
    expect(mapClientError(new ReauthRequiredError())).toMatchObject({
      code: "reauth_required",
    });
    expect(
      mapClientError(new Error("Gateway unreachable: connection refused")),
    ).toMatchObject({ code: "gateway_unreachable" });
    expect(
      mapClientError(
        new Error(
          'Gateway HTTP 403: {"error": {"code": "subscription_inactive"}}',
        ),
      ),
    ).toMatchObject({ code: "subscription_inactive" });
    expect(
      mapClientError(
        new Error('Gateway HTTP 402: {"error": {"code": "quota_exceeded"}}'),
      ),
    ).toMatchObject({ code: "quota_exceeded" });
    expect(mapClientError(new Error("Gateway HTTP 500: boom"))).toMatchObject({
      code: "http_500",
    });
    expect(mapClientError(new Error("boom"))).toMatchObject({
      code: "unknown",
    });
  });
});

describe("fetchTierCatalog / fetchUsage (mocked gateway)", () => {
  it("combines allowed models with locked tiers from /plans", async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/auth/login") || url.endsWith("/auth/refresh")) {
        return new Response(
          JSON.stringify({
            access_token: "acc-1",
            refresh_token: "ref-1",
            token_type: "bearer",
            expires_in: 900,
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/v1/models")) {
        return new Response(
          JSON.stringify({
            object: "list",
            data: [
              {
                id: "fast",
                details: {
                  display_name: "Fast",
                  upstream_provider: "evren",
                  upstream_model: "deepseek-v4-flash",
                  max_output_tokens: 8192,
                  context_window: 128000,
                },
              },
            ],
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/plans")) {
        return new Response(
          JSON.stringify([
            { name: "Free", allowed_tier_aliases: ["fast"] },
            { name: "Pro", allowed_tier_aliases: ["fast", "balanced", "strong"] },
          ]),
          { status: 200 },
        );
      }
      if (url.endsWith("/usage")) {
        return new Response(
          JSON.stringify({
            plan_name: "Free",
            credit_limit: "100.000000",
            credits_used: "95.000000",
            credits_remaining: "5.000000",
            requests_per_minute: 10,
            period_end: "2026-10-01T00:00:00Z",
            per_tier: [],
          }),
          { status: 200 },
        );
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    const s = buildGatewaySession(settings("http://localhost:8000"), tmp(), fakeSafe(), fetchMock);
    // login so the client has a token
    await s.auth.login("u@example.com", "pw");

    const catalog = await fetchTierCatalog(s);
    expect(catalog.allowed).toHaveLength(1);
    expect(catalog.allowed[0]).toMatchObject({
      id: "fast",
      displayName: "Fast",
      upstreamProvider: "evren",
      upstreamModel: "deepseek-v4-flash",
      contextWindow: 128000,
    });
    // tiers on other plans but not ours are locked with an explanation
    const lockedIds = catalog.locked.map((t) => t.id).sort();
    expect(lockedIds).toEqual(["balanced", "strong"]);
    expect(catalog.locked[0]?.reason).toContain("Not available on your plan");

    const usage = await fetchUsage(s);
    expect(usage).toMatchObject({
      planName: "Free",
      creditLimit: 100,
      creditsUsed: 95,
      creditsRemaining: 5,
      requestsPerMinute: 10,
    });
  });
});
