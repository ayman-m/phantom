import type {
  EventMessage,
  HelloMessage,
  InboundMessage,
  OutboundMessage,
} from "./types";

/** Connection state of the WebSocket manager. */
export enum ConnectionState {
  CONNECTING = "CONNECTING",
  CONNECTED = "CONNECTED",
  RECONNECTING = "RECONNECTING",
  DISCONNECTED = "DISCONNECTED",
}

/** Callback invoked when a typed event is received. */
export type EventCallback = (message: EventMessage) => void;

/** Callback invoked when connection state changes. */
export type StateCallback = (state: ConnectionState) => void;

const BASE_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 30_000;
const PING_INTERVAL_MS = 30_000;
const PONG_TIMEOUT_MS = 10_000;

export class WebSocketManager {
  private ws: WebSocket | null = null;
  private state: ConnectionState = ConnectionState.DISCONNECTED;
  private url = "";
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private pongTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionalClose = false;

  private readonly channels = new Set<string>();
  private readonly eventListeners = new Map<string, Set<EventCallback>>();
  private readonly stateListeners = new Set<StateCallback>();

  /** Current connection state. */
  get connectionState(): ConnectionState {
    return this.state;
  }

  /** Currently subscribed channels. */
  get subscribedChannels(): ReadonlySet<string> {
    return this.channels;
  }

  /** Open a WebSocket connection. */
  connect(url: string): void {
    if (this.ws) {
      this.cleanupConnection();
    }

    this.url = url;
    this.intentionalClose = false;
    this.setState(ConnectionState.CONNECTING);
    this.createSocket();
  }

  /** Gracefully close the connection without reconnecting. */
  disconnect(): void {
    this.intentionalClose = true;
    this.cleanupConnection();
    this.setState(ConnectionState.DISCONNECTED);
  }

  /** Subscribe to one or more channels. Sends subscribe if connected. */
  subscribe(channels: string[]): void {
    for (const ch of channels) {
      this.channels.add(ch);
    }
    if (this.state === ConnectionState.CONNECTED) {
      this.send({ type: "subscribe", channels });
    }
  }

  /** Unsubscribe from one or more channels. Sends unsubscribe if connected. */
  unsubscribe(channels: string[]): void {
    for (const ch of channels) {
      this.channels.delete(ch);
    }
    if (this.state === ConnectionState.CONNECTED) {
      this.send({ type: "unsubscribe", channels });
    }
  }

  /** Send a typed message over the WebSocket. */
  send(message: OutboundMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    }
  }

  /** Register a callback for events on a specific event type. */
  on(eventType: string, callback: EventCallback): void {
    let listeners = this.eventListeners.get(eventType);
    if (!listeners) {
      listeners = new Set();
      this.eventListeners.set(eventType, listeners);
    }
    listeners.add(callback);
  }

  /** Remove a previously registered event callback. */
  off(eventType: string, callback: EventCallback): void {
    this.eventListeners.get(eventType)?.delete(callback);
  }

  /** Register a callback for connection state changes. */
  onStateChange(callback: StateCallback): void {
    this.stateListeners.add(callback);
  }

  /** Remove a state change callback. */
  offStateChange(callback: StateCallback): void {
    this.stateListeners.delete(callback);
  }

  // ---- Private ----

  private createSocket(): void {
    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      // Wait for the hello message before marking CONNECTED
    };

    this.ws.onmessage = (event: MessageEvent) => {
      this.handleMessage(event);
    };

    this.ws.onclose = () => {
      this.stopPing();
      if (!this.intentionalClose) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      // The close event will fire after error — reconnect is handled there.
    };
  }

  private handleMessage(event: MessageEvent): void {
    let msg: InboundMessage;
    try {
      msg = JSON.parse(String(event.data)) as InboundMessage;
    } catch {
      return;
    }

    switch (msg.type) {
      case "hello":
        this.onHello(msg);
        break;
      case "pong":
        this.onPong();
        break;
      case "event":
        this.dispatchEvent(msg);
        break;
    }
  }

  private onHello(_msg: HelloMessage): void {
    this.reconnectAttempt = 0;
    this.setState(ConnectionState.CONNECTED);
    this.startPing();
    this.resubscribe();
  }

  private onPong(): void {
    this.clearPongTimeout();
  }

  private resubscribe(): void {
    if (this.channels.size > 0) {
      this.send({ type: "subscribe", channels: Array.from(this.channels) });
    }
  }

  private dispatchEvent(msg: EventMessage): void {
    const listeners = this.eventListeners.get(msg.event);
    if (listeners) {
      for (const cb of listeners) {
        cb(msg);
      }
    }
  }

  private startPing(): void {
    this.stopPing();
    this.pingTimer = setInterval(() => {
      this.send({ type: "ping", timestamp: Date.now() });
      this.startPongTimeout();
    }, PING_INTERVAL_MS);
  }

  private stopPing(): void {
    if (this.pingTimer !== null) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
    this.clearPongTimeout();
  }

  private startPongTimeout(): void {
    this.clearPongTimeout();
    this.pongTimer = setTimeout(() => {
      // Pong not received in time — force reconnect.
      this.ws?.close();
    }, PONG_TIMEOUT_MS);
  }

  private clearPongTimeout(): void {
    if (this.pongTimer !== null) {
      clearTimeout(this.pongTimer);
      this.pongTimer = null;
    }
  }

  private scheduleReconnect(): void {
    this.setState(ConnectionState.RECONNECTING);
    const delay = Math.min(
      BASE_RECONNECT_DELAY_MS * Math.pow(2, this.reconnectAttempt),
      MAX_RECONNECT_DELAY_MS,
    );
    this.reconnectAttempt++;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.createSocket();
    }, delay);
  }

  private cleanupConnection(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.stopPing();
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.close();
      this.ws = null;
    }
  }

  private setState(newState: ConnectionState): void {
    if (this.state === newState) return;
    this.state = newState;
    for (const cb of this.stateListeners) {
      cb(newState);
    }
  }
}
