/**
 * Actionable error box (M8): friendly handling for quota exceeded,
 * subscription inactive, rate limited (live countdown from Retry-After),
 * backend unreachable (retry), token expired (single re-login) and
 * upstream errors.
 */
import { useEffect, useState } from "react";
import { useAppStore } from "../stores/app";
import type { LiveTurn } from "../stores/chat";

function useCountdown(retryUntil: number | null): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (retryUntil === null || retryUntil <= Date.now()) return;
    const timer = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(timer);
  }, [retryUntil]);
  if (retryUntil === null) return null;
  return Math.max(0, Math.ceil((retryUntil - now) / 1000));
}

export function FriendlyErrorView({ turn }: { turn: LiveTurn }) {
  const logout = useAppStore((s) => s.logout);
  const countdown = useCountdown(turn.retryUntil);

  const headline = (): string => {
    switch (turn.errorCode) {
      case "quota_exceeded":
        return "Credit quota exhausted for this billing period";
      case "subscription_inactive":
        return "Your account has no active subscription";
      case "model_not_allowed":
        return "This tier is not available on your plan";
      case "rate_limited":
        return countdown !== null && countdown > 0
          ? `Rate limited — retry in ${countdown}s`
          : "Rate limited — you can retry now";
      case "reauth_required":
        return "Session expired";
      case "gateway_unreachable":
        return "Cannot reach the backend";
      case "upstream_unavailable":
      case "upstream_error":
        return "The model provider failed";
      case "timeout":
        return "The model request timed out";
      case "empty_response":
        return "The model returned an empty response";
      default:
        return turn.error ?? "Something went wrong";
    }
  };

  return (
    <div
      role="alert"
      className="rounded-md border border-red-900 bg-red-950/50 px-3 py-2 text-xs text-red-300"
    >
      <div className="flex items-center gap-2 font-medium">
        {turn.errorCode === "rate_limited" &&
          countdown !== null &&
          countdown > 0 && (
            <span
              aria-label="countdown"
              className="tabular-nums text-amber-300"
            >
              {countdown}s
            </span>
          )}
        <span>{headline()}</span>
      </div>
      {turn.errorCode !== "rate_limited" && turn.error && (
        <div className="mt-0.5 opacity-80">{turn.error}</div>
      )}
      {turn.errorCode === "empty_response" && (
        <div className="mt-1 opacity-80">
          The request finished without any content (the upstream model sent
          nothing). Use Retry below the input, or try a different tier.
        </div>
      )}
      {turn.errorCode === "quota_exceeded" && (
        <div className="mt-1 opacity-80">
          The request was not retried and nothing was charged. Check the credit
          indicator (top right) or upgrade your plan.
        </div>
      )}
      {turn.errorCode === "reauth_required" && (
        <button
          type="button"
          onClick={() => void logout()}
          className="mt-2 rounded border border-red-800 px-2 py-1 text-[11px] text-red-200 hover:bg-red-900/40"
        >
          Log in again
        </button>
      )}
    </div>
  );
}
