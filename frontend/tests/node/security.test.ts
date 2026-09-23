// @vitest-environment node
/**
 * Main-process security helpers: external-URL protocol checks and IPC
 * sender validation (origin policy).
 */
import { describe, expect, it } from "vitest";
import { parseExternalUrl } from "../../electron/main/security";

describe("parseExternalUrl (system-browser gate)", () => {
  it("accepts http and https URLs", () => {
    expect(parseExternalUrl("https://example.com/docs")?.href).toBe(
      "https://example.com/docs",
    );
    expect(parseExternalUrl("http://localhost:8000")?.protocol).toBe("http:");
  });

  it("rejects javascript:, data:, file:, vbscript: and other schemes", () => {
    for (const bad of [
      "javascript:alert(1)",
      "data:text/html,<script>1</script>",
      "file:///C:/Windows/System32/cmd.exe",
      "vbscript:msgbox(1)",
      "ms-msdt:x", // legacy Windows protocol handlers
      "search-ms:displayname=exploit",
    ]) {
      expect(parseExternalUrl(bad)).toBeNull();
    }
  });

  it("rejects malformed URLs", () => {
    expect(parseExternalUrl("")).toBeNull();
    expect(parseExternalUrl("not a url")).toBeNull();
    expect(parseExternalUrl("http://")).toBeNull();
  });

  it("cannot be tricked by embedded scheme separators", () => {
    // URL parsing is scheme-first: these are relative http paths, not file: URLs
    expect(
      parseExternalUrl("https://example.com/file:///etc/passwd")?.protocol,
    ).toBe("https:");
  });
});
