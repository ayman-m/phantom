/**
 * Minimal Server-Sent Events reader shared by the streaming provider adapters.
 *
 * `createSseParser` is an incremental line parser: feed it decoded text in any
 * chunking (a chunk may end mid-line, mid-CRLF or mid-event) and it returns the
 * events completed so far. `readSse` wraps it around a byte stream, decoding
 * UTF-8 across chunk boundaries.
 *
 * Follows the SSE field rules the providers rely on: `\n`, `\r\n` and bare `\r`
 * line ends; a blank line dispatches the event; `data:` lines of one event are
 * joined with `\n`; a leading space after the colon is dropped; lines starting
 * with `:` are comments (keep-alives) and ignored; unknown fields are ignored;
 * an event with no `data` line is not dispatched. A final event with no
 * trailing blank line is dispatched by `flush()`.
 *
 * One event may not exceed `maxEventBytes` (default 16 MiB), so a hostile or
 * broken endpoint cannot grow memory without bound.
 *
 * Erasable TypeScript only; no imports.
 */

export interface SseEvent {
  /** The `event:` field; undefined when the event had none. */
  event?: string;
  data: string;
  id?: string;
}

export interface SseParser {
  /** Feed decoded text; returns the events completed by it. */
  push(text: string): SseEvent[];
  /** The stream ended: dispatch a pending event that lacked its blank line. */
  flush(): SseEvent[];
}

export const DEFAULT_MAX_SSE_EVENT_BYTES = 16 * 1024 * 1024;

export function createSseParser(opts: { maxEventBytes?: number } = {}): SseParser {
  const maxEventBytes = opts.maxEventBytes ?? DEFAULT_MAX_SSE_EVENT_BYTES;
  let buffer = '';
  let eventName: string | undefined;
  let eventId: string | undefined;
  let dataLines: string[] = [];
  let pendingBytes = 0;
  let sawBom = false;

  function tooLarge(): never {
    throw new Error(`SSE event larger than ${maxEventBytes} bytes`);
  }

  function dispatch(out: SseEvent[]): void {
    if (dataLines.length > 0) {
      const event: SseEvent = { data: dataLines.join('\n') };
      if (eventName !== undefined) event.event = eventName;
      if (eventId !== undefined) event.id = eventId;
      out.push(event);
    }
    eventName = undefined;
    eventId = undefined;
    dataLines = [];
    pendingBytes = 0;
  }

  function handleLine(line: string, out: SseEvent[]): void {
    if (line === '') {
      dispatch(out);
      return;
    }
    if (line.startsWith(':')) return;
    const colon = line.indexOf(':');
    const field = colon < 0 ? line : line.slice(0, colon);
    let value = colon < 0 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    pendingBytes += line.length;
    if (pendingBytes > maxEventBytes) tooLarge();
    if (field === 'data') dataLines.push(value);
    else if (field === 'event') eventName = value;
    else if (field === 'id') eventId = value;
  }

  function drain(final: boolean): SseEvent[] {
    const out: SseEvent[] = [];
    let start = 0;
    let i = 0;
    while (i < buffer.length) {
      const ch = buffer[i];
      if (ch === '\n' || ch === '\r') {
        // A trailing \r may be the first half of \r\n; wait for the next chunk.
        if (ch === '\r' && i === buffer.length - 1 && !final) break;
        handleLine(buffer.slice(start, i), out);
        i += ch === '\r' && buffer[i + 1] === '\n' ? 2 : 1;
        start = i;
      } else {
        i++;
      }
    }
    buffer = buffer.slice(start);
    if (buffer.length > maxEventBytes) tooLarge();
    if (final) {
      if (buffer !== '') {
        handleLine(buffer, out);
        buffer = '';
      }
      dispatch(out);
    }
    return out;
  }

  return {
    push(text: string): SseEvent[] {
      if (!sawBom) {
        if (text === '') return [];
        sawBom = true;
        if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
      }
      buffer += text;
      return drain(false);
    },
    flush(): SseEvent[] {
      return drain(true);
    },
  };
}

/**
 * Read a response body as SSE events. Decodes UTF-8 incrementally, so a
 * multibyte character split across chunks survives. `onChunk` runs for every
 * network chunk, including those that complete no event (comments, pings), so
 * a caller can reset an idle timer on any traffic.
 */
export async function* readSse(
  body: ReadableStream<Uint8Array>,
  opts: { maxEventBytes?: number; onChunk?: () => void } = {},
): AsyncGenerator<SseEvent> {
  const parser = createSseParser({ maxEventBytes: opts.maxEventBytes });
  const decoder = new TextDecoder('utf-8');
  const reader = body.getReader();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      opts.onChunk?.();
      for (const event of parser.push(decoder.decode(value, { stream: true }))) yield event;
    }
    for (const event of parser.push(decoder.decode())) yield event;
    for (const event of parser.flush()) yield event;
  } finally {
    // Release the connection if the consumer stopped early or an error threw.
    reader.cancel().catch(() => {});
  }
}
