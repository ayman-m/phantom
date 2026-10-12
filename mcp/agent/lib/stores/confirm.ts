import { create } from "zustand";

/**
 * Promise-based in-app confirmation, the replacement for window.confirm().
 *
 *   if (!(await confirmAction({ title: "Delete hook?", message: "...", tone: "danger" }))) return;
 *
 * `ConfirmDialogHost` (mounted once in components/providers.tsx) renders the
 * pending request as a modal. Requests made while one is open queue and show
 * in order, so two quick clicks never lose a prompt. The function can be called
 * from any handler, hook or plain callback.
 */

export type ConfirmTone = "default" | "danger";

export interface ConfirmOptions {
  title: string;
  message?: string;
  /** Label of the accept button. Default "Confirm". */
  confirmLabel?: string;
  /** Label of the dismiss button. Default "Cancel". */
  cancelLabel?: string;
  /** "danger" styles the accept button as destructive and focuses Cancel first. */
  tone?: ConfirmTone;
}

export interface PendingConfirm {
  id: number;
  options: ConfirmOptions;
  resolve: (accepted: boolean) => void;
}

interface ConfirmState {
  queue: PendingConfirm[];
  /** Resolve the request at the head of the queue and show the next one. */
  settle: (accepted: boolean) => void;
}

let nextId = 0;

export const useConfirmStore = create<ConfirmState>((set, get) => ({
  queue: [],
  settle: (accepted) => {
    const [head, ...rest] = get().queue;
    if (!head) return;
    set({ queue: rest });
    head.resolve(accepted);
  },
}));

export function confirmAction(options: ConfirmOptions): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    nextId += 1;
    useConfirmStore.setState((s) => ({
      queue: [...s.queue, { id: nextId, options, resolve }],
    }));
  });
}
