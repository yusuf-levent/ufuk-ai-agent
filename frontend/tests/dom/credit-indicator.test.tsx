/**
 * Issue 3 — CreditIndicator states: remaining-first wording, colors that
 * only warn near exhaustion, the click breakdown (plan/used/remaining/
 * reset) and the distinct zero-credit state.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, describe, expect, it } from "vitest";
import { installBridge } from "./helpers/mock-bridge";
import { CreditIndicator } from "../../src/components/CreditIndicator";
import { useModelsStore } from "../../src/stores/models";
import type { UsageInfo } from "@shared/ipc";

(globalThis as Record<string, unknown>)["IS_REACT_ACT_ENVIRONMENT"] = true;

let container: HTMLDivElement;
let root: Root | null = null;

const render = async (): Promise<void> => {
  root = createRoot(container);
  await act(async () => {
    root?.render(<CreditIndicator />);
  });
};

const setUsage = (usage: UsageInfo | null): void => {
  useModelsStore.setState({
    usage,
    usageError: null,
    usageErrorCode: null,
  });
};

const usage = (over: Partial<UsageInfo>): UsageInfo => ({
  planName: "Pro",
  creditLimit: 100,
  creditsUsed: 18,
  creditsRemaining: 82,
  requestsPerMinute: 10,
  periodEnd: "2026-10-01T00:00:00Z",
  ...over,
});

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  installBridge();
  useModelsStore.setState({
    catalog: null,
    catalogError: null,
    catalogErrorCode: null,
    usage: null,
    usageError: null,
    usageErrorCode: null,
  });
});

afterEach(() => {
  if (root) {
    act(() => root?.unmount());
    root = null;
  }
  container.remove();
});

describe("CreditIndicator display states", () => {
  it("healthy usage reads as REMAINING credits, neutral color (82 left of 100)", async () => {
    setUsage(usage({}));
    await render();
    expect(container.textContent).toContain("credits left of");
    expect(container.textContent).toContain("82");
    expect(container.textContent).toContain("100");
    // no warning color at 82% remaining
    expect(container.querySelector(".bg-red-500")).toBeFalsy();
    expect(container.querySelector(".bg-amber-500")).toBeFalsy();
    expect(container.querySelector(".bg-sky-500")).toBeTruthy();
  });

  it("low credits (<25% left) turn amber but stay informative", async () => {
    setUsage(usage({ creditsUsed: 80, creditsRemaining: 20 }));
    await render();
    expect(container.textContent).toContain("20");
    expect(container.querySelector(".bg-amber-500")).toBeTruthy();
    expect(container.querySelector(".bg-red-500")).toBeFalsy();
  });

  it("critical credits (<10% left) turn red", async () => {
    setUsage(usage({ creditsUsed: 95, creditsRemaining: 5 }));
    await render();
    expect(container.textContent).toContain("5");
    expect(container.querySelector(".bg-red-500")).toBeTruthy();
    // still the bar+label presentation, not the exhausted state
    expect(container.textContent).not.toContain("credits used up");
  });

  it("ZERO credits: distinct exhausted state with reset date, no misleading bar", async () => {
    setUsage(usage({ creditsUsed: 100, creditsRemaining: 0 }));
    await render();
    expect(container.textContent).toContain("credits used up");
    expect(container.textContent).toMatch(/resets/);
    // no progress bar at all in the exhausted state
    expect(container.querySelector(".bg-red-500")).toBeFalsy();
    expect(container.querySelector(".h-1\\.5")).toBeFalsy();
  });

  it("clicking reveals the breakdown: plan, used, remaining, reset date", async () => {
    setUsage(usage({}));
    await render();
    await act(async () => {
      (
        [...container.querySelectorAll("button")].find(
          (b) => b.getAttribute("aria-label") === "Credits",
        ) as HTMLButtonElement | undefined
      )?.click();
    });
    const breakdown = container.querySelector(
      '[aria-label="Credit usage details"]',
    );
    expect(breakdown).toBeTruthy();
    expect(breakdown?.textContent).toContain("Pro");
    expect(breakdown?.textContent).toContain("18");
    expect(breakdown?.textContent).toContain("82");
    // reset date rendered in the viewer's locale
    expect(breakdown?.textContent).toContain(
      new Date("2026-10-01T00:00:00Z").toLocaleDateString(),
    );
    expect(breakdown?.textContent).toContain("10 req/min");
  });

  it("the exhausted state also opens the breakdown on click", async () => {
    setUsage(usage({ creditsUsed: 100, creditsRemaining: 0 }));
    await render();
    await act(async () => {
      (
        [...container.querySelectorAll("button")].find(
          (b) => b.getAttribute("aria-label") === "Credits exhausted",
        ) as HTMLButtonElement | undefined
      )?.click();
    });
    const breakdown = container.querySelector(
      '[aria-label="Credit usage details"]',
    );
    expect(breakdown).toBeTruthy();
    expect(breakdown?.textContent).toContain("0");
  });

  it("no subscription shows the existing badge instead of numbers", async () => {
    useModelsStore.setState({
      usage: null,
      usageError: "Your account has no active subscription.",
      usageErrorCode: "subscription_inactive",
    });
    await render();
    expect(container.textContent).toContain("no active subscription");
    expect(container.textContent).not.toContain("credits left of");
  });
});
