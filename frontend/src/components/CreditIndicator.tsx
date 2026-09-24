/**
 * Credit indicator (Issue 3 rework): remaining-first wording
 * ("82 credits left of 100"), color that only warns near actual
 * exhaustion (amber <25% left, red <10% left), a click breakdown
 * (plan, used, remaining, reset date, rate limit) and a distinct
 * zero-credit state with a clear message instead of a full bar.
 */
import { useState } from "react";
import type { UsageInfo } from "@shared/ipc";
import { useModelsStore } from "../stores/models";

const fmtCredits = (n: number): string =>
  n.toLocaleString(undefined, { maximumFractionDigits: 1 });

const fmtDate = (iso?: string): string =>
  iso ? new Date(iso).toLocaleDateString() : "—";

export function creditsRemainingPct(usage: UsageInfo): number {
  if (usage.creditLimit <= 0) return 0;
  return Math.max(
    0,
    Math.min(100, (usage.creditsRemaining / usage.creditLimit) * 100),
  );
}

/** tier for the remaining bar: normal -> amber <25% -> red <10% -> gone */
export function creditLevel(
  usage: UsageInfo,
): "ok" | "low" | "critical" | "gone" {
  if (usage.creditsRemaining <= 0) return "gone";
  const pct = creditsRemainingPct(usage);
  if (pct < 10) return "critical";
  if (pct < 25) return "low";
  return "ok";
}

export function CreditIndicator() {
  const usage = useModelsStore((s) => s.usage);
  const usageError = useModelsStore((s) => s.usageError);
  const usageErrorCode = useModelsStore((s) => s.usageErrorCode);
  const [open, setOpen] = useState(false);

  if (!usage) {
    if (usageErrorCode === "subscription_inactive") {
      return (
        <span
          className="rounded bg-amber-900/40 px-1.5 py-0.5 text-[10px] text-amber-300"
          title={usageError ?? undefined}
        >
          no active subscription
        </span>
      );
    }
    return null;
  }

  const level = creditLevel(usage);
  const usedPct =
    usage.creditLimit > 0
      ? Math.min(100, (usage.creditsUsed / usage.creditLimit) * 100)
      : 0;

  // zero-credit: a distinct, unambiguous state — message, not a bar
  if (level === "gone") {
    return (
      <span className="relative flex items-center">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-label="Credits exhausted"
          className="rounded bg-red-950/70 px-2 py-0.5 text-[10px] font-medium text-red-300 hover:bg-red-900/70"
          title="Credits used up — click for details"
        >
          credits used up — resets {fmtDate(usage.periodEnd)}
        </button>
        {open && (
          <CreditBreakdown usage={usage} onClose={() => setOpen(false)} />
        )}
      </span>
    );
  }

  const barColor =
    level === "critical"
      ? "bg-red-500"
      : level === "low"
        ? "bg-amber-500"
        : "bg-sky-500";

  return (
    <span className="relative flex items-center">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-label="Credits"
        title="Credits — click for details"
        className="flex items-center gap-1.5 text-neutral-400 hover:text-neutral-200"
      >
        <span className="h-1.5 w-14 overflow-hidden rounded-full bg-neutral-800">
          <span
            className={"block h-full " + barColor}
            style={{ width: `${usedPct}%` }}
          />
        </span>
        <span className="tabular-nums text-[10px]">
          {fmtCredits(usage.creditsRemaining)}{" "}
          <span className="text-neutral-500">credits left of</span>{" "}
          {fmtCredits(usage.creditLimit)}
        </span>
      </button>
      {open && <CreditBreakdown usage={usage} onClose={() => setOpen(false)} />}
    </span>
  );
}

function CreditBreakdown({
  usage,
  onClose,
}: {
  usage: UsageInfo;
  onClose: () => void;
}) {
  return (
    <span
      role="dialog"
      aria-label="Credit usage details"
      className="absolute right-0 top-full z-40 mt-1 block w-56 rounded-lg border border-neutral-700 bg-neutral-900 p-2 text-left text-[11px] shadow-xl"
    >
      <dl className="space-y-0.5 text-neutral-300">
        <div className="flex justify-between gap-2">
          <dt className="text-neutral-500">plan</dt>
          <dd>{usage.planName}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-neutral-500">used</dt>
          <dd className="tabular-nums">{fmtCredits(usage.creditsUsed)}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-neutral-500">remaining</dt>
          <dd className="tabular-nums">{fmtCredits(usage.creditsRemaining)}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-neutral-500">resets</dt>
          <dd>{fmtDate(usage.periodEnd)}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-neutral-500">rate limit</dt>
          <dd className="tabular-nums">{usage.requestsPerMinute} req/min</dd>
        </div>
      </dl>
      <button
        type="button"
        onClick={onClose}
        className="mt-1.5 w-full rounded border border-neutral-700 px-2 py-0.5 text-[10px] text-neutral-400 hover:bg-neutral-800"
      >
        close
      </button>
    </span>
  );
}
