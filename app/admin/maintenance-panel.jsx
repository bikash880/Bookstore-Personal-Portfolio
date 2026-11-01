"use client";

import { useCallback, useEffect, useState } from "react";
import { CalendarClock, ExternalLink, Mail, Power, RefreshCw, Save, Sparkles } from "lucide-react";

const API = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/+$/, "");
const PRESETS = [
  "We're updating the bookstore with new titles. Thank you for your patience!",
  "We're making a few improvements. Everything will be back shortly.",
  "Scheduled maintenance in progress — back in a few minutes."
];

function toLocalInput(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

// An open book whose page turns while a golden pen writes a line across it.
function BookPenEmblem({ active }) {
  return <div className={`mta-emblem ${active ? "is-active" : ""}`} aria-hidden="true">
    <span className="mta-emblem-ring mta-emblem-ring-a"/>
    <span className="mta-emblem-ring mta-emblem-ring-b"/>
    <svg viewBox="0 0 120 120" className="mta-emblem-art">
      <defs>
        <linearGradient id="mta-gold" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#f4e2bd"/>
          <stop offset=".55" stopColor="#d4ac6a"/>
          <stop offset="1" stopColor="#a87d3f"/>
        </linearGradient>
        <linearGradient id="mta-page" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#fbf6ea"/>
          <stop offset="1" stopColor="#efe4cd"/>
        </linearGradient>
      </defs>
      <circle cx="60" cy="60" r="50" fill="#163024" stroke="url(#mta-gold)" strokeWidth="1.2"/>
      <g className="mta-book">
        <path d="M60 86c-8-5-17.5-6.6-27-5.6V45c9.5-1 19 .6 27 5.6z" fill="url(#mta-page)" stroke="#d4ac6a" strokeWidth="1.2" strokeLinejoin="round"/>
        <path d="M60 86c8-5 17.5-6.6 27-5.6V45c-9.5-1-19 .6-27 5.6z" fill="url(#mta-page)" stroke="#d4ac6a" strokeWidth="1.2" strokeLinejoin="round"/>
        <path d="M60 50.6V86" stroke="#c49a57" strokeWidth="1.4" strokeLinecap="round"/>
        <path className="mta-line mta-line-1" d="M38 56c5-.5 10 .2 15 2" stroke="#7f9a8a" strokeWidth="1.3" strokeLinecap="round" fill="none"/>
        <path className="mta-line mta-line-2" d="M38 63c5-.5 10 .2 15 2" stroke="#7f9a8a" strokeWidth="1.3" strokeLinecap="round" fill="none"/>
        <path className="mta-line mta-line-3" d="M38 70c5-.5 10 .2 15 2" stroke="#7f9a8a" strokeWidth="1.3" strokeLinecap="round" fill="none"/>
        <path className="mta-write" d="M66 61c3.5-1.5 7-1.8 11-.6 2 .6 3.2-.8 4.6-.2" stroke="#2f5242" strokeWidth="1.4" strokeLinecap="round" fill="none"/>
        <path className="mta-flip" d="M60 50.6c8-5 17.5-6.6 27-5.6v35.4c-9.5-1-19 .6-27 5.6z" fill="#fffaf0" stroke="#d4ac6a" strokeWidth="1" strokeLinejoin="round"/>
      </g>
      <g className="mta-pen">
        <path d="M84 26l7 7-17 26-6-1-1-6z" fill="url(#mta-gold)" stroke="#8a6431" strokeWidth=".8" strokeLinejoin="round"/>
        <path d="M68 52l6 6-6.6 3.4z" fill="#2a1e10"/>
        <path d="M85.5 27.5l5 5" stroke="#fff6df" strokeWidth="1" strokeLinecap="round" opacity=".7"/>
      </g>
      <circle className="mta-spark mta-spark-a" cx="34" cy="34" r="1.6" fill="#f4e2bd"/>
      <circle className="mta-spark mta-spark-b" cx="92" cy="80" r="1.3" fill="#f4e2bd"/>
      <circle className="mta-spark mta-spark-c" cx="28" cy="78" r="1" fill="#f4e2bd"/>
    </svg>
  </div>;
}

export default function MaintenancePanel({ api, canWrite, onChange, onNotice, onError }) {
  const [state, setState] = useState(null);
  const [message, setMessage] = useState("");
  const [until, setUntil] = useState("");
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(false);
  const [visitorView, setVisitorView] = useState(null);
  const [checkedAt, setCheckedAt] = useState(null);
  const [contactEmail, setContactEmail] = useState("");

  const refresh = useCallback(async ({ resetFields = false } = {}) => {
    setChecking(true);
    try {
      const [admin, publicStatus] = await Promise.all([
        api("/maintenance"),
        fetch(`${API}/api/site/status`, { cache: "no-store" }).then(response => response.ok ? response.json() : null).catch(() => null)
      ]);
      setState(admin.maintenance);
      if (resetFields) {
        setMessage(admin.maintenance.message || "");
        setUntil(toLocalInput(admin.maintenance.until));
      }
      setVisitorView(publicStatus ? (publicStatus.maintenance ? "maintenance" : "live") : "unknown");
      setCheckedAt(new Date());
      onChange(admin.maintenance.enabled);
    } catch (error) {
      onError(error.message);
    } finally {
      setChecking(false);
    }
  }, [api, onChange, onError]);

  useEffect(() => { refresh({ resetFields: true }); }, [refresh]);

  useEffect(() => {
    // The Contact button uses the same public address visitors see on the maintenance page.
    let active = true;
    (async () => {
      try {
        const settings = await api("/settings");
        let email = settings.settings?.contactEmail || "";
        if (!email) {
          const content = await api("/content");
          email = content.content?.find(item => item.key === "author-profile")?.value?.email || "";
        }
        if (active) setContactEmail(email);
      } catch {
        // Contact is optional; the button stays disabled without an address.
      }
    })();
    return () => { active = false; };
  }, [api]);

  async function save(enabled) {
    if (enabled && !state?.enabled && !window.confirm("Turn maintenance mode ON? Visitors will see the maintenance page and the store will stop taking orders until you turn it off.")) return;
    setBusy(true);
    try {
      const result = await api("/maintenance", {
        method: "PUT",
        body: JSON.stringify({ enabled, message: message.trim(), until: until ? new Date(until).toISOString() : null })
      });
      setState(result.maintenance);
      onChange(result.maintenance.enabled);
      setVisitorView(result.maintenance.enabled ? "maintenance" : "live");
      setCheckedAt(new Date());
      onNotice(enabled
        ? (state?.enabled ? "Maintenance details updated." : "Maintenance mode is ON. The public website now shows the maintenance page.")
        : "Maintenance mode is OFF. The website is back online for everyone.");
    } catch (error) {
      onError(error.message);
    } finally {
      setBusy(false);
    }
  }

  if (!state) return <div className="mta-wrap"><div className="mta-card mta-loading"><BookPenEmblem active/><p>Loading maintenance status…</p></div></div>;
  const on = state.enabled;
  const visitorText = visitorView === "maintenance" ? "Visitors currently see the maintenance page."
    : visitorView === "live" ? "Visitors currently see the live website."
    : "Visitor status could not be checked.";

  return <div className="mta-wrap">
    <section className={`mta-card ${on ? "is-on" : ""}`} aria-labelledby="mta-title">
      <div className="mta-glow mta-glow-a" aria-hidden="true"/>
      <div className="mta-glow mta-glow-b" aria-hidden="true"/>

      <BookPenEmblem active={on}/>

      <span className={`mta-pill ${on ? "on" : ""}`}><i aria-hidden="true"/>{on ? "Maintenance ON" : "Website live"}</span>
      <h2 id="mta-title">{on ? <>We&rsquo;re turning a <em>new page.</em></> : <>Your website is <em>open.</em></>}</h2>
      <p className="mta-lead">{on
        ? "Visitors see the maintenance page. The store, sign-in and checkout are paused, while the Admin Panel and payments already in progress keep working."
        : "Everyone can browse the portfolio and shop normally. Switch maintenance on before making large changes."}</p>

      <div className="mta-switch-row">
        <span className={!on ? "is-current" : ""}>Off</span>
        <button
          type="button" role="switch" aria-checked={on} aria-label="Maintenance mode"
          className={`mta-switch ${on ? "on" : ""}`} disabled={!canWrite || busy}
          onClick={() => save(!on)}
        ><span><Power size={18}/></span></button>
        <span className={on ? "is-current" : ""}>On</span>
      </div>

      <div className={`mta-progress ${on ? "is-running" : "is-live"}`} role="status" aria-live="polite">
        <div className="mta-progress-track"><span/></div>
        <small>{busy ? "Applying your change…" : visitorText}{checkedAt && <> · checked {checkedAt.toLocaleTimeString()}</>}</small>
      </div>

      <div className="mta-fields">
        <label className="mta-field mta-field-wide">
          <span>Message for visitors <em>{message.length}/500</em></span>
          <textarea rows={3} maxLength={500} value={message} disabled={!canWrite} onChange={event => setMessage(event.target.value)} placeholder="We're making a few improvements. Everything will be back shortly — thank you for your patience."/>
        </label>
        {canWrite && <div className="mta-presets" aria-label="Message suggestions">
          <Sparkles size={13} aria-hidden="true"/>
          {PRESETS.map(text => <button key={text} type="button" onClick={() => setMessage(text)}>{text.split(".")[0].replace(/!$/, "")}</button>)}
        </div>}
        <label className="mta-field">
          <span><CalendarClock size={13}/> Expected back at <em>optional</em></span>
          <input type="datetime-local" value={until} disabled={!canWrite} onChange={event => setUntil(event.target.value)}/>
        </label>
        <p className="mta-hint">{until ? "Visitors see a live countdown until this time." : "Leave empty to hide the countdown."}</p>
      </div>

      <div className="mta-actions">
        <button type="button" className="mta-btn mta-btn-ghost" onClick={() => refresh()} disabled={checking}>
          <RefreshCw size={15} className={checking ? "mta-spin" : ""}/> {checking ? "Checking…" : "Check again"}
        </button>
        <a
          className={`mta-btn mta-btn-ghost ${contactEmail ? "" : "is-disabled"}`}
          href={contactEmail ? `mailto:${contactEmail}?subject=${encodeURIComponent("Website maintenance")}` : undefined}
          aria-disabled={!contactEmail}
          title={contactEmail ? `Email ${contactEmail}` : "Add a contact email under Store & bank settings"}
        ><Mail size={15}/> Contact</a>
        <a className="mta-btn mta-btn-ghost" href="/maintenance" target="_blank" rel="noreferrer"><ExternalLink size={15}/> Preview</a>
        {canWrite && on && <button type="button" className="mta-btn mta-btn-ghost" disabled={busy} onClick={() => save(true)}><Save size={15}/> Save message</button>}
        {canWrite && <button type="button" className={`mta-btn mta-btn-primary ${on ? "" : "is-danger"}`} disabled={busy} onClick={() => save(!on)}>
          <Power size={15}/> {busy ? "Saving…" : on ? "Turn OFF — bring site back" : "Turn ON maintenance"}
        </button>}
      </div>

      <small className="mta-foot">{state.updatedAt ? `Last changed ${new Date(state.updatedAt).toLocaleString()}` : "Maintenance has never been switched on"}{contactEmail && <> · contact shown to visitors: {contactEmail}</>}</small>
    </section>
  </div>;
}
