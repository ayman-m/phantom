/**
 * The one abort signal for a chat turn.
 *
 * It fires when the request's own signal does, or when `cancel()` is called
 * (the route calls it from the response stream's `cancel` callback, which runs
 * when the reader stops reading). Which of the two a streamed Next response
 * raises on a client disconnect varies by version, so the route wires both and
 * hands `signal` to every model call. Firing twice is harmless.
 *
 * Erasable TypeScript only (a node test loads this file directly).
 */
export function createTurnAbort(requestSignal: AbortSignal): { signal: AbortSignal; cancel: () => void } {
  const controller = new AbortController();
  const cancel = (): void => controller.abort();
  if (requestSignal.aborted) cancel();
  else requestSignal.addEventListener('abort', cancel, { once: true });
  return { signal: controller.signal, cancel };
}
