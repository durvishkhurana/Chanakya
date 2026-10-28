"use client";

import { useState } from "react";
import Link from "next/link";
import useVoiceCall from "../lib/useVoiceCall";

const PRODUCTS = [
  { number: "01", name: "QR payments", description: "For your everyday counter.", symbol: "▦" },
  { number: "02", name: "Soundbox", description: "Hear when a payment arrives.", symbol: "≋" },
  { number: "03", name: "Card machine", description: "Make room for card payments.", symbol: "▱" },
  { number: "04", name: "Online payments", description: "For a website or a remote order.", symbol: "↗" },
];

function Microphone({ end = false }) {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    {end ? <><path d="M4 15c4-5 12-5 16 0" /><path d="M4 15v4h4v-5M20 15v4h-4v-5" /></> : <><rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3M8 21h8" /></>}
  </svg>;
}

function VoiceSession({ onClose }) {
  const call = useVoiceCall({ isOpen: true, onClose, retrievalProvider: "llm_batch" });
  const labels = { connecting: "Connecting to Chanakya", listening: "Chanakya is listening", processing: "One moment", thinking: "Finding the right fit", speaking: "Chanakya is speaking", error: "Let's reconnect" };
  return <div className="session-backdrop" ref={call.callOverlayRef}>
    <section className="session" role="dialog" aria-modal="true" aria-labelledby="session-title" data-state={call.callState}>
      <div className="session-top"><span className="eyebrow">YOUR CONVERSATION</span><span className="timer">{call.duration}</span></div>
      <div className="voice-emblem" aria-hidden="true"><i /><i /><i /><i /><i /></div>
      <h2 id="session-title">{labels[call.callState]}</h2>
      <p className="session-status" role="status">{call.callState === "error" ? call.connectionError : "Speak naturally. We'll take it one question at a time."}</p>
      <div className="transcript" ref={call.messagesContainerRef} tabIndex={0} aria-label="Conversation transcript" aria-live="polite">
        {call.callMessages.length ? call.callMessages.map(message => <article key={message.id} className={`utterance ${message.role}`}><span>{message.role === "user" ? "YOU" : "MIRA"}</span><p>{message.text || "Thinking..."}</p></article>) : <p className="transcript-empty">Try saying, “I run a small shop. What would you recommend?”</p>}
      </div>
      <button className="end-call" ref={call.endButtonRef} onClick={call.handleEndCall}><Microphone end />End conversation</button>
      <p className="session-footnote">Your microphone stops when you end the conversation.</p>
    </section>
  </div>;
}

export default function Home() {
  const [inCall, setInCall] = useState(false);
  return <div className="site-shell">
    <header className="site-header"><Link className="brand" href="/" aria-label="Chanakya home"><span className="brand-mark" aria-hidden="true">m</span>chanakya<span className="brand-dot">.</span></Link><span className="header-note">A little clarity for your next big step.</span><span className="demo-badge">VOICE DEMO</span></header>
    <main>
      <section className="hero">
        <div className="hero-copy"><p className="eyebrow"><span className="small-dot" /> MEET YOUR PAYMENT PRODUCT ADVISOR</p><h1>Your business.<br />Your next move.<br /><em>Let’s talk.</em></h1><p className="hero-description">From a busy shop counter to your first online order, Chanakya helps you find the Paytm payment product that fits.</p><button className="start-call" onClick={() => setInCall(true)}><Microphone />Talk to Chanakya<span aria-hidden="true">↗</span></button><p className="button-note">No form. Just a conversation. <span>English · Hindi · Hinglish</span></p></div>
        <div className="hero-art" aria-label="Chanakya, your AI voice advisor"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><span className="art-tag tag-top">Made for your kind of business</span><div className="chanakya-sphere"><div className="waveform">{[19, 32, 49, 65, 40, 74, 54, 35, 20].map((height, i) => <span key={i} style={{ height, animationDelay: `${i * 0.12}s` }} />)}</div></div><div className="art-caption"><span className="small-dot" /><div><strong>A good place to start.</strong><p>Tell Chanakya what you need.</p></div></div><span className="art-tag tag-bottom">A voice. A question. A clearer choice.</span></div>
      </section>
      <section className="products" aria-labelledby="products-title"><div className="section-heading"><h2 id="products-title">One conversation. A few possibilities.</h2><p>Start with what your business needs.</p></div><div className="product-grid">{PRODUCTS.map(product => <article className="product-card" key={product.number}><div className="product-top"><span>{product.number}</span><span className="product-symbol" aria-hidden="true">{product.symbol}</span></div><h3>{product.name}</h3><p>{product.description}</p></article>)}</div></section>
    </main>
    <footer><span>chanakya. <span className="footer-muted">A conversation, then a decision.</span></span><p>Independent AI demo. Not affiliated with Paytm. Prices and availability are confirmed by Paytm.</p></footer>
    {inCall && <VoiceSession onClose={() => setInCall(false)} />}
  </div>;
}
