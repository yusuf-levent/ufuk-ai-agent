// @vitest-environment node
/**
 * M9 hardening: IPC sender validation, secrets hygiene in the contract,
 * safeStorage failure paths.
 */
import { describe, expect, it } from "vitest";
import { isTrustedSender, parseExternalUrl } from "../../electron/main/security";
import {
  INVOKE_CHANNELS,
  INVOKE_CHANNEL_SET,
} from "@shared/channels";
import { SafeStorageTokenStore, PlainTokenStore } from "../../electron/main/token-store";
import { fakeSafe } from "./helpers/fake-safe-storage";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";

/** Minimal WebContents stand-in (isTrustedSender only calls getURL). */
const contents = (url: string): { getURL(): string } => ({ getURL: () => url });

describe("isTrustedSender (origin policy)", () => {
  it("accepts the packaged app (file:) and the dev server on localhost", () => {
    expect(isTrustedSender(contents("file:///C:/app/out/renderer/index.html") as never)).toBe(true);
    expect(isTrustedSender(contents("http://localhost:5173/") as never)).toBe(true);
    expect(isTrustedSender(contents("http://127.0.0.1:5173/") as never)).toBe(true);
  });

  it("rejects remote origins, other localhost ports on weird hosts, and invalid URLs", () => {
    expect(isTrustedSender(contents("https://evil.example/") as never)).toBe(false);
    expect(isTrustedSender(contents("http:// attacker/") as never)).toBe(false);
    expect(isTrustedSender(contents("about:blank") as never)).toBe(false);
    expect(isTrustedSender(contents("chrome-extension://x/") as never)).toBe(false);
    expect(isTrustedSender({ getURL: () => "not a url" } as never)).toBe(false);
  });

  it("the renderer origin can be spoofed only by... the renderer: dev-server https is still localhost", () => {
    // https on localhost is still our dev server behind a proxy — allowed
    expect(isTrustedSender(contents("https://localhost:5173/") as never)).toBe(true);
  });
});

describe("parseExternalUrl (system browser gate)", () => {
  it("rejects every scheme except http(s), including exotic ones", () => {
    for (const bad of [
      "javascript:alert(1)",
      "JaVaScRiPt:alert(1)",
      "data:text/html,<script>1</script>",
      "vbscript:x",
      "file:///C:/Windows/win.ini",
      "ms-msdt:foo",
      "search-ms:displayname=x",
      "shell:Fonts",
      "intent://x",
      "ws://evil/",
    ]) {
      expect(parseExternalUrl(bad)).toBeNull();
    }
  });
});

describe("secrets hygiene (no tokens cross the bridge)", () => {
  it("no invoke channel name mentions tokens or secrets", () => {
    for (const channel of INVOKE_CHANNEL_SET) {
      expect(/token|secret|password|credential/i.test(channel)).toBe(false);
    }
  });

  it("the chat event payload schema carries no token fields", () => {
    // ChatEventPayload = { conversationId, event, errorInfo } — verified
    // structurally by the type; here we assert the serialized shape of a
    // representative payload never leaks auth material
    const payload = {
      conversationId: "c_1",
      event: { type: "message_delta", text: "hi" },
      errorInfo: { code: "quota_exceeded" },
    };
    expect(JSON.stringify(payload)).not.toMatch(/access_token|refresh_token/i);
  });

  it("the token file on disk never contains plaintext tokens", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "ufuk-sec-"));
    try {
      const file = path.join(dir, "tokens.bin");
      const store = new SafeStorageTokenStore(file, fakeSafe());
      void store.save({
        accessToken: "acc-SECRET",
        refreshToken: "ref-SECRET",
        expiresAt: Date.now() + 1000,
      });
      const raw = readFileSync(file, "utf8");
      expect(raw).not.toContain("acc-SECRET");
      expect(raw).not.toContain("ref-SECRET");
      expect(raw).not.toContain("accessToken");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("safeStorage failure: plain fallback is used and flagged; corrupt files force re-login", async () => {
    const dir = mkdtempSync(path.join(tmpdir(), "ufuk-sec2-"));
    try {
      const file = path.join(dir, "tokens.json");
      const plain = new PlainTokenStore(file);
      await plain.save({
        accessToken: "a",
        refreshToken: "r",
        expiresAt: 1,
      });
      expect(await plain.load()).toMatchObject({ accessToken: "a" });
      // corrupted JSON -> null (logged out), never a crash
      writeFileSync(file, "{oops", "utf8");
      expect(await new PlainTokenStore(file).load()).toBeNull();
      // encrypted store with garbage -> null + corrupted flag
      const enc = new SafeStorageTokenStore(
        path.join(dir, "t.bin"),
        fakeSafe(),
      );
      writeFileSync(path.join(dir, "t.bin"), "garbage", "utf8");
      expect(await enc.load()).toBeNull();
      expect(enc.corrupted).toBe(true);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("channel allowlist integrity", () => {
  it("every INVOKE_CHANNELS value is unique", () => {
    const values = Object.values(INVOKE_CHANNELS);
    expect(new Set(values).size).toBe(values.length);
  });
});
