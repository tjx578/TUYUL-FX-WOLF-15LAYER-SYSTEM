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

function getWsUrl(): string {
  const wsUrl = process.env.NEXT_PUBLIC_WS_URL;
  if (!wsUrl || wsUrl.trim() === "") {
    throw new Error(
      "Missing NEXT_PUBLIC_WS_URL. Set NEXT_PUBLIC_WS_URL (e.g. ws://localhost:8000/ws/live)."
    );
  }
  return wsUrl;
}

export function connectLiveUpdates(options: ConnectLiveUpdatesOptions): WsControls {
  const url = getWsUrl();
  const socket = new WebSocket(url);

  socket.onopen = () => {
    options.onStatusChange?.("CONNECTED");
  };

  socket.onmessage = (message) => {
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

  socket.onerror = (error) => {
    options.onStatusChange?.("RECONNECTING");
    options.onError?.(error);
  };

  socket.onclose = () => {
    options.onStatusChange?.("DISCONNECTED");
  };

  return {
    close: () => {
      if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
        socket.close();
      }
    },
  };
}
