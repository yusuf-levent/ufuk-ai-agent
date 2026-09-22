/** Shared fake safeStorage (reversible, so tests can assert at-rest secrecy). */
import type { SafeStorageLike } from "../../../electron/main/token-store";

export function fakeSafe(available = true): SafeStorageLike {
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
