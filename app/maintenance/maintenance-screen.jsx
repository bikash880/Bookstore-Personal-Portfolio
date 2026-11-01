"use client";

import { useEffect, useState } from "react";
import { Mail, RefreshCw } from "lucide-react";
import BrandMark from "../brand-mark";

const apiBase = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/+$/, "");
const POLL_MS = 15_000;

function remaining(until) {
  const ms = new Date(until).getTime() - Date.now();
  if (!Number.isFinite(ms) || ms <= 0) return null;
  const total = Math.floor(ms / 1000);
  return { days: Math.floor(total / 86400), hours: Math.floor(total / 3600) % 24, minutes: Math.floor(total / 60) % 60, seconds: total % 60 };
}

export default function MaintenanceScreen({ initial }) {
  const [status, setStatus] = useState(initial);
  const [left, setLeft] = useState(null);
  const [checking, setChecking] = useState(false);

  async function check() {
    setChecking(true);
    try {
      const response = await fetch(`${apiBase}/api/site/status`, { cache: "no-store" });
      const result = response.ok ? await response.json() : null;
      if (result && !result.maintenance) {
        // Maintenance is over: reload the address the visitor asked for (or the home page).
        if (window.location.pathname === "/maintenance") window.location.replace("/");
        else window.location.reload();
        return;
      }
      if (result) setStatus(result);
    } catch {
      // Network hiccup; try again on the next poll.
    } finally {
      setChecking(false);
    }
  }

  useEffect(() => {
    if (initial && initial.maintenance === false) check();
    const timer = window.setInterval(check, POLL_MS);
    function onVisible() { if (!document.hidden) check(); }
    document.addEventListener("visibilitychange", onVisible);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!status?.until) { setLeft(null); return; }
    const tick = () => setLeft(remaining(status.until));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [status?.until]);

  const name = status?.authorName || "The bookshop";
  const message = status?.message || "We're making a few improvements to give you a better reading experience. Everything will be back shortly — thank you for your patience.";

  return <main className="mt-page">
    <div className="mt-glow mt-glow-a" aria-hidden="true"/>
    <div className="mt-glow mt-glow-b" aria-hidden="true"/>
    <section className="mt-card" aria-live="polite">
      <div className="mt-emblem" aria-hidden="true">
        <span className="mt-ring mt-ring-a"/><span className="mt-ring mt-ring-b"/>
        <BrandMark size={88}/>
      </div>
      <span className="mt-eyebrow">Scheduled maintenance</span>
      <h1><span className="mt-emoji" role="img" aria-label="Under repair">🛠️</span> Server is <em>down</em></h1>
      <p className="mt-message">{message}</p>
      {left && <div className="mt-countdown" role="timer" aria-label="Expected back in">
        {(left.days ? [["days", left.days]] : []).concat([["hours", left.hours], ["minutes", left.minutes], ["seconds", left.seconds]]).map(([label, value]) => <div key={label}><strong>{String(value).padStart(2, "0")}</strong><span>{label}</span></div>)}
      </div>}
      <div className="mt-progress" aria-hidden="true"><span/></div>
      <div className="mt-actions">
        <button className="mt-button" onClick={check} disabled={checking}><RefreshCw size={15} className={checking ? "mt-spin" : ""}/> {checking ? "Checking…" : "Check again"}</button>
        {status?.contactEmail && <a className="mt-link" href={`mailto:${status.contactEmail}`}><Mail size={15}/> {status.contactEmail}</a>}
      </div>
      <small className="mt-foot">This page refreshes automatically when we&rsquo;re back. — {name}</small>
    </section>
  </main>;
}
