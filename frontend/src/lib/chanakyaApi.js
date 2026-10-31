"use client";

import { useEffect, useRef, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** WebSocket origin: the backend directly on the laptop; elsewhere (a phone through the tunnel) this page's own
 * origin, whose /api proxy forwards WebSockets to the backend. */
export function wsBase() {
  const { hostname, protocol, host } = window.location;
  if (hostname === "localhost" || hostname === "127.0.0.1") return API_URL.replace(/^http/, "ws");
  return `${protocol === "https:" ? "wss" : "ws"}://${host}`;
}

/** Whether the laptop-only demo tools (DEMO_TOOLS_ENABLED) are on and this page runs on the laptop. */
export function useDemoTools() {
  const [on, setOn] = useState(false);
  useEffect(() => {
    const { hostname } = window.location;
    if (hostname !== "localhost" && hostname !== "127.0.0.1") return;
    api("/api/phone-link").then(() => setOn(true)).catch(() => setOn(false));
  }, []);
  return on;
}

/** Retire a mission's run and put a fresh copy of it in the queue (demo tools). Returns the new mission's id. */
export async function resetMission(missionId) {
  return (await api(`/api/demo-tools/missions/${missionId}/reset`, { method: "POST" })).mission_id;
}

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
      socket = new WebSocket(`${wsBase()}/api/missions/stream?${params}`);
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
