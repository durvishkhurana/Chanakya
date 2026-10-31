"use client";

import { Figtree, League_Spartan } from "next/font/google";
import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import Doors from "../components/landing/Doors";
import TryDemo from "../components/landing/TryDemo";
import { STAGES, stageWeights } from "../lib/landingData.mjs";
import useVoiceCall, { primeVoiceAudio } from "../lib/useVoiceCall";
import "./landing.css";

const display = League_Spartan({ subsets: ["latin"], weight: ["700"], variable: "--font-display", display: "swap" });
const text = Figtree({ subsets: ["latin"], weight: ["400", "600"], variable: "--font-text", display: "swap" });

const TAGLINE = "Most sales bots pick the next sentence. Chanakya picks the next move.";

const FAQ = [
  ["Does it make up prices or offers?", "No. Product facts come only from sourced pages with a review date. When a merchant asks about charges, Chanakya says it will not guess and points to the official channel, in writing, before anything is signed."],
  ["Is a quick “haan” a yes?", "No. Before any change Chanakya asks for an explicit yes for that exact action and records it in the mission ledger. A short acknowledgement never counts as consent."],
  ["Will it ever ask for an OTP or a PIN?", "Never. Its safety gate blocks any action that mentions an OTP, UPI PIN, CVV, password, card number or identity document, and every attempt is written to an audit trail."],
  ["What happens when a merchant gets upset?", "Chanakya hands the call to a person early, with a card that carries the open worries, the moves already tried and the actions taken, so the merchant never has to repeat themselves."],
  ["How do you know the job is really done?", "A mission closes as done only when a system confirms it, such as the onboarding system reporting a finished signup. Until then Chanakya sends at most two reminders, inside calling hours."],
  ["Which languages does it speak?", "Hindi, Punjabi, Hinglish and English, with seven more Indian languages detected automatically by the speech layer."],
  ["Is this Paytm’s product?", "No. Chanakya is an independent hackathon project. Every business system it acts on in this demo is a labelled mock."],
];

const BLOCKS = [["c", 1, "#232323"], ["h", 0.78, "#a1ffcb"], ["a", 0.92, "#8a8a8a"], ["n", 0.66, "#232323"], ["a", 1, "#a1ffcb"], ["k", 0.84, "#232323"], ["y", 0.72, "#8a8a8a"], ["a", 0.95, "#232323"]];

export default function Home() {
  const [inCall, setInCall] = useState(false);
  const root = useRef(null);
  useLandingMotion(root);
  const weights = stageWeights();

  return <div ref={root} className={`lp ${display.variable} ${text.variable}`}>
    <a className="skip" href="#main">Skip to content</a>
    <header className="topbar">
      <Link className="tile logo" href="/" aria-label="Chanakya home">c</Link>
      <div className="tile links"><nav aria-label="Main">
        <a href="#try">Try it</a><a href="#how">How it works</a><Link href="/missions">Mission control</Link><a href="#faq">Questions</a>
      </nav></div>
      <button className="tile action" onClick={() => { primeVoiceAudio(); setInCall(true); }}>Talk to Chanakya</button>
    </header>

    <main id="main">
      <section className="board" aria-label="Chanakya">
        <div className="tile name">
          <h1><span className="display">chanakya</span><span className="what">The AI teammate for merchant sales and service</span></h1>
        </div>
        <div className="tile photo shutter"><Image src="/assets/species-shop-in-chandni-chowk.jpg" alt="A dry fruit shop counter in Chandni Chowk, Delhi, with priced bowls and a weighing scale" fill sizes="(max-width: 900px) 100vw, 50vw" priority /></div>
        <div className="tile photo second"><Image src="/assets/chandni-chowk-delhi-2278255256.jpg" alt="Handwritten price cards on bowls of dry fruit and spices in Chandni Chowk" fill sizes="(max-width: 900px) 100vw, 50vw" /></div>
        <div className="split">
          <p className="tile statement dark">Calls merchants in Hindi, Punjabi and Hinglish, hears the worry they do not say, and plans its next move.</p>
          <p className="tile statement mint">Sends the link only after a clear yes, then checks the job is really done.</p>
        </div>
      </section>

      <section aria-labelledby="slogan">
        <div className="mosaic">
          <div className="tile slogan"><h2 id="slogan" className="display" data-reveal>Plans the move</h2></div>
          <div className="tile figure" data-reveal style={{ "--i": 1 }}>
            <span className="display" data-count="62">62%</span>
            <p>hidden charges, read from one line: “kitna katega?”</p>
          </div>
          <div className="tile photo drift colour"><Image src="/assets/sangam-general-store-chinawal.jpg" alt="Closed shutters of a village general store with its name hand painted in Devanagari" fill sizes="(max-width: 900px) 100vw, 50vw" /></div>
        </div>
        <div className="longtext">
          <div className="sources" data-reveal style={{ "--i": 2 }}>
            <p>The research it is built on</p>
            <ul>
              <li><a href="https://arxiv.org/abs/2605.22240">Unlocking Proactivity in Task Oriented Dialogue (2026)</a></li>
              <li><a href="https://arxiv.org/abs/2604.11427">METRO: Strategy Induction from Expert Transcripts (ACL 2026)</a></li>
              <li><a href="https://arxiv.org/abs/2511.21706">NRPA for Goal Oriented Dialogue (AAAI 2026)</a></li>
              <li><a href="https://arxiv.org/abs/2606.20708">Simulated Customers Never Walk Away (2026)</a></li>
            </ul>
          </div>
          <p className="body" data-reveal style={{ "--i": 1 }}>Most sales bots choose the next sentence. A shopkeeper between two customers needs something else: someone who hears that “kitna katega?” really means “I am scared of hidden charges”. Research on outbound merchant calls found that more sampling and reward shaping did not lift acceptance, while conditioning on the merchant’s hidden concerns did. Chanakya keeps a live estimate of those concerns, tries a few possible moves against simulated merchants before it speaks, and then answers in the merchant’s own language with facts from sourced product pages. When the meter reads 62% hidden charges, it answers the charges question first.</p>
        </div>
      </section>

      <section className="showcase" id="try" aria-labelledby="try-title">
        <h2 id="try-title" className="display" data-reveal>Try a merchant’s line</h2>
        <p data-reveal style={{ "--i": 1 }}>Choose what Ramesh says on the right. See what Chanakya thinks before it answers.</p>
        <TryDemo />
        <p className="demo-note">Pick a line. The concern meter and the next move change at once. Replies follow the same rules as live calls: no guessed prices, no requests for secrets.</p>
      </section>

      <section className="tagline" aria-label="What Chanakya does differently">
        <p>{TAGLINE.split(" ").map((w, i) => <span key={i}><span className="word">{w}</span>{" "}</span>)}</p>
      </section>

      <section className="stages" id="how" aria-labelledby="how-title">
        <h2 id="how-title" className="display" data-reveal>From a raised hand to done</h2>
        <div className="bar" data-ui data-reveal style={{ "--i": 1 }}>
          {STAGES.map((s, i) => <div key={i} className="seg" style={{ flex: weights[i] }}>{s.duration}<small><b>{s.order}</b>, {s.text}</small></div>)}
        </div>
        <div className="clauses">
          {STAGES.map((s, i) => <p key={i} style={{ flex: weights[i] }} data-reveal><b>{s.order}</b>, {s.text}</p>)}
        </div>
      </section>

      <section className="doors" aria-labelledby="doors-title">
        <div className="doors-head">
          <h2 id="doors-title" className="display" data-reveal><span>Three doors in.</span>One mission card out.</h2>
          <Link className="btn btn-dark" href="/missions">Open Mission control</Link>
        </div>
        <Doors />
      </section>

      <section className="faq" id="faq" aria-labelledby="faq-title">
        <div className="faq-head"><h2 id="faq-title" className="display" data-reveal>Fair questions</h2></div>
        {FAQ.map(([q, a]) => <div key={q} className="qa"><h3 data-reveal>{q}</h3><p data-reveal style={{ "--i": 1 }}>{a}</p></div>)}
      </section>

      <section className="cta" aria-labelledby="cta-title">
        <div className="tile photo colour"><Image src="/assets/shop-in-chandni-chowk-3.jpg" alt="A busy accessories shop in Chandni Chowk with the owner at the counter" fill sizes="(max-width: 900px) 100vw, 50vw" /></div>
        <div className="tile mint-tile">
          <div>
            <h2 id="cta-title" className="display">Hear it for yourself</h2>
            <p>Talk to Chanakya in Hindi or English, right in your browser. Your microphone stops the moment you end the call.</p>
            <button className="btn btn-dark" onClick={() => { primeVoiceAudio(); setInCall(true); }}>Talk to Chanakya</button>
          </div>
          <p className="prompt"><span>Try saying</span>“Meri kirana ki dukaan hai. Soundbox kya karta hai, aur kitna katega?”</p>
        </div>
        <div className="tile flat" aria-hidden="true" />
      </section>
    </main>

    <footer>
      <div className="blocks" role="img" aria-label="Chanakya, built from blocks">
        {BLOCKS.map(([letter, h, colour], i) => <span key={i} className="block"
          style={{ height: `${h * 100}%`, background: colour, color: colour === "#a1ffcb" ? "#232323" : "#ffffff" }}>{letter}</span>)}
      </div>
      <div className="footer-grid">
        <nav aria-label="Product"><b>Product</b><Link href="/missions">Mission control</Link><Link href="/call/demo">Recorded call</Link><a href="#try">Try a line</a></nav>
        <nav aria-label="Demo"><b>Demo</b><Link href="/demo/soundbox">Mock product page</Link><a href="#how">How it works</a><a href="#faq">Questions</a></nav>
        <div className="contact"><span>Built by Team Legacy, Thapar University</span><span>For the Paytm AI Hackathon, Track 3</span><span>Independent project, not affiliated with Paytm. Business systems in this demo are labelled mocks.</span></div>
      </div>
      <p className="credits">Pictures show the merchants’ world, not Chanakya’s customers: <a href="https://commons.wikimedia.org/wiki/File:Species_shop_in_Chandni_Chowk.jpg">“Species shop in Chandni Chowk”</a> and <a href="https://commons.wikimedia.org/wiki/File:Shop_in_Chandni_Chowk_3.jpg">“Shop in Chandni Chowk 3”</a> by SimónK, <a href="https://creativecommons.org/licenses/by-sa/4.0">CC BY-SA 4.0</a>; <a href="https://commons.wikimedia.org/wiki/File:Chandni_Chowk,_Delhi_(2278255256).jpg">“Chandni Chowk, Delhi”</a> by Dan from Brussels, <a href="https://creativecommons.org/licenses/by-sa/2.0">CC BY-SA 2.0</a>; <a href="https://commons.wikimedia.org/wiki/File:Sangam_General_Store_Chinawal.jpg">“Sangam General Store Chinawal”</a> by abhiriksh, <a href="https://creativecommons.org/licenses/by-sa/3.0">CC BY-SA 3.0</a>; all via Wikimedia Commons, shown in greyscale or cropped.</p>
      <div className="last-row"><span>© 2026 Team Legacy</span><button className="btn btn-dark" onClick={() => { primeVoiceAudio(); setInCall(true); }}>Talk to Chanakya</button></div>
    </footer>

    {inCall && <VoiceSession onClose={() => setInCall(false)} />}
  </div>;
}

/** Entrances once per element, the tagline lit word by word, the headline figure counted up. All skipped for reduced motion. */
function useLandingMotion(root) {
  useEffect(() => {
    const el = root.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return undefined;
    el.classList.add("js");
    const reveal = new IntersectionObserver((entries) => entries.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add("in"); reveal.unobserve(e.target); }
    }), { threshold: 0.15 });
    el.querySelectorAll("[data-reveal]").forEach((n) => reveal.observe(n));

    // Words light in reading order as they cross 60% of the viewport height.
    const words = new IntersectionObserver((entries) => entries.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add("lit"); words.unobserve(e.target); }
    }), { rootMargin: "0px 0px -40% 0px" });
    el.querySelectorAll(".tagline .word").forEach((n, i) => { n.style.transitionDelay = `${(i % 6) * 60}ms`; words.observe(n); });

    const counters = new IntersectionObserver((entries) => entries.forEach((e) => {
      if (!e.isIntersecting) return;
      counters.unobserve(e.target);
      const target = Number(e.target.dataset.count);
      const start = performance.now();
      const tick = (now) => {
        const t = Math.min(1, (now - start) / 1200);
        e.target.textContent = `${Math.round(target * (1 - (1 - t) ** 3))}%`;
        if (t < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }), { threshold: 0.6 });
    el.querySelectorAll("[data-count]").forEach((n) => counters.observe(n));
    return () => { reveal.disconnect(); words.disconnect(); counters.disconnect(); };
  }, [root]);
}

function Microphone({ end = false }) {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    {end ? <><path d="M4 15c4-5 12-5 16 0" /><path d="M4 15v4h4v-5M20 15v4h-4v-5" /></> : <><rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3M8 21h8" /></>}
  </svg>;
}

function VoiceSession({ onClose }) {
  const call = useVoiceCall({ isOpen: true, onClose, retrievalProvider: "llm_batch", pushToTalk: true });
  const ready = call.callState !== "connecting" && call.callState !== "error";
  const labels = { connecting: "Connecting to Chanakya", listening: "Chanakya is listening", processing: "One moment", thinking: "Finding the right fit", speaking: "Chanakya is speaking", error: "Let us reconnect" };
  return <div className="session-backdrop" ref={call.callOverlayRef}>
    <section className="session" role="dialog" aria-modal="true" aria-labelledby="session-title" data-state={call.callState}>
      <div className="session-top"><span>Your conversation</span><span className="timer">{call.duration}</span></div>
      <div className="voice-emblem" aria-hidden="true"><i /><i /><i /><i /><i /></div>
      <h2 id="session-title">{labels[call.callState]}</h2>
      <p className="session-status" role="status">{call.callState === "error" ? call.connectionError : "Speak naturally, in Hindi or English. We will take it one question at a time."}</p>
      <div className="transcript" ref={call.messagesContainerRef} tabIndex={0} aria-label="Conversation transcript" aria-live="polite">
        {call.callMessages.length ? call.callMessages.map((message) => <article key={message.id} className={`utterance ${message.role}`}><span>{message.role === "user" ? "You" : "Chanakya"}</span><p>{message.text || "Thinking..."}</p></article>) : <p className="transcript-empty">Try saying, “Meri kirana ki dukaan hai. Soundbox kya karta hai?”</p>}
      </div>
      <button
        type="button"
        className="push-to-talk"
        data-talking={call.talking}
        disabled={!ready}
        aria-pressed={call.talking}
        onClick={call.toggleMic}
      ><Microphone />{call.talking ? "Listening, tap to mute" : "Tap to talk"}</button>
      <button className="end-call" ref={call.endButtonRef} onClick={call.handleEndCall}><Microphone end />End conversation</button>
      <p className="session-footnote">Tap the mic to speak and tap it again to mute. End the conversation to stop the microphone.</p>
    </section>
  </div>;
}
