"use client";

import { useEffect } from "react";
import { cn } from "@/lib/utils";
import {
  useNotificationsStore,
  type Toast as ToastData,
  type ToastVariant,
} from "@/lib/stores/notifications";

const AUTO_DISMISS_MS = 5000;

const variantStyles: Record<ToastVariant, string> = {
  success: "border-green-600 bg-green-950 text-green-100",
  error: "border-red-600 bg-red-950 text-red-100",
  warning: "border-yellow-600 bg-yellow-950 text-yellow-100",
  info: "border-blue-600 bg-blue-950 text-blue-100",
};

const variantLabels: Record<ToastVariant, string> = {
  success: "Success",
  error: "Error",
  warning: "Warning",
  info: "Info",
};

function ToastItem({ toast }: { toast: ToastData }) {
  const removeToast = useNotificationsStore((s) => s.removeToast);

  useEffect(() => {
    const timer = setTimeout(() => {
      removeToast(toast.id);
    }, AUTO_DISMISS_MS);

    return () => clearTimeout(timer);
  }, [toast.id, removeToast]);

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "pointer-events-auto flex w-80 items-start gap-3 rounded-lg border p-4 shadow-lg",
        variantStyles[toast.variant],
      )}
    >
      <div className="flex-1 space-y-1">
        <p className="text-sm font-semibold">
          {toast.title}
        </p>
        {toast.description && (
          <p className="text-sm opacity-80">{toast.description}</p>
        )}
      </div>
      <button
        type="button"
        onClick={() => removeToast(toast.id)}
        className="shrink-0 rounded p-1 opacity-60 transition-opacity hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={`Dismiss ${variantLabels[toast.variant]} notification`}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </div>
  );
}

export function ToastContainer() {
  const toasts = useNotificationsStore((s) => s.toasts);

  if (toasts.length === 0) {
    return null;
  }

  return (
    <div
      aria-label="Notifications"
      className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col-reverse gap-2"
    >
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} />
      ))}
    </div>
  );
}
