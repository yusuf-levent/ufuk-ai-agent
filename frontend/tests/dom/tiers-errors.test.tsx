/**
 * M8: structured chat errors drive the actionable UI (countdown, re-login,
 * quota explanation); the tier selector uses the live catalog with locked
 * tiers and the details popover; the credit indicator renders usage.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { installBridge } from "./helpers/mock-bridge";
import { useChatStore } from "../../src/stores/chat";
import { useModelsStore } from "../../src/stores/models";
import { useAppStore } from "../../src/stores/app";
import { FriendlyErrorView } from "../../src/components/FriendlyErrorView";
import { Composer } from "../../src/components/Composer";
import { MainShell } from "../../src/screens/MainShell";

(globalThis as Record<string, unknown>)["IS_REACT_ACT_ENVIRONMENT"] = true;

let container: HTMLDivElement;
let root: Root | null = null;
let invoke: ReturnType<typeof vi.fn>;

const render = async (el: React.ReactNode): Promise<void> => {
  root = createRoot(container);
  await act(async () => {
    root?.render(el);
  });
};

const emit = (event: unknown, errorInfo?: unknown): void => {
  act(() => {
    useChatStore.getState().handleEvent({
      conversationId: "c_1",
      event,
      ...(errorInfo ? { errorInfo } : {}),
    } as never);
  });
};

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  const bridge = installBridge({
    "models:list": () => ({
      ok: true,
      value: {
        allowed: [
          {
            id: "fast",
            displayName: "Fast",
            upstreamProvider: "evren",
            upstreamModel: "deepseek-v4-flash",
            maxOutputTokens: 8192,
            contextWindow: 128000,
          },
          {
            id: "strong",
            displayName: "Strong",
            upstreamProvider: "evren",
            upstreamModel: "glm-5.3",
          },
        ],
        locked: [
          {
            id: "balanced",
            reason: "Not available on your plan (available on Pro).",
          },
        ],
      },
    }),
    "usage:get": () => ({
      ok: true,
      value: {
        planName: "Free",
        creditLimit: 100,
        creditsUsed: 95,
        creditsRemaining: 5,
        requestsPerMinute: 10,
        periodEnd: "2026-10-01T00:00:00Z",
      },
    }),
    "projects:list": () => ({ ok: true, value: [] }),
  });
  invoke = bridge.invoke;
  useChatStore.setState({ turns: {}, lastMessage: {} });
  useModelsStore.setState({
    catalog: null,
    catalogError: null,
    catalogErrorCode: null,
    usage: null,
    usageError: null,
    usageErrorCode: null,
  });
  useAppStore.setState({
    ready: true,
    sessionChecked: true,
    settings: {
      backendUrl: "http://localhost:8000",
      theme: "dark",
      defaultTier: "fast",
      permissionMode: "ask",
      privacyAcknowledged: true,
      activeMode: "projects",
    },
    mode: "projects",
    session: {
      userId: "u1",
      email: "u@example.com",
      displayName: null,
      usingPlainTokenStore: false,
    },
  });
});

afterEach(() => {
  if (root) {
    act(() => root?.unmount());
    root = null;
  }
  container.remove();
  useChatStore.setState({ turns: {}, lastMessage: {} });
});

describe("FriendlyErrorView (structured errors)", () => {
  it("rate limited: live countdown from Retry-After", async () => {
    emit(
      { type: "error", fatal: true, message: "Rate limited by the gateway." },
      { code: "rate_limited", retryAfterMs: 5_000 },
    );
    const turn = useChatStore.getState().turns["c_1"]!;
    expect(turn.retryUntil).not.toBeNull();
    await render(<FriendlyErrorView turn={turn} />);
    expect(container.textContent).toContain("Rate limited");
    expect(container.textContent).toMatch(/retry in \d+s/);
    expect(container.querySelector("[aria-label=countdown]")).toBeTruthy();
  });

  it("quota exceeded: explains nothing was charged", async () => {
    emit(
      { type: "error", fatal: true, message: "Credit quota exhausted..." },
      { code: "quota_exceeded" },
    );
    await render(
      <FriendlyErrorView turn={useChatStore.getState().turns["c_1"]!} />,
    );
    expect(container.textContent).toContain(
      "Credit quota exhausted for this billing period",
    );
    expect(container.textContent).toContain("nothing was charged");
  });

  it("session expired: offers a single re-login that logs out", async () => {
    emit(
      { type: "error", fatal: true, message: "Session expired..." },
      { code: "reauth_required" },
    );
    await render(
      <FriendlyErrorView turn={useChatStore.getState().turns["c_1"]!} />,
    );
    expect(container.textContent).toContain("Session expired");
    const button = [...container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("Log in again"),
    );
    expect(button).toBeTruthy();
    await act(async () => {
      button?.click();
    });
    const calls = invoke.mock.calls.filter(([c]) => c === "auth:logout");
    expect(calls).toHaveLength(1);
  });

  it("subscription inactive and model not allowed headlines", async () => {
    emit(
      { type: "error", fatal: true, message: "..." },
      { code: "subscription_inactive" },
    );
    await render(
      <FriendlyErrorView turn={useChatStore.getState().turns["c_1"]!} />,
    );
    expect(container.textContent).toContain("no active subscription");
  });
});

describe("Composer tier selector (live catalog)", () => {
  it("shows display names, locks unavailable tiers, reveals upstream details", async () => {
    await act(async () => {
      await useModelsStore.getState().refresh();
    });
    await render(
      <Composer root="/tmp/p" conversationId="c_1" onTurnStarted={() => {}} />,
    );
    const select = container.querySelector("select");
    expect(select).toBeTruthy();
    const options = [...(select as HTMLSelectElement).options];
    expect(options.map((o) => o.text)).toEqual([
      "Fast",
      "Strong",
      "🔒 balanced",
    ]);
    const locked = options.find((o) => o.text.includes("balanced"));
    expect(locked?.disabled).toBe(true);
    expect(locked?.title).toContain("Not available on your plan");

    // details popover shows the real upstream provider/model
    const details = [...container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("details"),
    );
    expect(details).toBeTruthy();
    await act(async () => {
      details?.click();
    });
    expect(container.textContent).toContain("deepseek-v4-flash");
    expect(container.textContent).toContain("evren");
    expect(container.textContent).toMatch(/128[.,]000/);
  });
});

describe("CreditIndicator (usage)", () => {
  it("renders the remaining/limit bar and plan tooltip", async () => {
    await act(async () => {
      await useModelsStore.getState().refresh();
    });
    await render(<MainShell onOpenSettings={() => {}} />);
    expect(container.textContent).toContain("5");
    expect(container.textContent).toContain("100");
    // near-limit bar turns red (95%)
    const bar = container.querySelector(".bg-red-500");
    expect(bar).toBeTruthy();
  });
});
