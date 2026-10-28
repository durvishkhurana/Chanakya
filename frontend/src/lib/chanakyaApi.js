"use client";

import { useEffect, useRef, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** JSON request to the backend through the same-origin /api proxy. Throws with the server's detail on error. */
export async function api(path, { method = "GET", body } = {}) {
  const response = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${response.status})`);
  return data;
}

/** Live ledger events over WebSocket, with a replay of recent history and automatic reconnects. */
export function useMissionStream({ missionId = null, replay = 200, enabled = true } = {}) {
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);
  const seen = useRef(new Set());

  useEffect(() => {
    if (!enabled) return undefined;
    let socket;
    let retry;
    let closed = false;
    seen.current = new Set();
    setEvents([]);

    const connect = () => {
      const params = new URLSearchParams({ replay: String(replay) });
      if (missionId) params.set("mission_id", missionId);
      socket = new WebSocket(`${API_URL.replace(/^http/, "ws")}/api/missions/stream?${params}`);
      socket.onopen = () => setConnected(true);
      socket.onmessage = (message) => {
        const event = JSON.parse(message.data);
        if (seen.current.has(event.id)) return;
        seen.current.add(event.id);
        setEvents((current) => [...current, event]);
      };
      socket.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(connect, 1500);
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      socket?.close();
    };
  }, [missionId, replay, enabled]);

  return { events, connected };
}
