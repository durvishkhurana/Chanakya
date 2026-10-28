"use client";

import Link from "next/link";
import { useState } from "react";

import "../../styles/app.css";
import { plexSans } from "./fonts";
import { CallIcon, MenuIcon, PeopleIcon, QueueIcon, ShopIcon } from "./icons";

const NAV = [
  { href: "/missions", label: "Mission control", Icon: QueueIcon },
  { href: "/call/demo", label: "Live call (recorded)", Icon: CallIcon },
  { href: "/missions?tab=handoffs", label: "Hand-offs", Icon: PeopleIcon, countKey: "handoffs" },
];

/** Tinted L-frame (sidebar and top bar) around one white sheet. */
export default function AppShell({ current, counts = {}, connected = false, topbar = null, children }) {
  const [open, setOpen] = useState(false);
  return <div className={`cx ${plexSans.variable}`}>
    <aside className={`sidebar${open ? " open" : ""}`} aria-label="Navigation">
      <Link className="brand" href="/" aria-label="Chanakya home"><span className="mark" aria-hidden="true">c</span>Chanakya</Link>
      <div className="scope"><b>North India merchants</b>Demo workspace · mock systems</div>
      {NAV.map(({ href, label, Icon, countKey }) => <Link key={href} href={href} className="nav-item" aria-current={current === href ? "page" : undefined} onClick={() => setOpen(false)}>
        <Icon />{label}{countKey && counts[countKey] > 0 && <span className="count">{counts[countKey]}</span>}
      </Link>)}
      <p className="group-label">Demo pages</p>
      <Link href="/demo/soundbox" className="nav-item" onClick={() => setOpen(false)}><ShopIcon />Mock product page</Link>
      <p className="bottom">Independent project, not affiliated with Paytm. Every business system here is a mock.</p>
    </aside>
    <div className="topbar">
      <button className="btn ghost menu-toggle" onClick={() => setOpen(!open)} aria-expanded={open} aria-label="Menu"><MenuIcon /></button>
      <span className={`live${connected ? " on" : ""}`} role="status"><i aria-hidden="true" />{connected ? "Live" : "Connecting"}</span>
      <span className="spacer" />
      {topbar}
    </div>
    <main className="sheet">{children}</main>
  </div>;
}
