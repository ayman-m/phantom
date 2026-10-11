import { create } from "zustand";

export type ToastVariant = "success" | "error" | "warning" | "info";

export interface Toast {
  id: string;
  variant: ToastVariant;
  title: string;
  description?: string;
}

export interface NotificationsState {
  toasts: Toast[];
  pendingApprovals: number;
  pendingPairings: number;
}

export interface NotificationsActions {
  addToast: (toast: Omit<Toast, "id">) => string;
  removeToast: (id: string) => void;
  incrementApprovals: () => void;
  decrementApprovals: () => void;
  incrementPairings: () => void;
  decrementPairings: () => void;
}

export type NotificationsStore = NotificationsState & NotificationsActions;

let nextToastId = 0;

function generateToastId(): string {
  nextToastId++;
  return `toast-${nextToastId}`;
}

/** Reset the ID counter (for testing). */
export function resetToastIdCounter(): void {
  nextToastId = 0;
}

export const useNotificationsStore = create<NotificationsStore>((set) => ({
  toasts: [],
  pendingApprovals: 0,
  pendingPairings: 0,

  addToast: (toast) => {
    const id = generateToastId();
    set((state) => ({
      toasts: [...state.toasts, { ...toast, id }],
    }));
    return id;
  },

  removeToast: (id: string) => {
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    }));
  },

  incrementApprovals: () => {
    set((state) => ({ pendingApprovals: state.pendingApprovals + 1 }));
  },

  decrementApprovals: () => {
    set((state) => ({
      pendingApprovals: Math.max(0, state.pendingApprovals - 1),
    }));
  },

  incrementPairings: () => {
    set((state) => ({ pendingPairings: state.pendingPairings + 1 }));
  },

  decrementPairings: () => {
    set((state) => ({
      pendingPairings: Math.max(0, state.pendingPairings - 1),
    }));
  },
}));
