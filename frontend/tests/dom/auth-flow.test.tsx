/**
 * M4 flow: privacy gate (acknowledge once), login/register screens (loading
 * states, friendly coded errors), settings dialog (backend URL validation,
 * theme/tier/permission mode patches).
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { installBridge, defaultSettings } from "./helpers/mock-bridge";
import { PrivacyGate } from "../../src/screens/PrivacyGate";
import { LoginScreen } from "../../src/screens/LoginScreen";
import { SettingsDialog } from "../../src/components/SettingsDialog";
import { useAppStore } from "../../src/stores/app";

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

const type = async (el: Element | null, value: string): Promise<void> => {
  if (!el) return;
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    "value",
  )?.set;
  await act(async () => {
    setter?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
};

const setStore = (patch: Partial<typeof defaultSettings>): void => {
  useAppStore.setState({
    ready: true,
    sessionChecked: true,
    settings: { ...defaultSettings, ...patch },
    ...("session" in patch ? {} : {}),
  });
};

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  const bridge = installBridge();
  invoke = bridge.invoke;
});

afterEach(() => {
  if (root) {
    act(() => root?.unmount());
    root = null;
  }
  container.remove();
  useAppStore.setState({
    ready: false,
    settings: null,
    session: null,
    sessionChecked: false,
    sessionExpired: false,
    sessionUnreachable: false,
    mode: "chat",
  });
});

describe("PrivacyGate (first-run notice)", () => {
  it("fetches /privacy/info through the bridge and shows the upstream host", async () => {
    await render(<PrivacyGate onOpenSettings={() => {}} />);
    expect(invoke).toHaveBeenCalledWith("privacy:info");
    expect(container.textContent).toContain("gw.example.com");
    expect(container.textContent).toContain("third-party model providers");
  });

  it("continue stays disabled until the checkbox is ticked; acknowledging patches settings once", async () => {
    await render(<PrivacyGate onOpenSettings={() => {}} />);
    const continueBtn = [...container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("Continue"),
    );
    expect(continueBtn).toBeTruthy();
    expect((continueBtn as HTMLButtonElement).disabled).toBe(true);

    const checkbox = container.querySelector(
      "input[type=checkbox]",
    ) as HTMLInputElement;
    await act(async () => {
      checkbox.click();
    });
    expect((continueBtn as HTMLButtonElement).disabled).toBe(false);

    await act(async () => {
      (continueBtn as HTMLButtonElement).click();
    });
    const setCalls = invoke.mock.calls.filter(([c]) => c === "settings:set");
    expect(setCalls).toHaveLength(1);
    expect(setCalls[0]?.[1]).toEqual({ privacyAcknowledged: true });
  });

  it("shows a retryable error when the backend is unreachable", async () => {
    const { invoke: failInvoke } = installBridge({
      "privacy:info": () => ({
        ok: false,
        error: {
          message: "Cannot reach the backend. Is it running?",
          code: "gateway_unreachable",
        },
      }),
    });
    invoke = failInvoke;
    await render(<PrivacyGate onOpenSettings={() => {}} />);
    expect(container.textContent).toContain("Cannot reach the backend");
    const retry = [...container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("Retry"),
    );
    expect(retry).toBeTruthy();
  });
});

describe("LoginScreen", () => {
  it("shows a clear 'session expired' banner when the stored session could not be restored", async () => {
    useAppStore.setState({ sessionExpired: true, sessionUnreachable: false });
    await render(<LoginScreen onOpenSettings={() => {}} />);
    const banner = container.querySelector('[role="status"]');
    expect(banner?.textContent).toContain("session expired");
    expect(banner?.textContent).toContain("log in again");
    useAppStore.setState({ sessionExpired: false });
  });

  it("shows a retryable banner when the backend was unreachable at restore time", async () => {
    useAppStore.setState({ sessionExpired: false, sessionUnreachable: true });
    await render(<LoginScreen onOpenSettings={() => {}} />);
    const banner = container.querySelector('[role="status"]');
    expect(banner?.textContent).toContain("Couldn't reach the backend");
    const retry = [...container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("Retry"),
    );
    expect(retry).toBeTruthy();
    await act(async () => {
      retry?.click();
    });
    // retry re-checks the session through the bridge
    expect(
      invoke.mock.calls.filter(([c]) => c === "auth:session").length,
    ).toBeGreaterThanOrEqual(1);
    useAppStore.setState({ sessionUnreachable: false });
  });

  it("shows a friendly error for invalid credentials", async () => {
    const { invoke: failInvoke } = installBridge({
      "auth:login": () => ({
        ok: false,
        error: {
          message: "Invalid email or password.",
          code: "invalid_credentials",
        },
      }),
    });
    invoke = failInvoke;
    await render(<LoginScreen onOpenSettings={() => {}} />);
    const inputs = container.querySelectorAll("input");
    await type(inputs.item(0), "u@example.com");
    await type(inputs.item(1), "wrong");
    await act(async () => {
      (
        container.querySelector("button[type=submit]") as HTMLButtonElement
      ).click();
    });
    expect(container.textContent).toContain("Invalid email or password");
    expect(container.textContent).not.toContain("HTTP");
  });

  it("validates register passwords client-side (min 8)", async () => {
    await render(<LoginScreen onOpenSettings={() => {}} />);
    // switch to register mode
    await act(async () => {
      [...container.querySelectorAll("button")]
        .find((b) => b.textContent?.includes("Register"))
        ?.click();
    });
    const inputs = container.querySelectorAll("input");
    await type(inputs.item(0), "Ada");
    await type(inputs.item(1), "a@b.co");
    await type(inputs.item(2), "short");
    await act(async () => {
      (
        container.querySelector("button[type=submit]") as HTMLButtonElement
      ).click();
    });
    expect(container.textContent).toContain("at least 8 characters");
    expect(
      invoke.mock.calls.filter(([c]) => c === "auth:register"),
    ).toHaveLength(0);
  });

  it("surfaces registration failures from the backend", async () => {
    const { invoke: failInvoke } = installBridge({
      "auth:register": () => ({
        ok: false,
        error: {
          message: "email already registered",
          code: "registration_failed",
        },
      }),
    });
    invoke = failInvoke;
    await render(<LoginScreen onOpenSettings={() => {}} />);
    await act(async () => {
      [...container.querySelectorAll("button")]
        .find((b) => b.textContent?.includes("Register"))
        ?.click();
    });
    const inputs = container.querySelectorAll("input");
    await type(inputs.item(0), "Ada");
    await type(inputs.item(1), "a@b.co");
    await type(inputs.item(2), "longenough");
    await act(async () => {
      (
        container.querySelector("button[type=submit]") as HTMLButtonElement
      ).click();
    });
    expect(container.textContent).toContain("Registration failed");
    expect(container.textContent).toContain("email already registered");
  });
});

describe("app store session restore (snapshot with reason)", () => {
  it("restores the profile and clears the flags when info is present", async () => {
    installBridge({
      "auth:session": () => ({
        ok: true,
        value: {
          info: {
            userId: "u1",
            email: "u@example.com",
            displayName: null,
            usingPlainTokenStore: false,
          },
        },
      }),
    });
    await act(async () => {
      await useAppStore.getState().refreshSession();
    });
    expect(useAppStore.getState().session).toMatchObject({
      userId: "u1",
      email: "u@example.com",
    });
    expect(useAppStore.getState().sessionExpired).toBe(false);
    expect(useAppStore.getState().sessionUnreachable).toBe(false);
  });

  it("marks sessionExpired when the restore reason is 'expired'", async () => {
    installBridge({
      "auth:session": () => ({
        ok: true,
        value: { info: null, reason: "expired" },
      }),
    });
    await act(async () => {
      await useAppStore.getState().refreshSession();
    });
    expect(useAppStore.getState().session).toBeNull();
    expect(useAppStore.getState().sessionExpired).toBe(true);
  });

  it("marks sessionUnreachable (retryable) when the reason is 'unreachable'", async () => {
    installBridge({
      "auth:session": () => ({
        ok: true,
        value: { info: null, reason: "unreachable" },
      }),
    });
    await act(async () => {
      await useAppStore.getState().refreshSession();
    });
    expect(useAppStore.getState().sessionUnreachable).toBe(true);
    expect(useAppStore.getState().sessionExpired).toBe(false);
  });
});

describe("SettingsDialog", () => {
  it("rejects non-http(s) backend URLs without calling the bridge", async () => {
    setStore({});
    await render(<SettingsDialog onClose={() => {}} />);
    const input = container.querySelector(
      "input[type=text]",
    ) as HTMLInputElement;
    await type(input, "ftp://nope");
    await act(async () => {
      [...container.querySelectorAll("button")]
        .find((b) => b.textContent === "Save")
        ?.click();
    });
    expect(container.textContent).toContain("http:// or https://");
    expect(
      invoke.mock.calls.filter(([c]) => c === "settings:set"),
    ).toHaveLength(0);
  });

  it("theme switch patches settings through the bridge", async () => {
    setStore({});
    await render(<SettingsDialog onClose={() => {}} />);
    await act(async () => {
      [...container.querySelectorAll("button")]
        .find((b) => b.textContent === "light")
        ?.click();
    });
    const setCalls = invoke.mock.calls.filter(([c]) => c === "settings:set");
    expect(setCalls.at(-1)?.[1]).toMatchObject({ theme: "light" });
  });

  it("permission mode offers exactly ask and auto-edits (no allow-everything)", async () => {
    setStore({});
    await render(<SettingsDialog onClose={() => {}} />);
    const radios = [
      ...container.querySelectorAll('input[name="perm"]'),
    ] as HTMLInputElement[];
    const labels = radios.map((r) => r.closest("label")?.textContent ?? "");
    expect(labels.some((t) => t.includes("Ask every time"))).toBe(true);
    expect(
      labels.some((t) => t.includes("Auto-accept edits inside the workspace")),
    ).toBe(true);
    expect(labels.some((t) => /allow\s+everything/i.test(t))).toBe(false);
    const autoEdits = radios.find((r) =>
      r.closest("label")?.textContent.includes("Auto-accept"),
    );
    await act(async () => {
      autoEdits?.click();
    });
    const setCalls = invoke.mock.calls.filter(([c]) => c === "settings:set");
    expect(setCalls.at(-1)?.[1]).toMatchObject({
      permissionMode: "auto-edits",
    });
  });

  it("Escape closes the dialog", async () => {
    setStore({});
    let closed = false;
    await render(<SettingsDialog onClose={() => (closed = true)} />);
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(closed).toBe(true);
  });
});
