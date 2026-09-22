// @vitest-environment node
/**
 * safeStorage-backed token store: encrypted at rest, never logged, safe
 * fallback when DPAPI is unavailable. Mirrors the TokenStore contract the
 * CLI uses (agent-core), so gateway auth works unchanged.
 */
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import {
  createTokenStore,
  PlainTokenStore,
  SafeStorageTokenStore,
  type SafeStorageLike,
} from "../../electron/main/token-store";

const dirs: string[] = [];
const tmp = (): string => {
  const d = mkdtempSync(path.join(tmpdir(), "ufuk-tokens-"));
  dirs.push(d);
  return d;
};
afterAll(() => {
  for (const d of dirs) rmSync(d, { recursive: true, force: true });
});

/** Fake DPAPI: reversible "encryption" so tests assert at-rest secrecy. */
function fakeSafe(available = true): SafeStorageLike {
  return {
    isEncryptionAvailable: () => available,
    encryptString: (plain) => Buffer.from(`enc:${plain}`, "utf8"),
    decryptString: (buf) => {
      const s = buf.toString("utf8");
      if (!s.startsWith("enc:")) throw new Error("not encrypted by this store");
      return s.slice(4);
    },
  };
}

const tokens = {
  accessToken: "acc-SECRET-VALUE",
  refreshToken: "ref-SECRET-VALUE",
  expiresAt: Date.now() + 60_000,
};

describe("SafeStorageTokenStore", () => {
  it("round-trips tokens through the encrypted file", async () => {
    const dir = tmp();
    const file = path.join(dir, "tokens.bin");
    const store = new SafeStorageTokenStore(file, fakeSafe());
    await store.save(tokens);
    expect(await store.load()).toEqual(tokens);
  });

  it("never writes plaintext tokens to disk", async () => {
    const dir = tmp();
    const file = path.join(dir, "tokens.bin");
    const store = new SafeStorageTokenStore(file, fakeSafe());
    await store.save(tokens);
    const raw = readFileSync(file, "utf8");
    expect(raw).not.toContain(tokens.accessToken);
    expect(raw).not.toContain(tokens.refreshToken);
    expect(raw).not.toContain("accessToken");
  });

  it("treats a corrupted/undecryptable file as logged out (forces re-login)", async () => {
    const dir = tmp();
    const file = path.join(dir, "tokens.bin");
    writeFileSync(file, "garbage-not-base64-encrypted", "utf8");
    const store = new SafeStorageTokenStore(file, fakeSafe());
    expect(await store.load()).toBeNull();
    expect(store.corrupted).toBe(true);
  });

  it("clear() removes the file", async () => {
    const dir = tmp();
    const file = path.join(dir, "tokens.bin");
    const store = new SafeStorageTokenStore(file, fakeSafe());
    await store.save(tokens);
    await store.clear();
    expect(await store.load()).toBeNull();
  });
});

describe("PlainTokenStore (safeStorage unavailable fallback)", () => {
  it("round-trips and clears", async () => {
    const dir = tmp();
    const file = path.join(dir, "tokens.json");
    const store = new PlainTokenStore(file);
    await store.save(tokens);
    expect(await store.load()).toEqual(tokens);
    await store.clear();
    expect(await store.load()).toBeNull();
  });

  it("returns null for corrupt or schema-invalid files", async () => {
    const dir = tmp();
    const a = path.join(dir, "a.json");
    writeFileSync(a, "{oops", "utf8");
    expect(await new PlainTokenStore(a).load()).toBeNull();
    const b = path.join(dir, "b.json");
    writeFileSync(b, JSON.stringify({ accessToken: "" }), "utf8");
    expect(await new PlainTokenStore(b).load()).toBeNull();
  });
});

describe("createTokenStore", () => {
  it("prefers safeStorage when encryption is available", () => {
    const made = createTokenStore(path.join(tmp(), "t.bin"), fakeSafe(true));
    expect(made.usingPlainFallback).toBe(false);
    expect(made.store).toBeInstanceOf(SafeStorageTokenStore);
  });

  it("falls back to the plain store (flagged) when DPAPI is unavailable", () => {
    const made = createTokenStore(path.join(tmp(), "t.json"), fakeSafe(false));
    expect(made.usingPlainFallback).toBe(true);
    expect(made.store).toBeInstanceOf(PlainTokenStore);
  });
});
