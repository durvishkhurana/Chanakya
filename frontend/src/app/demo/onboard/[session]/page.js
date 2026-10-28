"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "../../../../lib/chanakyaApi";
import styles from "../../demo.module.css";

export default function MockOnboardingPage() {
  const { session } = useParams();
  const [info, setInfo] = useState(null);
  const [businessName, setBusinessName] = useState("");
  const [setupDay, setSetupDay] = useState("Tomorrow");
  const [confirmed, setConfirmed] = useState(false);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api(`/api/demo/onboarding/${session}`).then((data) => {
      setInfo(data);
      setBusinessName(data.merchant?.name || "");
    }).catch((e) => setError(e.message));
  }, [session]);

  async function complete(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      setResult(await api(`/api/demo/onboarding/${session}/complete`, { method: "POST" }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const finished = result || info?.session.status === "completed";
  const product = { soundbox: "Soundbox", card_machine: "card machine" }[info?.session.product] || (info?.session.product || "").replace("_", " ");
  return <div className={styles.shell}>
    <div className={styles.mockBar}><span>Onboarding · {product || "loading"}</span><span className={styles.mockTag}>Mock onboarding · not affiliated with Paytm</span></div>
    {error && <p className={styles.error} role="alert">{error}</p>}
    {info && finished && <section className={styles.done} aria-live="polite">
      <div className={styles.tick} aria-hidden="true">✓</div>
      <h1>You are all set.</h1>
      <p className={styles.lead} style={{ margin: "0 auto" }}>{info.merchant?.name}, your {product} onboarding is complete in the mock onboarding system.</p>
      {result?.verified_missions?.length > 0 && <p className={styles.note}>Chanakya checked the onboarding system and marked the mission done.</p>}
      <div className={styles.row} style={{ justifyContent: "center", marginTop: 20 }}>
        {result?.verified_missions?.[0] && <Link className={styles.secondary} href={`/missions?m=${result.verified_missions[0]}`}>See the mission</Link>}
      </div>
    </section>}
    {info && !finished && <section style={{ paddingTop: 36 }}>
      <p className="eyebrow"><span className="small-dot" /> ONE LAST STEP</p>
      <h1 style={{ fontSize: 40, letterSpacing: -1.5 }}>Finish your {product} setup</h1>
      <p className={styles.lead}>Confirm a couple of details. This mock asks for nothing sensitive: no OTP, PIN, card, bank or ID details.</p>
      <form className={styles.form} onSubmit={complete}>
        <label className={styles.field}>Business name<input value={businessName} onChange={(e) => setBusinessName(e.target.value)} required /></label>
        <label className={styles.field}>Preferred setup day
          <select value={setupDay} onChange={(e) => setSetupDay(e.target.value)}><option>Tomorrow</option><option>In two days</option><option>This weekend</option></select>
        </label>
        <label className={styles.check}><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} required />I confirm these details for this demo.</label>
        <button className={styles.primary} disabled={busy || !confirmed}>{busy ? "Completing…" : "Complete onboarding"}</button>
      </form>
    </section>}
  </div>;
}
