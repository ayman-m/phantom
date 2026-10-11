import { redirect } from "next/navigation";

/**
 * /audit moved to /observability/events as part of the observability
 * rework — events live under observability now, alongside metrics,
 * traces, logs, and pipeline. Keep this redirect so any bookmarks
 * the operator had still land in the right place.
 */
export default function AuditRedirectPage() {
  redirect("/observability/events");
}
