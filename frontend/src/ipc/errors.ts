/**
 * Renderer-side error presentation: maps IpcError codes (and a few known
 * message prefixes from @evren/agent-core) to friendly, actionable text.
 * Never invents facts the backend did not send.
 */
export interface FriendlyError {
  title: string;
  detail?: string;
  /** Retryable errors offer a retry button (offline / rate limit). */
  retryable: boolean;
}

export function friendlyError(err: unknown): FriendlyError {
  const code =
    typeof err === "object" && err !== null && "code" in err
      ? String((err as { code?: unknown }).code ?? "")
      : "";
  const message =
    err instanceof Error ? err.message : String(err ?? "unknown error");

  switch (code) {
    case "invalid_credentials":
      return {
        title: "Invalid email or password",
        retryable: false,
      };
    case "gateway_unreachable":
      return {
        title: "Cannot reach the backend",
        detail:
          "Check that the gateway is running and the backend URL in Settings is correct.",
        retryable: true,
      };
    case "registration_failed":
      return {
        title: "Registration failed",
        detail: message,
        retryable: false,
      };
    case "reauth_required":
      return {
        title: "Session expired",
        detail: "Please log in again.",
        retryable: false,
      };
    case "invalid_request":
      return {
        title: "Invalid request",
        detail: message,
        retryable: false,
      };
    default:
      // unmatched: show the raw message, keep it honest
      return { title: message, retryable: false };
  }
}
