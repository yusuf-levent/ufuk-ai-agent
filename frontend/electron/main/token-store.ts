/**
 * TokenStore implementation backed by Electron safeStorage (DPAPI on
 * Windows). Tokens (access + refresh) are encrypted before touching disk and
 * never cross the IPC boundary — only the main process sees them.
 *
 * safeStorage failure handling: when encryption is unavailable (rare; e.g.
 * DPAPI service issues), we fall back to a plain JSON file with owner-only
 * permissions and surface a warning through the session info, so the UI can
 * tell the user (Milestone 9 tests this).
 *
 * The CLI's file-based store (`FileTokenStore` in @evren/local-runner) keeps
 * working for terminal use. We deliberately do NOT share or import the CLI's
 * tokens: refresh-token rotation with reuse detection revokes every session
 * when two stores use the same refresh token, so each client keeps its own.
 */
import {
  existsSync,
  mkdirSync,
  readFileSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import * as path from "node:path";
import { z } from "zod";
import type { StoredTokens, TokenStore } from "@evren/agent-core";

/** The slice of Electron's safeStorage this store needs (injectable for tests). */
export interface SafeStorageLike {
  isEncryptionAvailable(): boolean;
  encryptString(plainText: string): Buffer;
  decryptString(encrypted: Buffer): string;
}

const StoredTokensFileSchema = z.object({
  accessToken: z.string().min(1),
  refreshToken: z.string().min(1),
  expiresAt: z.number(),
});

export class SafeStorageTokenStore implements TokenStore {
  /** Set when decryption fails (file corrupted / different OS user). */
  public corrupted = false;

  constructor(
    private readonly filePath: string,
    private readonly safe: SafeStorageLike,
  ) {}

  async load(): Promise<StoredTokens | null> {
    if (!existsSync(this.filePath)) return null;
    try {
      const b64 = readFileSync(this.filePath, "utf8").trim();
      const plain = this.safe.decryptString(Buffer.from(b64, "base64"));
      const parsed = StoredTokensFileSchema.safeParse(JSON.parse(plain));
      if (!parsed.success) return null;
      return parsed.data;
    } catch {
      // unreadable/corrupt/tampered: treat as no session, force re-login
      this.corrupted = true;
      return null;
    }
  }

  async save(tokens: StoredTokens): Promise<void> {
    const plain = JSON.stringify(tokens);
    const encrypted = this.safe.encryptString(plain);
    mkdirSync(path.dirname(this.filePath), { recursive: true });
    writeFileSync(this.filePath, encrypted.toString("base64"), "utf8");
  }

  async clear(): Promise<void> {
    if (existsSync(this.filePath)) {
      try {
        unlinkSync(this.filePath);
      } catch {
        // best effort
      }
    }
  }
}

/**
 * Fallback when safeStorage is unavailable: plain JSON, owner-only file
 * permissions (0600 is a no-op on Windows; the user-profile ACL applies).
 */
export class PlainTokenStore implements TokenStore {
  constructor(private readonly filePath: string) {}

  async load(): Promise<StoredTokens | null> {
    if (!existsSync(this.filePath)) return null;
    try {
      const parsed = StoredTokensFileSchema.safeParse(
        JSON.parse(readFileSync(this.filePath, "utf8")),
      );
      return parsed.success ? parsed.data : null;
    } catch {
      return null;
    }
  }

  async save(tokens: StoredTokens): Promise<void> {
    mkdirSync(path.dirname(this.filePath), { recursive: true });
    writeFileSync(this.filePath, JSON.stringify(tokens), {
      encoding: "utf8",
      mode: 0o600,
    });
  }

  async clear(): Promise<void> {
    if (existsSync(this.filePath)) {
      try {
        unlinkSync(this.filePath);
      } catch {
        // best effort
      }
    }
  }
}

export interface CreatedTokenStore {
  store: TokenStore;
  /** true when we could NOT use OS-level encryption. */
  usingPlainFallback: boolean;
}

/** Build the token store for a gateway base URL (path is namespaced by hash). */
export function createTokenStore(
  filePath: string,
  safe: SafeStorageLike,
): CreatedTokenStore {
  if (safe.isEncryptionAvailable()) {
    return {
      store: new SafeStorageTokenStore(filePath, safe),
      usingPlainFallback: false,
    };
  }
  return { store: new PlainTokenStore(filePath), usingPlainFallback: true };
}
