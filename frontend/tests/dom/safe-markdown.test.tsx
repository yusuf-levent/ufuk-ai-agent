/**
 * SafeMarkdown: model output is UNTRUSTED. Scripts, event handlers,
 * javascript:/data: URLs and raw SVG must never reach the DOM as live
 * elements; links become buttons that go through the confirmed
 * openExternal IPC (never in-app navigation).
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SafeMarkdown } from "../../src/components/SafeMarkdown";

(globalThis as Record<string, unknown>)["IS_REACT_ACT_ENVIRONMENT"] = true;

let container: HTMLDivElement;
let root: Root | null = null;
let openExternal: ReturnType<typeof vi.fn>;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  openExternal = vi.fn(async () => true);
  (window as unknown as Record<string, unknown>)["ufuk"] = {
    invoke: vi.fn(async (_channel: string, payload?: unknown) => {
      if (_channel === "shell:open-external") {
        return openExternal(payload as { url: string });
      }
      return { ok: true, value: null };
    }),
    subscribe: vi.fn(),
  };
});

afterEach(() => {
  if (root) {
    act(() => root?.unmount());
    root = null;
  }
  container.remove();
});

const render = async (text: string): Promise<void> => {
  root = createRoot(container);
  await act(async () => {
    root?.render(<SafeMarkdown text={text} />);
  });
};

describe("SafeMarkdown (untrusted model output)", () => {
  it("renders plain markdown", async () => {
    await render("# Hello\n\nsome **bold** text");
    expect(container.querySelector("h1")?.textContent).toBe("Hello");
    expect(container.textContent).toContain("bold");
  });

  it("never creates script elements from raw HTML", async () => {
    await render('before <script>alert("pwn")</script> after');
    expect(container.querySelector("script")).toBeNull();
  });

  it("never creates img elements with event handlers", async () => {
    await render('<img src="x" onerror="alert(1)">');
    const imgs = container.querySelectorAll("img");
    for (const img of imgs) {
      expect(img.getAttribute("onerror")).toBeNull();
    }
  });

  it("never creates svg/onload elements (SVG script carrier)", async () => {
    await render('<svg onload="alert(1)"><circle r="1"/></svg>');
    expect(container.querySelector("svg")).toBeNull();
  });

  it("strips iframe/object/embed from raw HTML", async () => {
    await render(
      '<iframe src="https://evil.example"></iframe><object></object>',
    );
    expect(container.querySelector("iframe")).toBeNull();
    expect(container.querySelector("object")).toBeNull();
  });

  it("markdown links render as buttons (no anchor navigation)", async () => {
    await render("[click me](https://example.com/page)");
    expect(container.querySelector("a")).toBeNull();
    const button = container.querySelector("button");
    expect(button?.textContent).toBe("click me");
  });

  it("clicking a link goes through the confirmed openExternal IPC, not navigation", async () => {
    const locationBefore = window.location.href;
    await render("[docs](https://example.com/docs)");
    const button = container.querySelector("button");
    expect(button).not.toBeNull();
    await act(async () => {
      button?.click();
    });
    expect(openExternal).toHaveBeenCalledWith({
      url: "https://example.com/docs",
    });
    expect(window.location.href).toBe(locationBefore);
  });

  it("javascript: and data: URLs are stripped by the sanitizer before they can be clicked", async () => {
    await render(
      "[x](javascript:alert(1)) and [y](data:text/html,<script>1</script>)",
    );
    const buttons = container.querySelectorAll("button");
    expect(buttons.length).toBe(2);
    for (const button of buttons) {
      await act(async () => {
        button?.click();
      });
    }
    // nothing reaches openExternal: the href was removed by rehype-sanitize
    expect(openExternal).not.toHaveBeenCalled();
  });

  it("inlines code fences as inert text", async () => {
    await render("```js\nwindow.location='https://evil.example'\n```");
    const pre = container.querySelector("pre");
    expect(pre?.textContent).toContain("window.location");
    expect(container.querySelector("script")).toBeNull();
  });
});
