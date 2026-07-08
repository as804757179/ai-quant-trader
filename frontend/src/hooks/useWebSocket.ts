import { useCallback, useEffect, useRef, useState } from "react";

type MessageHandler = (data: unknown) => void;

interface UseWebSocketOptions {
  /** 自动重连间隔基数（毫秒） */
  reconnectDelay?: number;
  /** 最大重连次数，默认无限 */
  maxRetries?: number;
  /** 心跳间隔（毫秒） */
  pingInterval?: number;
  enabled?: boolean;
}

function buildWsUrl(path: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = window.location.host;
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${protocol}//${host}${normalized}`;
}

/**
 * WebSocket Hook — 支持心跳、断线重连、JSON 消息解析。
 *
 * @example
 * const { lastMessage, sendPing, connected } = useWebSocket(
 *   "/ws/signals",
 *   (msg) => console.log("signal", msg),
 * );
 */
export function useWebSocket(
  path: string,
  onMessage?: MessageHandler,
  options: UseWebSocketOptions = {},
) {
  const {
    reconnectDelay = 1000,
    maxRetries = Infinity,
    pingInterval = 30000,
    enabled = true,
  } = options;

  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<unknown>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const retriesRef = useRef(0);
  const pingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onMessageRef = useRef(onMessage);

  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  const cleanup = useCallback(() => {
    if (pingTimerRef.current) {
      clearInterval(pingTimerRef.current);
      pingTimerRef.current = null;
    }
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setConnected(false);
  }, []);

  const connect = useCallback(() => {
    if (!enabled) return;

    const url = buildWsUrl(path);
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      retriesRef.current = 0;
      setConnected(true);
      pingTimerRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send("ping");
        }
      }, pingInterval);
    };

    ws.onmessage = (event) => {
      if (event.data === "pong") return;
      try {
        const parsed = JSON.parse(event.data);
        setLastMessage(parsed);
        onMessageRef.current?.(parsed);
      } catch {
        setLastMessage(event.data);
        onMessageRef.current?.(event.data);
      }
    };

    ws.onclose = () => {
      setConnected(false);
      if (pingTimerRef.current) {
        clearInterval(pingTimerRef.current);
        pingTimerRef.current = null;
      }
      if (!enabled) return;
      if (retriesRef.current >= maxRetries) return;

      retriesRef.current += 1;
      const delay = reconnectDelay * Math.min(retriesRef.current, 5);
      reconnectTimerRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [enabled, maxRetries, path, pingInterval, reconnectDelay]);

  useEffect(() => {
    connect();
    return cleanup;
  }, [connect, cleanup]);

  const sendPing = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send("ping");
    }
  }, []);

  return { connected, lastMessage, sendPing };
}