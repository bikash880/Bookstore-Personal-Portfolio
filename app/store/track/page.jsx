"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, PackageSearch } from "lucide-react";
import { OBJECT_ID, formatDate, rememberedOrders, requestJson } from "../store-shared";

export default function TrackOrderPage() {
  const router = useRouter();
  const [orderId, setOrderId] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recent, setRecent] = useState([]);

  useEffect(() => { setRecent(rememberedOrders()); }, []);

  async function submit(event) {
    event.preventDefault();
    const id = orderId.trim().replace(/^#/, "");
    if (!OBJECT_ID.test(id)) {
      setError("Order references are 24 characters long, made of numbers and the letters a–f.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await requestJson("/api/orders/lookup", { method: "POST", body: JSON.stringify({ orderId: id, email: email.trim() }) });
      router.push(`/store/orders/${id}`);
    } catch (requestError) {
      setError(requestError.message);
      setBusy(false);
    }
  }

  return <section className="store-order-page store-track-page">
    <form className="store-panel store-lookup-card" onSubmit={submit}>
      <div className="store-order-check"><PackageSearch size={22}/></div>
      <span className="store-eyebrow">ORDER TRACKING</span>
      <h1>Where's my order?</h1>
      <p>Enter the order reference from your confirmation email and the email address you used at checkout.</p>
      <label className="store-field">Order reference<input autoComplete="off" spellCheck={false} required maxLength={30} placeholder="e.g. 6720f1c2a9b3e4d5f6a7b8c9" value={orderId} onChange={event => setOrderId(event.target.value)}/></label>
      <label className="store-field">Email address<input type="email" autoComplete="email" required maxLength={320} value={email} onChange={event => setEmail(event.target.value)}/></label>
      {error && <div className="store-alert" role="alert">{error}</div>}
      <button className="store-checkout-button" disabled={busy}>{busy ? "Looking it up…" : "Track order"} <ArrowRight size={15}/></button>
    </form>
    {recent.length > 0 && <div className="store-panel store-recent-orders">
      <h2>Orders from this device</h2>
      <ul>{recent.map(item => <li key={item.id}><Link href={`/store/orders/${item.id}`}><code>{item.id}</code><small>{formatDate(item.at)}</small><ArrowRight size={13}/></Link></li>)}</ul>
    </div>}
  </section>;
}
