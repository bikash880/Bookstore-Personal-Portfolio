"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight, Check, KeyRound, LogOut, MailCheck, Package, ShieldCheck, UserRound
} from "lucide-react";
import { useStore } from "../store-shell";
import BrandMark from "../../brand-mark";
import { PAYMENT_LABELS, STATUS_LABELS, formatDate, formatNpr, requestJson } from "../store-shared";

export default function AccountPage() {
  const { account, accountReady, setAccount, logout, notify } = useStore();
  if (!accountReady) return <section className="store-order-page"><div className="store-empty">Loading your account…</div></section>;
  return account
    ? <AccountDashboard account={account} setAccount={setAccount} logout={logout} notify={notify}/>
    : <AuthPanel onSignedIn={setAccount}/>;
}

function Field({ label, ...props }) {
  return <label className="store-field">{label}<input {...props}/></label>;
}

function AuthPanel({ onSignedIn }) {
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ name: "", email: "", password: "", code: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const update = key => event => setForm(current => ({ ...current, [key]: key === "code" ? event.target.value.replace(/\D/g, "").slice(0, 6) : event.target.value }));

  function go(next) {
    setMode(next);
    setError("");
    setNotice("");
  }

  async function run(action) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (requestError) {
      setError(requestError.message);
      if (requestError.status === 403 && /verify/i.test(requestError.message)) setMode("verify");
    } finally {
      setBusy(false);
    }
  }

  const email = form.email.trim();
  const submit = {
    login: () => run(async () => {
      const result = await requestJson("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password: form.password }) });
      onSignedIn(result.user);
    }),
    register: () => run(async () => {
      const result = await requestJson("/api/auth/register", { method: "POST", body: JSON.stringify({ name: form.name.trim(), email, password: form.password }) });
      setMode("verify");
      setNotice(result.message);
    }),
    verify: () => run(async () => {
      const result = await requestJson("/api/auth/verify-email", { method: "POST", body: JSON.stringify({ email, code: form.code }) });
      onSignedIn(result.user);
    }),
    forgot: () => run(async () => {
      const result = await requestJson("/api/auth/password/request", { method: "POST", body: JSON.stringify({ email }) });
      setMode("reset");
      setNotice(result.message);
    }),
    reset: () => run(async () => {
      const result = await requestJson("/api/auth/password/reset", { method: "POST", body: JSON.stringify({ email, code: form.code, password: form.password }) });
      setMode("login");
      setForm(current => ({ ...current, password: "", code: "" }));
      setNotice(result.message);
    })
  };

  async function resend() {
    await run(async () => {
      const result = await requestJson("/api/auth/resend-verification", { method: "POST", body: JSON.stringify({ email }) });
      setNotice(result.message);
    });
  }

  const titles = {
    login: ["Welcome back", "Sign in to see your orders and check out faster."],
    register: ["Create your account", "Keep every order in one place and track deliveries anytime."],
    verify: ["Check your email", `Enter the 6-digit code we sent to ${email || "your email address"}.`],
    forgot: ["Forgot your password?", "We'll email you a code to choose a new one."],
    reset: ["Choose a new password", "Enter the code from your email and your new password."]
  };

  return <section className="store-order-page store-auth-page">
    <div className="store-auth-layout">
      <aside className="store-auth-aside">
        <BrandMark size={58}/>
        <h2>Your reading life, in one place.</h2>
        <ul>
          <li><Package size={16}/> Track every order from payment to delivery</li>
          <li><UserRound size={16}/> Save your delivery details for faster checkout</li>
          <li><ShieldCheck size={16}/> Payments verified securely with eSewa, Khalti and your bank</li>
        </ul>
        <p>Prefer not to sign up? You can still <Link href="/store">check out as a guest</Link> and <Link href="/store/track">track an order</Link> with its reference.</p>
      </aside>
      <form className="store-panel store-auth-card" onSubmit={event => { event.preventDefault(); submit[mode](); }}>
        {(mode === "login" || mode === "register") && <div className="store-auth-tabs" role="tablist">
          <button type="button" role="tab" aria-selected={mode === "login"} className={mode === "login" ? "active" : ""} onClick={() => go("login")}>Sign in</button>
          <button type="button" role="tab" aria-selected={mode === "register"} className={mode === "register" ? "active" : ""} onClick={() => go("register")}>Create account</button>
        </div>}
        <span className="store-eyebrow">MY ACCOUNT</span>
        <h1>{titles[mode][0]}</h1>
        <p>{titles[mode][1]}</p>
        {notice && <div className="store-notice store-notice-inline" role="status"><MailCheck size={15}/> {notice}</div>}

        {mode === "register" && <Field label="Full name" autoComplete="name" required maxLength={160} value={form.name} onChange={update("name")}/>}
        {mode !== "verify" && mode !== "reset" && <Field label="Email address" type="email" autoComplete="email" required maxLength={320} value={form.email} onChange={update("email")}/>}
        {(mode === "verify" || mode === "reset") && <Field label={mode === "verify" ? "Verification code" : "Reset code"} inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" required value={form.code} onChange={update("code")}/>}
        {(mode === "login" || mode === "register" || mode === "reset") && <Field
          label={mode === "reset" ? "New password" : "Password"} type="password" required
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          minLength={mode === "login" ? 1 : 12} maxLength={128} value={form.password} onChange={update("password")}/>}
        {(mode === "register" || mode === "reset") && <small className="store-hint">Use at least 12 characters.</small>}

        {error && <div className="store-alert" role="alert">{error}</div>}
        <button className="store-checkout-button" disabled={busy}>
          {busy ? "Please wait…" : { login: "Sign in", register: "Create account", verify: "Verify email", forgot: "Send reset code", reset: "Reset password" }[mode]} <ArrowRight size={15}/>
        </button>

        <div className="store-auth-links">
          {mode === "login" && <button type="button" className="store-link-button" onClick={() => go("forgot")}>Forgot password?</button>}
          {mode === "verify" && <button type="button" className="store-link-button" disabled={busy} onClick={resend}>Send a new code</button>}
          {mode !== "login" && mode !== "register" && <button type="button" className="store-link-button" onClick={() => go("login")}>Back to sign in</button>}
        </div>
      </form>
    </div>
  </section>;
}

function AccountDashboard({ account, setAccount, logout, notify }) {
  const [tab, setTab] = useState("orders");
  const [orders, setOrders] = useState(null);
  const [error, setError] = useState("");

  const loadOrders = useCallback(async () => {
    try {
      setOrders((await requestJson("/api/account/orders")).orders || []);
    } catch (requestError) {
      if (requestError.status === 401) setAccount(null);
      else setError(requestError.message);
    }
  }, [setAccount]);
  useEffect(() => { loadOrders(); }, [loadOrders]);

  const active = (orders || []).filter(order => !["fulfilled", "cancelled"].includes(order.status)).length;
  return <section className="store-order-page store-account">
    <div className="store-account-head">
      <div className="store-account-avatar" aria-hidden="true">{(account.name || account.email).slice(0, 1).toUpperCase()}</div>
      <div>
        <span className="store-eyebrow">MY ACCOUNT</span>
        <h1>Hello, {(account.name || "reader").split(" ")[0]}.</h1>
        <p>{account.email}{account.createdAt ? ` · member since ${formatDate(account.createdAt)}` : ""}</p>
      </div>
      <button className="store-details-button store-signout" onClick={logout}><LogOut size={14}/> Sign out</button>
    </div>
    <div className="store-account-stats">
      <div><strong>{orders ? orders.length : "–"}</strong><span>Orders</span></div>
      <div><strong>{orders ? active : "–"}</strong><span>In progress</span></div>
      <div><strong>{orders ? formatNpr(orders.filter(order => order.paymentStatus === "paid" && order.status !== "cancelled").reduce((sum, order) => sum + order.total, 0)) : "–"}</strong><span>Spent</span></div>
    </div>
    <div className="store-auth-tabs store-account-tabs" role="tablist">
      {[["orders", "Orders", Package], ["profile", "Delivery details", UserRound], ["security", "Password", KeyRound]].map(([key, label, Icon]) => <button key={key} type="button" role="tab" aria-selected={tab === key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}><Icon size={14}/> {label}</button>)}
    </div>
    {error && <div className="store-alert" role="alert">{error}</div>}
    {tab === "orders" && (!orders ? <div className="store-empty">Loading your orders…</div>
      : orders.length ? <ul className="store-account-orders">{orders.map(order => <li key={order.id}>
        <Link href={`/store/orders/${order.id}`}>
          <div className="store-account-order-main">
            <span className={`store-status-pill ${order.status}`}>{STATUS_LABELS[order.status] || order.status}</span>
            <strong>{order.items.map(item => `${item.title}${item.quantity > 1 ? ` × ${item.quantity}` : ""}`).join(", ")}</strong>
            <small>Placed {formatDate(order.createdAt, true)} · {PAYMENT_LABELS[order.paymentProvider] || order.paymentProvider} · <code>…{order.id.slice(-8)}</code></small>
          </div>
          <b>{formatNpr(order.total)}</b>
          <ArrowRight size={16}/>
        </Link>
      </li>)}</ul>
      : <div className="store-empty store-account-empty"><span>You haven't ordered anything yet.</span><Link className="store-checkout-button" href="/store">Browse the bookshelf <ArrowRight size={15}/></Link></div>)}
    {tab === "profile" && <ProfileForm account={account} setAccount={setAccount} notify={notify}/>}
    {tab === "security" && <PasswordForm notify={notify}/>}
  </section>;
}

function ProfileForm({ account, setAccount, notify }) {
  const [form, setForm] = useState({ name: account.name || "", phone: account.phone || "", address: account.address || "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await requestJson("/api/account/profile", { method: "PATCH", body: JSON.stringify(form) });
      setAccount(result.user);
      notify("Your delivery details were saved.");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }
  return <form className="store-panel store-account-form" onSubmit={submit}>
    <h2>Delivery details</h2>
    <p>Used to fill in checkout automatically. Your email address is fixed to your verified account email.</p>
    <div className="store-checkout-fields">
      <label>Full name<input required maxLength={160} autoComplete="name" value={form.name} onChange={event => setForm({ ...form, name: event.target.value })}/></label>
      <label>Phone<input type="tel" maxLength={32} autoComplete="tel" value={form.phone} onChange={event => setForm({ ...form, phone: event.target.value })} placeholder="98XXXXXXXX"/></label>
      <label className="store-field-wide">Delivery address<textarea rows={3} maxLength={500} autoComplete="street-address" value={form.address} onChange={event => setForm({ ...form, address: event.target.value })} placeholder="Street, tole, municipality, district"/></label>
    </div>
    {error && <div className="store-alert" role="alert">{error}</div>}
    <button className="store-add-button store-inline-button" disabled={busy}><Check size={14}/> {busy ? "Saving…" : "Save details"}</button>
  </form>;
}

function PasswordForm({ notify }) {
  const [form, setForm] = useState({ currentPassword: "", newPassword: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await requestJson("/api/account/password", { method: "POST", body: JSON.stringify(form) });
      setForm({ currentPassword: "", newPassword: "" });
      notify(result.message);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }
  return <form className="store-panel store-account-form" onSubmit={submit}>
    <h2>Change password</h2>
    <p>Changing your password signs you out on your other devices.</p>
    <div className="store-checkout-fields">
      <label>Current password<input type="password" required autoComplete="current-password" maxLength={128} value={form.currentPassword} onChange={event => setForm({ ...form, currentPassword: event.target.value })}/></label>
      <label>New password<input type="password" required minLength={12} maxLength={128} autoComplete="new-password" value={form.newPassword} onChange={event => setForm({ ...form, newPassword: event.target.value })}/></label>
    </div>
    {error && <div className="store-alert" role="alert">{error}</div>}
    <button className="store-add-button store-inline-button" disabled={busy}><KeyRound size={14}/> {busy ? "Saving…" : "Update password"}</button>
  </form>;
}
