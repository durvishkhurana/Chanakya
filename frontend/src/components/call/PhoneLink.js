"use client";

import { useRouter } from "next/navigation";
import QRCode from "qrcode";
import { useEffect, useState } from "react";

import { api, resetMission } from "../../lib/chanakyaApi";

/** Laptop-only demo tools (DEMO_TOOLS_ENABLED): open this call on a phone through a tunnel, and save the run log. */
export default function PhoneLink({ missionId }) {
  const router = useRouter();
  const [onLaptop, setOnLaptop] = useState(false);
  const [link, setLink] = useState(null);
  const [qr, setQr] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(null);

  useEffect(() => {
    const { hostname } = window.location;
    if (hostname !== "localhost" && hostname !== "127.0.0.1") return;
    setOnLaptop(true);
    api("/api/phone-link").then(setLink).catch(() => setLink(null));
  }, []);

  const phoneUrl = link?.running && link.url ? `${link.url}/call/${missionId}` : "";
  useEffect(() => {
    if (!phoneUrl) { setQr(""); return; }
    QRCode.toDataURL(phoneUrl, { margin: 1, width: 220 }).then(setQr).catch(() => setQr(""));
  }, [phoneUrl]);

  if (!onLaptop || !link) return null;

  async function run(label, path, apply) {
    setBusy(label);
    setError("");
    try { apply(await api(path, { method: "POST" })); }
    catch (err) { setError(err.message); }
    finally { setBusy(""); }
  }

  return <div className="panel" style={{ marginTop: 12, display: "grid", gap: 12 }}>
    <b>Demo tools</b>
    {phoneUrl ? <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
      {/* eslint-disable-next-line @next/next/no-img-element -- a generated data URL, nothing for next/image to optimise */}
      {qr && <img src={qr} width={220} height={220} alt={`QR code for ${phoneUrl}`} />}
      <div style={{ display: "grid", gap: 8, minWidth: 0 }}>
        <span className="meta">Scan with the phone, allow the microphone, then tap the black mic button to speak and tap it again to mute.</span>
        <a className="text-action" href={phoneUrl} target="_blank" rel="noreferrer" style={{ overflowWrap: "anywhere" }}>{phoneUrl}</a>
        <span className="meta">Anyone with this link can open the demo while it is connected.</span>
        <div><button className="btn" disabled={!!busy} onClick={() => run("stop", "/api/phone-link/stop", setLink)}>
          {busy === "stop" ? "Disconnecting…" : "Disconnect phone"}</button></div>
      </div>
    </div> : <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
      <button className="btn primary" disabled={!!busy} onClick={() => run("start", "/api/phone-link/start", setLink)}>
        {busy === "start" ? "Connecting… (up to 45 s)" : "Connect phone"}</button>
      <span className="meta">Opens this call on a phone through a temporary public link.</span>
    </div>}
    <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
      <button className="btn" disabled={!!busy} onClick={() => run("save", "/api/run-logs", setSaved)}>
        {busy === "save" ? "Saving…" : "Save run log"}</button>
      <button className="btn ghost" disabled={!!busy} onClick={async () => {
        setBusy("reset");
        setError("");
        try { router.push(`/call/${await resetMission(missionId)}`); }
        catch (err) { setError(err.message); }
        finally { setBusy(""); }
      }}>{busy === "reset" ? "Resetting…" : "Reset this call"}</button>
      {saved && <span className="meta">{saved.calls} calls ({saved.missions} missions) saved to <code>{saved.folder}</code></span>}
    </div>
    {saved && (saved.problems.length
      ? <ul className="error" role="alert" style={{ margin: 0 }}>{saved.problems.slice(0, 8).map((p) => <li key={p}>{p}</li>)}
        {saved.problems.length > 8 && <li>…and {saved.problems.length - 8} more in report.md</li>}</ul>
      : <span className="meta">No problems found.</span>)}
    {error && <p className="error" role="alert" style={{ margin: 0 }}>{error}</p>}
  </div>;
}
