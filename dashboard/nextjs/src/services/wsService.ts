import { WsEventSchema, type WsEventParsed } from "@/schema/wsEventSchema";
import type { SystemStatusView } from "@/contracts/wsEvents";

export type WsConnectionStatus = "CONNECTED" | "DISCONNECTED" | "RECONNECTING";

export interface WsControls {
  close: () => void;
}

interface ConnectLiveUpdatesOptions {
  onEvent: (event: WsEventParsed) => void;
  onError?: (error: unknown) => void;
  onStatusChange?: (status: WsConnectionStatus) => void;
  onDegradation?: (status: SystemStatusView) => void;
}

function getWsUrl(): string | null {
  const wsUrl = process.env.NEXT_PUBLIC_WS_URL;
  if (!wsUrl || wsUrl.trim() === "") {
    return null;
  }
  return wsUrl;
}

export function connectLiveUpdates(options: ConnectLiveUpdatesOptions): WsControls {
  const url = getWsUrl();

  // No WS URL configured — immediately report DISCONNECTED/degraded, no crash.
  if (!url) {
    options.onStatusChange?.("DISCONNECTED");
    options.onDegradation?.({
      mode: "DEGRADED",
      reason: "Backend unreachable: NEXT_PUBLIC_WS_URL not configured. Operating in offline mode.",
    });
    return { close: () => {} };
  }

  let socket: WebSocket;
  try {
    socket = new WebSocket(url);
  } catch {
    options.onStatusChange?.("DISCONNECTED");
    options.onDegradation?.({
      mode: "DEGRADED",
      reason: `WebSocket connection failed to ${url}. Backend may be offline.`,
    });
    return { close: () => {} };
  }

  const socketRef = socket;

  socketRef.onopen = () => {
    options.onStatusChange?.("CONNECTED");
  };

  socketRef.onmessage = (message) => {
    try {
      const parsed = JSON.parse(message.data as string);
      const event = WsEventSchema.parse(parsed);
      options.onEvent(event);
      if (event.type === "SystemStatusUpdated") {
        options.onDegradation?.(event.payload);
      }
    } catch (error) {
      options.onError?.(error);
    }
  };

  socketRef.onerror = () => {
    options.onStatusChange?.("RECONNECTING");
    options.onDegradation?.({
      mode: "DEGRADED",
      reason: "WebSocket connection error. Backend may be offline or unreachable.",
    });
  };

  socketRef.onclose = () => {
    options.onStatusChange?.("DISCONNECTED");
  };

  return {
    close: () => {
      if (
        socketRef.readyState === WebSocket.OPEN ||
        socketRef.readyState === WebSocket.CONNECTING
      ) {
        socketRef.close();
      }
    },
  };
}
