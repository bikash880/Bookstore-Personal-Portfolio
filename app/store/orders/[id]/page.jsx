"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight, Check, CircleAlert, Clock3, Copy, Landmark, Mail, PackageCheck, RefreshCw,
  Truck, Wallet, X
} from "lucide-react";
import { useStore } from "../../store-shell";
import {
  OBJECT_ID, PAYMENT_LABELS, STATUS_LABELS, formatDate, formatNpr, rememberOrder, requestJson
} from "../../store-shared";

const steps = [
  ["pending", "Order placed", Clock3],
  ["paid", "Payment confirmed", Wallet],
  ["processing", "Being prepared", PackageCheck],
  ["shipped", "On its way", Truck],
  ["fulfilled", "Delivered", Check]
];
const stepIndex = Object.fromEntries(steps.map(([status], index) => [status, index]));

export default function OrderPage({ params }) {
  const { id } = use(params);
  const { settings, clearCart, notify } = useStore();
  const [result, setResult] = useState(null);
  const [state, setState] = useState("loading");
  const [error, setError] = useState("");
  const [returning, setReturning] = useState(false);
  const [placed, setPlaced] = useState(false);

  const load = useCallback(async () => {
    if (!OBJECT_ID.test(id)) {
      setState("missing");
      return null;
    }
    try {
      const latest = await requestJson(`/api/payments/nepal/track/${id}`);
      setResult(latest);
      setState("ready");
      setError("");
      return latest;
    } catch (requestError) {
      if (requestError.status === 404) setState("locked");
      else {
        setError(requestError.message);
        setState(current => current === "loading" ? "error" : current);
      }
      return null;
    }
  }, [id]);

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    setReturning(query.get("payment") === "return");
    setPlaced(query.get("placed") === "1");
    load();
  }, [load]);

  const order = result?.order;

  useEffect(() => {
    if (!order) return;
    rememberOrder(order.id);
    if (order.paymentStatus === "paid" && returning) clearCart();
  }, [order, returning, clearCart]);

  useEffect(() => {
    // Gateway payments can take a moment to settle after the provider redirects back.
    if (!order || order.paymentStatus !== "pending" || order.paymentProvider === "bank_transfer") return;
    let attempts = 0;
    const timer = window.setInterval(async () => {
      attempts += 1;
      const latest = await load();
      if (!latest || latest.order.paymentStatus !== "pending" || attempts >= 10) window.clearInterval(timer);
    }, 6000);
    return () => window.clearInterval(timer);
  }, [order?.id, order?.paymentStatus, order?.paymentProvider, load]);

  if (state === "loading") return <section className="store-order-page"><div className="store-empty">Loading your order…</div></section>;
  if (state === "missing") return <section className="store-order-page"><OrderNotice title="Order not found" text="Check the order reference and try again." /></section>;
  if (state === "locked") return <section className="store-order-page"><OrderUnlock id={id} onUnlocked={latest => { setResult(latest); setState("ready"); }}/></section>;
  if (state === "error") return <section className="store-order-page"><OrderNotice title="We couldn't load this order" text={error} action={<button className="store-checkout-button" onClick={load}>Try again</button>}/></section>;

  const cancelled = order.status === "cancelled";
  const current = stepIndex[order.status] ?? 0;
  const bankPending = order.paymentProvider === "bank_transfer" && order.paymentStatus === "pending" && !cancelled;
  const headline = cancelled ? "This order was cancelled."
    : order.paymentStatus === "pending" && order.paymentProvider !== "bank_transfer" ? "We're confirming your payment."
    : bankPending ? "Your order is reserved."
    : order.status === "fulfilled" ? "Your order was delivered."
    : "Thank you for your order.";

  return <section className="store-order-page">
    <div className="store-order-hero">
      <div className={`store-order-check ${cancelled ? "cancelled" : ""}`}>{cancelled ? <X size={23}/> : <Check size={23}/>}</div>
      <span className="store-eyebrow">{placed || returning ? "ORDER RECEIVED" : "ORDER STATUS"}</span>
      <h1>{headline}</h1>
      <p>Order reference <code>{order.id}</code>{order.createdAt && <> · placed {formatDate(order.createdAt, true)}</>}</p>
      {error && <div className="store-alert" role="alert">{error}</div>}
    </div>

    <div className="store-order-grid">
      <div>
        {!cancelled && <ol className="store-progress" aria-label="Order progress">
          {steps.map(([status, label, Icon], index) => <li key={status} className={index < current ? "done" : index === current ? "current" : ""}>
            <span><Icon size={15}/></span><small>{label}</small>
          </li>)}
        </ol>}
        {cancelled && <div className="store-alert store-alert-soft" role="status"><CircleAlert size={15}/> {order.paymentStatus === "refunded" ? "Your payment has been refunded." : order.paymentStatus === "paid" ? "Your payment will be refunded. We'll email you once it's issued." : "No payment was taken, and the reserved books were returned to the shelf."}</div>}

        {order.paymentStatus === "pending" && order.paymentProvider !== "bank_transfer" && !cancelled && <div className="store-notice store-notice-inline" role="status">
          <RefreshCw size={14} className="store-spin"/> Waiting for {PAYMENT_LABELS[order.paymentProvider] || "the provider"} to confirm your payment. This page updates automatically.
        </div>}

        {bankPending && <BankTransfer order={order} payment={result.payment} settings={settings} onReported={latest => { setResult(latest); notify("Thanks! We'll verify your transfer and confirm your order."); }}/>}

        {order.status === "shipped" && order.trackingNumber && <div className="store-tracking-card">
          <Truck size={18}/><span><strong>Shipped with {order.carrier || "our courier"}</strong>Tracking number <code>{order.trackingNumber}</code></span>
        </div>}

        <div className="store-panel">
          <h2>Order history</h2>
          <ol className="store-history">{[...(order.history || [])].reverse().map((entry, index) => <li key={`${entry.at}-${index}`}>
            <span className={`store-history-dot ${entry.status}`}/>
            <div><strong>{STATUS_LABELS[entry.status] || entry.status}</strong>{entry.note && <p>{entry.note}</p>}<small>{formatDate(entry.at, true)}</small></div>
          </li>)}</ol>
        </div>
      </div>

      <aside className="store-panel store-order-summary">
        <h2>Summary</h2>
        <ul className="store-summary-items">{(order.items || []).map((item, index) => <li key={`${item.book}-${index}`}>
          <span><Link href={`/store/books/${item.book}`}><strong>{item.title}</strong></Link><small>Qty {item.quantity}{item.unitPrice ? ` × ${formatNpr(item.unitPrice)}` : ""}</small></span>
          {item.unitPrice ? <b>{formatNpr(item.unitPrice * item.quantity)}</b> : null}
        </li>)}</ul>
        <div className="store-summary-row store-summary-total"><span>Total</span><strong>{formatNpr(order.total)}</strong></div>
        <dl className="store-order-facts">
          <div><dt>Status</dt><dd>{STATUS_LABELS[order.status] || order.status}</dd></div>
          <div><dt>Payment</dt><dd>{PAYMENT_LABELS[order.paymentProvider] || order.paymentProvider} · <span className="store-capitalize">{order.paymentStatus}</span></dd></div>
          {order.customerName && <div><dt>Name</dt><dd>{order.customerName}</dd></div>}
        </dl>
        <button className="store-details-button store-full" onClick={load}><RefreshCw size={13}/> Refresh status</button>
        {settings?.contactEmail && <a className="store-link-button" href={`mailto:${settings.contactEmail}?subject=${encodeURIComponent(`Order ${order.id}`)}`}><Mail size={13}/> Questions? Email the bookstore</a>}
        <Link className="store-checkout-button" href="/store">Continue browsing <ArrowRight size={15}/></Link>
      </aside>
    </div>
  </section>;
}

function BankTransfer({ order, payment, settings, onReported }) {
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const reported = payment?.customerReportedAt;

  async function copy(value) {
    try { await navigator.clipboard.writeText(value); } catch { /* clipboard blocked; the value stays visible */ }
  }

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onReported(await requestJson(`/api/payments/nepal/track/${order.id}/bank-reference`, {
        method: "POST",
        body: JSON.stringify({ reference: reference.trim(), note: note.trim() })
      }));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  return <div className="store-bank-instructions store-bank-card">
    <strong><Landmark size={17}/> Complete your bank transfer</strong>
    {settings?.bankTransferEnabled ? <>
      <dl>
        <div><dt>Amount</dt><dd><b>{formatNpr(order.total)}</b></dd></div>
        <div><dt>Bank</dt><dd>{settings.bankName}{settings.bankBranch ? ` · ${settings.bankBranch}` : ""}</dd></div>
        <div><dt>Account name</dt><dd>{settings.bankAccountName}</dd></div>
        <div><dt>Account number</dt><dd><b>{settings.bankAccountNumber}</b><button type="button" onClick={() => copy(settings.bankAccountNumber)} aria-label="Copy account number"><Copy size={12}/></button></dd></div>
        <div><dt>Remarks / reference</dt><dd><b>{order.id}</b><button type="button" onClick={() => copy(order.id)} aria-label="Copy order reference"><Copy size={12}/></button></dd></div>
      </dl>
      <p>{settings.bankInstructions || "Use your order reference as the transfer remark. Your order is confirmed once we verify the transfer on our bank statement."}</p>
    </> : <p>Bank details are being updated. Please contact the bookstore for transfer instructions.</p>}
    {reported ? <small><Check size={12}/> You reported this transfer on {formatDate(reported, true)}. We'll confirm it after checking our bank statement.</small>
      : <form className="store-bank-reference" onSubmit={submit}>
        <span>Already paid? Tell us the transaction reference so we can verify it faster.</span>
        <input aria-label="Bank transaction reference" placeholder="Transaction / voucher reference" required minLength={3} maxLength={120} value={reference} onChange={event => setReference(event.target.value)}/>
        <input aria-label="Note (optional)" placeholder="Note (optional) — e.g. paid from Global IME" maxLength={300} value={note} onChange={event => setNote(event.target.value)}/>
        {error && <div className="store-alert" role="alert">{error}</div>}
        <button className="store-add-button" disabled={busy}>{busy ? "Sending…" : "I've made the transfer"}</button>
      </form>}
  </div>;
}

function OrderUnlock({ id, onUnlocked }) {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onUnlocked(await requestJson("/api/orders/lookup", { method: "POST", body: JSON.stringify({ orderId: id, email: email.trim() }) }));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }
  return <form className="store-panel store-lookup-card" onSubmit={submit}>
    <span className="store-eyebrow">ORDER STATUS</span>
    <h1>Confirm it's your order</h1>
    <p>For your privacy, enter the email address used at checkout for order <code>{id}</code>.</p>
    <label className="store-field">Email address<input type="email" autoComplete="email" required maxLength={320} value={email} onChange={event => setEmail(event.target.value)}/></label>
    {error && <div className="store-alert" role="alert">{error}</div>}
    <button className="store-checkout-button" disabled={busy}>{busy ? "Checking…" : "View order"} <ArrowRight size={15}/></button>
  </form>;
}

function OrderNotice({ title, text, action }) {
  return <div className="store-panel store-lookup-card">
    <span className="store-eyebrow">ORDER STATUS</span>
    <h1>{title}</h1>
    <p>{text}</p>
    {action || <Link className="store-checkout-button" href="/store/track">Look up an order <ArrowRight size={15}/></Link>}
  </div>;
}
