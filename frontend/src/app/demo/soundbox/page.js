"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "../../../lib/chanakyaApi";
import { doorLabel, percent, topWorries, worryLabel } from "../../../lib/missionView.mjs";
import styles from "../demo.module.css";

export default function SoundboxMockPage() {
  const [merchants, setMerchants] = useState([]);
  const [merchantId, setMerchantId] = useState("mer_ramesh");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/api/actions/merchants").then(setMerchants).catch((e) => setError(e.message));
  }, []);

  async function requestCallback() {
    setBusy(true);
    setError("");
    try {
      setResult(await api("/api/missions/signals", {
        method: "POST",
        body: { merchant_id: merchantId, kind: "callback_request", door: "merchant", source: "mock product page", details: { product: "soundbox" } },
      }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const card = result?.mission.card;
  return <div className={styles.shell}>
    <div className={styles.mockBar}><span>Demo storefront for Chanakya</span><span className={styles.mockTag}>Mock page · not affiliated with Paytm</span></div>
    <section className={styles.hero}>
      <div>
        <h1>Hear every payment the moment it lands.</h1>
        <p className={styles.lead}>A Soundbox speaks each received in-store payment out loud, so you never have to check your phone at a busy counter.</p>
        <div className={styles.row}>
          <select className={styles.select} value={merchantId} onChange={(e) => setMerchantId(e.target.value)} aria-label="Demo merchant">
            {(merchants.length ? merchants : [{ id: "mer_ramesh", name: "Ramesh Kirana Store", city: "Patiala" }]).map((m) =>
              <option key={m.id} value={m.id}>{m.name} · {m.city}</option>)}
          </select>
          <button className={styles.primary} onClick={requestCallback} disabled={busy}>{busy ? "Requesting…" : "Request a callback"} <span aria-hidden="true">↗</span></button>
        </div>
        <p className={styles.note}>Pick a fictional demo merchant, then ask for a call. Chanakya opens a mission through the “merchant raised a hand” door.</p>
        {error && <p className={styles.error} role="alert">{error}</p>}
      </div>
      <div className={styles.device} aria-hidden="true"><div>₹ RECEIVED</div></div>
    </section>

    {card && <section className={styles.card} aria-live="polite">
      <div className={styles.cardTop}>
        <h2>{result.created ? "Mission opened" : "Existing mission refreshed"}: {card.merchant_name}</h2>
        <span className={styles.pill}>{doorLabel(card.door)}</span>
      </div>
      <p className={styles.why}><strong>Why now:</strong> {card.why_now}<br /><strong>Goal:</strong> {card.goal}</p>
      <p className={styles.label}>Starting worries (the call begins with this guess)</p>
      {topWorries(card.starting_worries).map(([id, p]) => <div className={styles.bar} key={id}>
        <span>{worryLabel(id)}</span><div className={styles.track}><div className={styles.fill} style={{ width: percent(p) }} /></div><span>{percent(p)}</span>
      </div>)}
      <div className={styles.row} style={{ marginTop: 18 }}>
        <Link className={styles.primary} href={`/call/${result.mission.id}`}>Open the live call view</Link>
        <Link className={styles.secondary} href={`/missions?m=${result.mission.id}`}>See it in Mission Control</Link>
      </div>
    </section>}

    <section className={styles.facts}>
      <div className={styles.fact}><strong>Spoken confirmations</strong>Each received payment is announced at the counter.</div>
      <div className={styles.fact}><strong>Prices are not shown here</strong>Device charges and terms come only from the official channel.</div>
      <div className={styles.fact}><strong>Your data stays put</strong>This mock never asks for OTPs, PINs, card or bank details.</div>
    </section>
  </div>;
}
