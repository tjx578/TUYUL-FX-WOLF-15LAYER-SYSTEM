import { WsEventSchema, type WsEventParsed } from "@/schema/wsEventSchema";

export interface WsControls {
  close: () => void;
}

interface ConnectLiveUpdatesOptions {
  onEvent: (event: WsEventParsed) => void;
  onError?: (error: unknown) => void;
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

  socket.onmessage = (message) => {
    try {
      const parsed = JSON.parse(message.data as string);
      const event = WsEventSchema.parse(parsed);
      options.onEvent(event);
    } catch (error) {
      options.onError?.(error);
    }
  };

  socket.onerror = (error) => {
    options.onError?.(error);
  };

  return {
    close: () => {
      if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
        socket.close();
      }
    },
  };
}
