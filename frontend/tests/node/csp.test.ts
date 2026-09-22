// @vitest-environment node
/** CSP builder: production must be strict; dev may only widen styles/HMR. */
import { describe, expect, it } from "vitest";
import { buildCsp } from "../../shared/csp";

describe("buildCsp", () => {
  it("production: script-src is 'self' only — no unsafe-inline, no unsafe-eval", () => {
    const csp = buildCsp(false);
    const script = /script-src ([^;]+);/.exec(csp)?.[1] ?? "";
    expect(script).toContain("'self'");
    expect(csp).not.toContain("unsafe-inline");
    expect(csp).not.toContain("unsafe-eval");
  });

  it("production: no connect-src beyond 'self' (renderer never talks to the backend)", () => {
    const csp = buildCsp(false);
    const connect = /connect-src ([^;]+);/.exec(csp)?.[1] ?? "";
    expect(connect).toBe("'self'");
    expect(csp).not.toContain("localhost:8000");
    expect(csp).not.toContain("http:");
  });

  it("production: frames, objects, base-uri and forms are all locked down", () => {
    const csp = buildCsp(false);
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("frame-src 'none'")
    expect(csp).toContain("child-src 'none'");
    expect(csp).toContain("base-uri 'none'");
    expect(csp).toContain("form-action 'none'");
  });

  it("dev: only style-src gains unsafe-inline (Vite HMR) and the HMR websocket is allowed", () => {
    const csp = buildCsp(true);
    expect(csp).toContain("style-src 'self' 'unsafe-inline'");
    expect(csp).toContain("ws://localhost:5173");
    // scripts stay strict even in dev
    expect(csp).toMatch(/script-src 'self';/);
    expect(csp).not.toContain("unsafe-eval");
  });
});
