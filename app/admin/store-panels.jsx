"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, ArrowRight, Bell, Check, CheckCheck, ClipboardList, CreditCard,
  Download, Eye, Landmark, Minus, Package, Pencil, Plus, Search, ShoppingCart, Tag, Trash2,
  TrendingDown, TrendingUp, Truck, Users, X
} from "lucide-react";

export const PAYMENT_LABELS = { esewa: "eSewa", khalti: "Khalti", bank_transfer: "Bank transfer" };
const ORDER_LABELS = {
  pending: "Awaiting payment", paid: "Paid", processing: "Processing",
  shipped: "Shipped", fulfilled: "Delivered", cancelled: "Cancelled"
};
const NEXT_STEPS = {
  pending: [["cancelled", "Cancel order"]],
  paid: [["processing", "Start preparing"], ["cancelled", "Cancel & refund"]],
  processing: [["shipped", "Mark shipped"], ["fulfilled", "Mark delivered"], ["cancelled", "Cancel & refund"]],
  shipped: [["fulfilled", "Mark delivered"]]
};

export function formatNpr(value) {
  return `NPR ${Number(value || 0).toLocaleString("en-NP", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatShortNpr(value) {
  const amount = Number(value || 0);
  if (amount >= 100000) return `${(amount / 100000).toFixed(amount >= 1000000 ? 0 : 1)}L`;
  if (amount >= 1000) return `${(amount / 1000).toFixed(amount >= 10000 ? 0 : 1)}k`;
  return String(Math.round(amount));
}

function when(value, withTime = true) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : withTime ? date.toLocaleString() : date.toLocaleDateString();
}

function timeAgo(value) {
  const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function customerOf(order) {
  const record = order?.customerRecord && typeof order.customerRecord === "object" ? order.customerRecord : {};
  return { ...record, ...(order?.customer || {}) };
}

export function StatusBadge({ value, label }) {
  const normalized = String(value || "").toLowerCase();
  const tone = ["paid", "completed", "fulfilled", "published", "active", "approved"].includes(normalized) ? "good"
    : ["processing", "shipped"].includes(normalized) ? "info"
    : ["cancelled", "failed", "rejected", "refunded", "due"].includes(normalized) ? "bad"
    : ["pending", "initiated", "draft"].includes(normalized) ? "pending" : "";
  return <span className={`admin-status ${tone}`}>{label || ORDER_LABELS[normalized] || value || "—"}</span>;
}

function Modal({ title, eyebrow, onClose, children, wide = false }) {
  useEffect(() => {
    function onKey(event) { if (event.key === "Escape") onClose(); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return <div className="admin-dialog-backdrop" role="presentation" onMouseDown={event => event.target === event.currentTarget && onClose()}>
    <section className={`admin-dialog ${wide ? "admin-dialog-wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
      <div className="admin-dialog-head"><div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h2 className="serif">{title}</h2></div><button type="button" onClick={onClose} aria-label="Close"><X size={18}/></button></div>
      {children}
    </section>
  </div>;
}

/* ------------------------------ Notifications ------------------------------ */

const notificationIcons = { order: ShoppingCart, payment: CreditCard, bank_reference: Landmark, low_stock: AlertTriangle };

export function NotificationBell({ api, onOpenOrder, onNavigate }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState({ notifications: [], unread: 0 });
  const lastUnread = useRef(null);
  const wrapper = useRef(null);

  const load = useCallback(async () => {
    try {
      const result = await api("/notifications");
      setData(result);
      if (lastUnread.current !== null && result.unread > lastUnread.current && document.hidden) {
        document.title = `(${result.unread}) Admin Panel`;
      }
      lastUnread.current = result.unread;
    } catch {
      // Notifications are a convenience; the panel keeps working if a poll fails.
    }
  }, [api]);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 45000);
    function onVisible() { if (!document.hidden) { document.title = "Admin Panel"; load(); } }
    document.addEventListener("visibilitychange", onVisible);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [load]);

  useEffect(() => {
    if (!open) return;
    function close(event) { if (!wrapper.current?.contains(event.target)) setOpen(false); }
    function onKey(event) { if (event.key === "Escape") setOpen(false); }
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", onKey); };
  }, [open]);

  async function markRead(ids = []) {
    try {
      await api("/notifications/read", { method: "POST", body: JSON.stringify({ ids }) });
      await load();
    } catch {
      // Leave the unread state as-is; the next poll will retry.
    }
  }

  function openItem(item) {
    if (!item.read) markRead([item._id]);
    setOpen(false);
    if (item.order) onOpenOrder(item.order);
    else if (item.kind === "low_stock") onNavigate("store-books");
  }

  return <div className="admin-bell" ref={wrapper}>
    <button className="admin-bell-button" onClick={() => setOpen(!open)} aria-expanded={open} aria-label={`Notifications, ${data.unread} unread`}>
      <Bell size={17}/>{data.unread > 0 && <b>{data.unread > 99 ? "99+" : data.unread}</b>}
    </button>
    {open && <div className="admin-bell-menu" role="menu">
      <div className="admin-bell-head"><strong>Notifications</strong>{data.unread > 0 && <button onClick={() => markRead()}><CheckCheck size={13}/> Mark all read</button>}</div>
      <div className="admin-bell-list">{data.notifications.length ? data.notifications.map(item => {
        const Icon = notificationIcons[item.kind] || Bell;
        return <button key={item._id} role="menuitem" className={`admin-bell-item ${item.read ? "" : "unread"} ${item.kind}`} onClick={() => openItem(item)}>
          <span className="admin-bell-icon"><Icon size={14}/></span>
          <span><strong>{item.title}</strong><small>{item.message}</small><em>{timeAgo(item.createdAt)}</em></span>
        </button>;
      }) : <div className="admin-empty">No notifications yet. New orders and payments will appear here.</div>}</div>
    </div>}
  </div>;
}

/* ------------------------------ Store dashboard ------------------------------ */

export function StoreDashboard({ api, refreshKey, onNavigate, onOpenOrder, onError }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let active = true;
    Promise.all([api("/store/analytics"), api("/orders"), api("/notifications")])
      .then(([analytics, orders, notifications]) => { if (active) setData({ analytics, orders: orders.orders || [], notifications: notifications.notifications || [] }); })
      .catch(error => onError(error.message));
    return () => { active = false; };
  }, [api, refreshKey, onError]);

  if (!data) return <div className="admin-empty">Loading the bookstore dashboard…</div>;
  const { analytics: a, orders, notifications } = data;
  const change = a.revenuePrevious30Npr > 0 ? ((a.revenueLast30Npr - a.revenuePrevious30Npr) / a.revenuePrevious30Npr) * 100 : null;
  const tasks = [
    [a.toFulfil, a.toFulfil === 1 ? "order to prepare or ship" : "orders to prepare or ship", "store-orders", Package],
    [a.awaitingBankConfirmation, a.awaitingBankConfirmation === 1 ? "bank transfer to verify" : "bank transfers to verify", "store-payments", Landmark],
    [a.refundsDue, a.refundsDue === 1 ? "refund to issue" : "refunds to issue", "store-orders", CreditCard],
    [a.lowStock, a.lowStock === 1 ? "book low on stock" : "books low on stock", "store-books", AlertTriangle],
    [a.pendingOrders, a.pendingOrders === 1 ? "order awaiting payment" : "orders awaiting payment", "store-orders", ClipboardList]
  ].filter(([count]) => count > 0);

  return <>
    <div className="admin-stat-grid admin-kpi-grid">
      <article className="admin-stat admin-kpi">
        <span>Revenue · last 30 days</span>
        <strong>{formatNpr(a.revenueLast30Npr)}</strong>
        <small className={change === null ? "" : change >= 0 ? "up" : "down"}>
          {change === null ? "No sales in the previous 30 days" : <>{change >= 0 ? <TrendingUp size={12}/> : <TrendingDown size={12}/>} {Math.abs(change).toFixed(0)}% vs previous 30 days</>}
        </small>
      </article>
      <article className="admin-stat admin-kpi"><span>Confirmed sales · all time</span><strong>{formatNpr(a.revenueNpr)}</strong><small>{a.paidOrders} paid {a.paidOrders === 1 ? "order" : "orders"} · avg {formatNpr(a.averageOrderNpr)}</small></article>
      <article className="admin-stat admin-kpi"><span>Orders to fulfil</span><strong>{a.toFulfil}</strong><small>Paid or being prepared</small></article>
      <article className="admin-stat admin-kpi"><span>Customers</span><strong>{a.customers}</strong><small>{a.orders} {a.orders === 1 ? "order" : "orders"} placed in total</small></article>
    </div>

    <div className="admin-store-columns">
      <section className="admin-panel">
        <div className="admin-panel-heading"><div><h2>Needs your attention</h2><span>Work waiting in the bookstore</span></div></div>
        {tasks.length ? <ul className="admin-task-list">{tasks.map(([count, label, target, Icon]) => <li key={label}>
          <button onClick={() => onNavigate(target)}><span className="admin-task-icon"><Icon size={15}/></span><strong>{count}</strong><span>{label}</span><ArrowRight size={14}/></button>
        </li>)}</ul> : <div className="admin-empty"><Check size={18}/><br/>All caught up — nothing needs attention right now.</div>}
      </section>
      <section className="admin-panel">
        <div className="admin-panel-heading"><div><h2>Recent activity</h2><span>Orders, payments and stock alerts</span></div></div>
        {notifications.length ? <ul className="admin-activity">{notifications.slice(0, 6).map(item => {
          const Icon = notificationIcons[item.kind] || Bell;
          return <li key={item._id} className={item.kind}><span className="admin-bell-icon"><Icon size={13}/></span><div><strong>{item.title}</strong><small>{item.message}</small></div><em>{timeAgo(item.createdAt)}</em></li>;
        })}</ul> : <div className="admin-empty">Activity will appear here after your first order.</div>}
      </section>
    </div>

    <section className="admin-panel">
      <div className="admin-panel-heading"><div><h2>Daily sales</h2><span>Confirmed revenue for the last 30 days · NPR</span></div><button className="admin-link" onClick={() => onNavigate("sales")}>Full report <ArrowRight size={13}/></button></div>
      <BarChart rows={(a.salesByDay || []).map(row => ({ key: row.day, label: new Date(`${row.day}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" }), value: row.revenueNpr, detail: `${row.orders} order${row.orders === 1 ? "" : "s"}` }))} sparseLabels emptyText="Confirmed sales from the last 30 days will appear here."/>
    </section>

    <section className="admin-panel">
      <div className="admin-panel-heading"><div><h2>Latest orders</h2><span>The five most recent orders</span></div><button className="admin-link" onClick={() => onNavigate("store-orders")}>All orders <ArrowRight size={13}/></button></div>
      {orders.length ? <div className="admin-table-scroll"><table className="admin-table"><thead><tr><th>Order</th><th>Customer</th><th>Total</th><th>Payment</th><th>Status</th></tr></thead><tbody>
        {orders.slice(0, 5).map(order => <tr key={order._id} className="admin-clickable" onClick={() => onOpenOrder(order._id)}>
          <td data-label="Order"><code>…{order._id.slice(-8)}</code><small>{when(order.createdAt)}</small></td>
          <td data-label="Customer">{customerOf(order).name || "—"}</td>
          <td data-label="Total">{formatNpr(order.total)}</td>
          <td data-label="Payment">{PAYMENT_LABELS[order.paymentProvider] || order.paymentProvider}<small>{order.paymentStatus}</small></td>
          <td data-label="Status"><StatusBadge value={order.status}/></td>
        </tr>)}
      </tbody></table></div> : <div className="admin-empty">No orders yet.</div>}
    </section>
  </>;
}

/* ------------------------------ Charts ------------------------------ */

function BarChart({ rows, sparseLabels = false, emptyText }) {
  const [showTable, setShowTable] = useState(false);
  const [active, setActive] = useState(null);
  const peak = Math.max(0, ...rows.map(row => Number(row.value) || 0));
  if (!rows.length || peak === 0) return <div className="admin-empty">{emptyText}</div>;
  const ticks = [peak, peak / 2, 0];
  return <div className="admin-chart">
    <div className="admin-chart-tools"><button className="admin-link" onClick={() => setShowTable(!showTable)}>{showTable ? "Show chart" : "Show as table"}</button></div>
    {showTable ? <div className="admin-table-scroll"><table className="admin-table"><thead><tr><th>Period</th><th>Revenue</th><th>Detail</th></tr></thead><tbody>
      {rows.map(row => <tr key={row.key}><td data-label="Period">{row.label}</td><td data-label="Revenue">{formatNpr(row.value)}</td><td data-label="Detail">{row.detail}</td></tr>)}
    </tbody></table></div> : <div className="admin-chart-plot">
      <div className="admin-chart-axis" aria-hidden="true">{ticks.map(tick => <span key={tick}>{formatShortNpr(tick)}</span>)}</div>
      <div className="admin-chart-bars" role="list" aria-label="Revenue chart" style={{ gridTemplateColumns: `repeat(${rows.length}, minmax(0, 1fr))` }} onMouseLeave={() => setActive(null)}>
        {rows.map((row, index) => {
          const height = (Number(row.value) || 0) / peak * 100;
          const showLabel = !sparseLabels || index === 0 || index === rows.length - 1 || index % 7 === 0;
          return <div key={row.key} role="listitem" tabIndex={0} className={`admin-chart-col ${active === row.key ? "active" : ""}`}
            aria-label={`${row.label}: ${formatNpr(row.value)}, ${row.detail}`}
            onMouseEnter={() => setActive(row.key)} onFocus={() => setActive(row.key)} onBlur={() => setActive(null)}>
            <div className="admin-chart-track">{height > 0 && <span className="admin-chart-bar" style={{ height: `${Math.max(2, height)}%` }}/>}</div>
            <small className={showLabel ? "" : "admin-chart-label-hidden"}>{row.label}</small>
            {active === row.key && <div className={`admin-chart-tip ${index > rows.length * .7 ? "left" : ""}`} role="tooltip"><strong>{formatNpr(row.value)}</strong><span>{row.label} · {row.detail}</span></div>}
          </div>;
        })}
      </div>
    </div>}
  </div>;
}

function HorizontalBars({ rows, valueLabel, emptyText }) {
  const peak = Math.max(0, ...rows.map(row => Number(row.value) || 0));
  if (!rows.length || peak === 0) return <div className="admin-empty">{emptyText}</div>;
  return <ul className="admin-hbars">{rows.map(row => <li key={row.key} tabIndex={0} title={`${row.label}: ${valueLabel(row)}`}>
    <div className="admin-hbar-head"><span>{row.label}</span><strong>{valueLabel(row)}</strong></div>
    <div className="admin-hbar-track"><span style={{ width: `${Math.max(1.5, (Number(row.value) || 0) / peak * 100)}%` }}/></div>
    {row.detail && <small>{row.detail}</small>}
  </li>)}</ul>;
}

/* ------------------------------ Sales report ------------------------------ */

export function SalesPanel({ api, refreshKey, onError, onExport }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let active = true;
    api("/store/analytics").then(result => { if (active) setData(result); }).catch(error => onError(error.message));
    return () => { active = false; };
  }, [api, refreshKey, onError]);
  if (!data) return <div className="admin-empty">Loading sales reports…</div>;
  const totalByMethod = (data.salesByMethod || []).reduce((sum, row) => sum + row.revenueNpr, 0);
  return <>
    <div className="admin-stat-grid admin-kpi-grid">
      <article className="admin-stat admin-kpi"><span>Gross sales</span><strong>{formatNpr(data.revenueNpr)}</strong><small>Confirmed, excluding cancellations</small></article>
      <article className="admin-stat admin-kpi"><span>Paid orders</span><strong>{data.paidOrders}</strong><small>of {data.orders} orders placed</small></article>
      <article className="admin-stat admin-kpi"><span>Average order</span><strong>{formatNpr(data.averageOrderNpr)}</strong><small>Per confirmed order</small></article>
      <article className="admin-stat admin-kpi"><span>Last 30 days</span><strong>{formatNpr(data.revenueLast30Npr)}</strong><small>Previous 30: {formatNpr(data.revenuePrevious30Npr)}</small></article>
    </div>
    <section className="admin-panel">
      <div className="admin-panel-heading"><div><h2>Monthly sales</h2><span>Confirmed revenue by month · NPR</span></div><button className="admin-add" onClick={onExport}><Download size={14}/> Export orders (CSV)</button></div>
      <BarChart rows={(data.salesByMonth || []).map(row => ({ key: row.month, label: new Date(`${row.month}-01T00:00:00`).toLocaleDateString(undefined, { month: "short", year: "2-digit" }), value: row.revenueNpr, detail: `${row.orders} order${row.orders === 1 ? "" : "s"}` }))} emptyText="Confirmed monthly sales will appear here."/>
    </section>
    <div className="admin-store-columns">
      <section className="admin-panel">
        <div className="admin-panel-heading"><div><h2>Best-selling books</h2><span>Copies sold in confirmed orders</span></div></div>
        <HorizontalBars rows={(data.topBooks || []).map(row => ({ key: row.bookId, label: row.title, value: row.quantity, detail: formatNpr(row.revenueNpr) }))} valueLabel={row => `${row.value} sold`} emptyText="Best sellers will appear after your first sale."/>
      </section>
      <section className="admin-panel">
        <div className="admin-panel-heading"><div><h2>Revenue by payment method</h2><span>Share of confirmed sales</span></div></div>
        <HorizontalBars rows={(data.salesByMethod || []).map(row => ({ key: row.method, label: PAYMENT_LABELS[row.method] || row.method, value: row.revenueNpr, detail: `${row.orders} order${row.orders === 1 ? "" : "s"} · ${totalByMethod ? Math.round(row.revenueNpr / totalByMethod * 100) : 0}%` }))} valueLabel={row => formatNpr(row.value)} emptyText="Payment method totals will appear after your first sale."/>
      </section>
    </div>
    <section className="admin-panel">
      <div className="admin-panel-heading"><div><h2>Orders by status</h2><span>Every order placed, grouped by its current status</span></div></div>
      <div className="admin-status-grid">{Object.entries(ORDER_LABELS).map(([status, label]) => <div key={status}><StatusBadge value={status}/><strong>{data.statusCounts?.[status] || 0}</strong><small>{label}</small></div>)}</div>
    </section>
  </>;
}

/* ------------------------------ Orders ------------------------------ */

export function OrdersPanel({ orders, api, onChanged, focusOrderId, onFocusHandled, onNotice, onExport }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [openId, setOpenId] = useState(null);

  useEffect(() => {
    if (!focusOrderId) return;
    setOpenId(focusOrderId);
    onFocusHandled();
  }, [focusOrderId, onFocusHandled]);

  const counts = useMemo(() => orders.reduce((result, order) => {
    result[order.status] = (result[order.status] || 0) + 1;
    if (order.refundStatus === "due") result.refund = (result.refund || 0) + 1;
    return result;
  }, {}), [orders]);
  const filtered = orders.filter(order => {
    const customer = customerOf(order);
    if (status === "refund" ? order.refundStatus !== "due" : status !== "all" && order.status !== status) return false;
    return `${order._id} ${customer.name || ""} ${customer.email || ""} ${customer.phone || ""} ${(order.items || []).map(item => item.title).join(" ")} ${order.trackingNumber || ""}`.toLowerCase().includes(query.toLowerCase().trim());
  });
  const selected = orders.find(order => order._id === openId);

  return <section className="admin-panel">
    <div className="admin-panel-heading"><div><h2>Customer orders</h2><span>{filtered.length} of {orders.length} orders · newest first</span></div><button className="admin-cancel admin-inline-button" onClick={onExport}><Download size={14}/> Export CSV</button></div>
    <div className="admin-chip-row" role="tablist" aria-label="Filter orders by status">
      {[["all", "All", orders.length], ["pending", "Awaiting payment"], ["paid", "Paid"], ["processing", "Processing"], ["shipped", "Shipped"], ["fulfilled", "Delivered"], ["cancelled", "Cancelled"], ["refund", "Refund due"]].map(([key, label, total]) => {
        const count = total ?? counts[key] ?? 0;
        if (key !== "all" && !count && status !== key) return null;
        return <button key={key} role="tab" aria-selected={status === key} className={status === key ? "active" : ""} onClick={() => setStatus(key)}>{label}<b>{count}</b></button>;
      })}
    </div>
    <div className="admin-list-toolbar"><label className="admin-search"><Search size={15}/><input aria-label="Search orders" placeholder="Search order, customer, book, or tracking number…" value={query} onChange={event => setQuery(event.target.value)}/></label></div>
    <div className="admin-table-scroll"><table className="admin-table"><thead><tr><th>Order</th><th>Customer</th><th>Items</th><th>Total</th><th>Payment</th><th>Status</th><th></th></tr></thead><tbody>
      {filtered.map(order => {
        const customer = customerOf(order);
        return <tr key={order._id} className="admin-clickable" onClick={() => setOpenId(order._id)}>
          <td data-label="Order"><code>…{order._id.slice(-8)}</code><small>{when(order.createdAt)}</small></td>
          <td data-label="Customer">{customer.name || "—"}<small>{customer.email || "—"}</small></td>
          <td data-label="Items">{(order.items || []).map(item => `${item.title} × ${item.quantity}`).join(", ") || "—"}</td>
          <td data-label="Total">{formatNpr(order.total)}</td>
          <td data-label="Payment">{PAYMENT_LABELS[order.paymentProvider] || order.paymentProvider || "—"}<small><StatusBadge value={order.paymentStatus} label={order.paymentStatus}/></small></td>
          <td data-label="Status"><StatusBadge value={order.status}/>{order.refundStatus === "due" && <small><StatusBadge value="due" label="Refund due"/></small>}</td>
          <td data-label="Details"><button className="admin-reconcile" onClick={event => { event.stopPropagation(); setOpenId(order._id); }}>Manage</button></td>
        </tr>;
      })}
    </tbody></table>{!filtered.length && <div className="admin-empty">{orders.length ? "No orders match the current search or filter." : "Orders will appear here after a customer checks out."}</div>}</div>
    {selected && <OrderDrawer order={selected} api={api} onClose={() => setOpenId(null)} onChanged={async message => { onNotice(message); await onChanged(); }}/>}
  </section>;
}

function OrderDrawer({ order, api, onClose, onChanged }) {
  const [action, setAction] = useState(null);
  const [note, setNote] = useState("");
  const [trackingNumber, setTrackingNumber] = useState(order.trackingNumber || "");
  const [carrier, setCarrier] = useState(order.carrier || "");
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const customer = customerOf(order);
  const steps = NEXT_STEPS[order.status] || [];

  useEffect(() => {
    function onKey(event) { if (event.key === "Escape") onClose(); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (action === "refund") {
        await api(`/orders/${order._id}/refund`, { method: "POST", body: JSON.stringify({ reference }) });
        await onChanged(`Refund recorded for order …${order._id.slice(-8)}.`);
      } else {
        await api(`/orders/${order._id}`, { method: "PATCH", body: JSON.stringify({ status: action, note, ...(action === "shipped" ? { trackingNumber, carrier } : {}) }) });
        await onChanged(`Order …${order._id.slice(-8)} is now ${ORDER_LABELS[action].toLowerCase()}. The customer was notified by email.`);
      }
      setAction(null);
      setNote("");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  return <div className="admin-dialog-backdrop admin-drawer-backdrop" role="presentation" onMouseDown={event => event.target === event.currentTarget && onClose()}>
    <aside className="admin-drawer" role="dialog" aria-modal="true" aria-label={`Order ${order._id}`}>
      <div className="admin-dialog-head"><div><div className="eyebrow">ORDER · {when(order.createdAt)}</div><h2 className="serif">…{order._id.slice(-8)}</h2><code className="admin-muted-code">{order._id}</code></div><button type="button" onClick={onClose} aria-label="Close order"><X size={18}/></button></div>
      <div className="admin-drawer-badges"><StatusBadge value={order.status}/><StatusBadge value={order.paymentStatus} label={`Payment ${order.paymentStatus}`}/>{order.refundStatus === "due" && <StatusBadge value="due" label="Refund due"/>}</div>

      {steps.length > 0 && !action && <div className="admin-drawer-actions">{steps.map(([next, label]) => <button key={next} className={next === "cancelled" ? "admin-cancel" : "admin-add"} onClick={() => { setAction(next); setError(""); }}>{next === "shipped" && <Truck size={14}/>}{label}</button>)}</div>}
      {order.refundStatus === "due" && !action && <div className="admin-drawer-actions"><button className="admin-add" onClick={() => setAction("refund")}><CreditCard size={14}/> Record refund</button></div>}

      {action && <form className="admin-drawer-form" onSubmit={submit}>
        <strong>{action === "refund" ? "Record a refund" : `${steps.find(([key]) => key === action)?.[1]}`}</strong>
        {action === "cancelled" && order.paymentStatus === "paid" && <p className="admin-warning"><AlertTriangle size={14}/> This order is paid. Cancelling returns the books to stock and marks a refund as due; refund the customer through {PAYMENT_LABELS[order.paymentProvider] || "the original method"}, then record it here.</p>}
        {action === "cancelled" && order.paymentStatus !== "paid" && <p className="admin-warning"><AlertTriangle size={14}/> Cancelling releases the reserved books back to stock. Do this only if the customer will not pay.</p>}
        {action === "shipped" && <div className="admin-dialog-fields">
          <label className="field">Courier / carrier<input value={carrier} maxLength={80} onChange={event => setCarrier(event.target.value)} placeholder="e.g. Nepal Can Move, Pathao"/></label>
          <label className="field">Tracking number<input value={trackingNumber} maxLength={120} onChange={event => setTrackingNumber(event.target.value)}/></label>
        </div>}
        {action === "refund" ? <label className="field">Refund reference<input value={reference} maxLength={120} onChange={event => setReference(event.target.value)} placeholder="Provider or bank refund reference"/></label>
          : <label className="field">Note to the customer (optional)<textarea rows={3} maxLength={500} value={note} onChange={event => setNote(event.target.value)} placeholder="Included in the status email and on the order page"/></label>}
        {error && <div className="admin-error" role="alert">{error}</div>}
        <div className="admin-dialog-footer"><button type="button" className="admin-cancel" onClick={() => { setAction(null); setError(""); }}>Back</button><button className="button" disabled={busy}>{busy ? "Saving…" : "Confirm"}</button></div>
      </form>}

      <div className="admin-drawer-section"><h3>Customer</h3>
        <dl className="admin-facts">
          <div><dt>Name</dt><dd>{customer.name || "—"}</dd></div>
          <div><dt>Email</dt><dd>{customer.email ? <a href={`mailto:${customer.email}?subject=${encodeURIComponent(`Your order ${order._id}`)}`}>{customer.email}</a> : "—"}</dd></div>
          <div><dt>Phone</dt><dd>{customer.phone ? <a href={`tel:${customer.phone}`}>{customer.phone}</a> : "—"}</dd></div>
          <div><dt>Delivery address</dt><dd className="admin-preline">{customer.address || "—"}</dd></div>
        </dl>
      </div>
      <div className="admin-drawer-section"><h3>Items</h3>
        <ul className="admin-line-items">{(order.items || []).map((item, index) => <li key={index}><span>{item.title}<small>{item.quantity} × {formatNpr(item.unitPrice)}</small></span><strong>{formatNpr(item.unitPrice * item.quantity)}</strong></li>)}
          <li className="admin-line-total"><span>Total</span><strong>{formatNpr(order.total)}</strong></li></ul>
      </div>
      <div className="admin-drawer-section"><h3>Payment</h3>
        <dl className="admin-facts">
          <div><dt>Method</dt><dd>{PAYMENT_LABELS[order.paymentProvider] || order.paymentProvider}{order.paymentMode ? ` (${order.paymentMode})` : ""}</dd></div>
          <div><dt>Reference</dt><dd><code>{order.paymentReference || "—"}</code></dd></div>
          {order.refundReference && <div><dt>Refund reference</dt><dd><code>{order.refundReference}</code></dd></div>}
          {order.trackingNumber && <div><dt>Shipment</dt><dd>{order.carrier || "Courier"} · <code>{order.trackingNumber}</code></dd></div>}
        </dl>
      </div>
      <div className="admin-drawer-section"><h3>Timeline</h3>
        <ol className="admin-timeline">{[...(order.statusHistory || [])].reverse().map((entry, index) => <li key={index}><span className={`dot ${entry.status}`}/><div><strong>{ORDER_LABELS[entry.status] || entry.status}</strong>{entry.note && <p>{entry.note}</p>}<small>{when(entry.at)}</small></div></li>)}</ol>
      </div>
    </aside>
  </div>;
}

/* ------------------------------ Payments ------------------------------ */

export function PaymentsPanel({ payments, api, onChanged, onNotice }) {
  const [filter, setFilter] = useState("all");
  const [confirming, setConfirming] = useState(null);
  const [verifying, setVerifying] = useState(null);
  const [error, setError] = useState("");
  const filtered = payments.filter(payment => filter === "all"
    || (filter === "action" ? ["pending", "initiated"].includes(payment.status) : payment.provider === filter));
  const awaiting = payments.filter(payment => payment.provider === "bank_transfer" && payment.status === "pending").length;

  async function verify(payment) {
    setVerifying(payment._id);
    setError("");
    try {
      const result = await api(`/payments/${payment._id}/reconcile`, { method: "POST" });
      onNotice(`${PAYMENT_LABELS[payment.provider]} reports this payment as ${result.payment.status}.`);
      await onChanged();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setVerifying(null);
    }
  }

  return <section className="admin-panel">
    <div className="admin-panel-heading"><div><h2>Payment ledger</h2><span>Gateway payments are verified with eSewa or Khalti; bank transfers are confirmed after you check the bank statement.</span></div></div>
    {awaiting > 0 && <div className="admin-callout"><Landmark size={16}/><span><strong>{awaiting} bank transfer{awaiting === 1 ? "" : "s"} awaiting verification.</strong> Match the amount and reference on your bank statement before confirming.</span></div>}
    <div className="admin-chip-row">{[["all", "All"], ["action", "Needs action"], ["esewa", "eSewa"], ["khalti", "Khalti"], ["bank_transfer", "Bank transfer"]].map(([key, label]) => <button key={key} className={filter === key ? "active" : ""} onClick={() => setFilter(key)}>{label}</button>)}</div>
    {error && <div className="admin-error" role="alert">{error}</div>}
    <div className="admin-table-scroll"><table className="admin-table"><thead><tr><th>Date</th><th>Order / customer</th><th>Method</th><th>Amount</th><th>Status</th><th>References</th><th>Action</th></tr></thead><tbody>
      {filtered.map(payment => {
        const order = payment.order || {};
        const actionable = ["pending", "initiated"].includes(payment.status);
        return <tr key={payment._id}>
          <td data-label="Date">{when(payment.createdAt)}</td>
          <td data-label="Order"><code>…{String(order._id || "").slice(-8) || "—"}</code><small>{order.customer?.name || ""}</small></td>
          <td data-label="Method">{PAYMENT_LABELS[payment.provider] || payment.provider}<small>{payment.mode}</small></td>
          <td data-label="Amount">{formatNpr(payment.amount)}</td>
          <td data-label="Status"><StatusBadge value={payment.status} label={payment.status}/></td>
          <td data-label="References">{payment.providerTransactionId ? <code>{payment.providerTransactionId}</code> : "—"}{payment.customerReference && <small>Customer: <b>{payment.customerReference}</b>{payment.customerNote ? ` — ${payment.customerNote}` : ""}</small>}{payment.verifiedAt && <small>Verified {when(payment.verifiedAt)}</small>}</td>
          <td data-label="Action">{actionable && (payment.provider === "bank_transfer"
            ? <button className="admin-publish-toggle" onClick={() => setConfirming(payment)}>Confirm transfer</button>
            : <button className="admin-publish-toggle" disabled={verifying === payment._id} onClick={() => verify(payment)}>{verifying === payment._id ? "Checking…" : "Verify with provider"}</button>)}</td>
        </tr>;
      })}
    </tbody></table>{!filtered.length && <div className="admin-empty">{payments.length ? "No payments match this filter." : "Payment attempts will be recorded here."}</div>}</div>
    {confirming && <ConfirmTransferDialog payment={confirming} api={api} onClose={() => setConfirming(null)} onDone={async () => { setConfirming(null); onNotice("Bank transfer verified. The order is now paid and the customer was emailed."); await onChanged(); }}/>}
  </section>;
}

function ConfirmTransferDialog({ payment, api, onClose, onDone }) {
  const [reference, setReference] = useState(payment.customerReference || "");
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(`/payments/${payment._id}/confirm`, { method: "POST", body: JSON.stringify({ transactionReference: reference.trim() }) });
      await onDone();
    } catch (requestError) {
      setError(requestError.message);
      setBusy(false);
    }
  }
  return <Modal title="Confirm bank transfer" eyebrow="PAYMENT VERIFICATION" onClose={onClose}>
    <form onSubmit={submit} className="admin-drawer-form admin-plain-form">
      <dl className="admin-facts">
        <div><dt>Expected amount</dt><dd><strong>{formatNpr(payment.amount)}</strong></dd></div>
        <div><dt>Order reference</dt><dd><code>{payment.order?._id}</code></dd></div>
        <div><dt>Customer</dt><dd>{payment.order?.customer?.name || "—"}</dd></div>
        {payment.customerReference && <div><dt>Reported by customer</dt><dd><code>{payment.customerReference}</code>{payment.customerNote && <small> — {payment.customerNote}</small>}</dd></div>}
      </dl>
      <label className="field">Bank transaction reference<input value={reference} maxLength={120} onChange={event => setReference(event.target.value)} placeholder="As shown on your bank statement"/></label>
      <label className="admin-check"><input type="checkbox" checked={checked} onChange={event => setChecked(event.target.checked)}/> I have checked our bank statement and received {formatNpr(payment.amount)} for this order.</label>
      {error && <div className="admin-error" role="alert">{error}</div>}
      <div className="admin-dialog-footer"><button type="button" className="admin-cancel" onClick={onClose}>Cancel</button><button className="button" disabled={!checked || busy}>{busy ? "Confirming…" : "Confirm payment"}</button></div>
    </form>
  </Modal>;
}

/* ------------------------------ Inventory ------------------------------ */

export function InventoryPanel({ books, api, canWrite, threshold = 5, onAdd, onEdit, onDelete, onPublish, onChanged, onNotice }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [adjusting, setAdjusting] = useState(null);
  const categories = [...new Set(books.map(book => book.category).filter(Boolean))].sort();
  const stats = {
    live: books.filter(book => book.status !== "draft" && Number(book.priceNpr) > 0 && book.stock > 0).length,
    low: books.filter(book => book.status !== "draft" && Number(book.priceNpr) > 0 && (book.stock ?? 0) <= threshold).length,
    unpriced: books.filter(book => !(Number(book.priceNpr) > 0)).length,
    value: books.reduce((sum, book) => sum + (Number(book.priceNpr) || 0) * (Number(book.stock) || 0), 0)
  };
  const filtered = books.filter(book => {
    if (filter === "low" && !((book.stock ?? 0) <= threshold && Number(book.priceNpr) > 0)) return false;
    if (filter === "unpriced" && Number(book.priceNpr) > 0) return false;
    if (filter === "draft" && book.status !== "draft") return false;
    if (filter.startsWith("cat:") && book.category !== filter.slice(4)) return false;
    return `${book.title} ${book.subtitle || ""} ${book.category || ""} ${book.format || ""}`.toLowerCase().includes(query.toLowerCase().trim());
  });

  return <>
    <div className="admin-stat-grid admin-kpi-grid">
      <article className="admin-stat admin-kpi"><span>Available to buy</span><strong>{stats.live}</strong><small>Published, priced and in stock</small></article>
      <article className="admin-stat admin-kpi"><span>Low or out of stock</span><strong>{stats.low}</strong><small>At or below {threshold} copies</small></article>
      <article className="admin-stat admin-kpi"><span>Not yet priced</span><strong>{stats.unpriced}</strong><small>Hidden from checkout until priced</small></article>
      <article className="admin-stat admin-kpi"><span>Stock value</span><strong>{formatNpr(stats.value)}</strong><small>At current retail prices</small></article>
    </div>
    <section className="admin-panel">
      <div className="admin-panel-heading"><div><h2>Bookstore inventory</h2><span>{filtered.length} of {books.length} books</span></div>{canWrite && <button className="admin-add" onClick={onAdd}><Plus size={15}/> Add book</button>}</div>
      <div className="admin-list-toolbar">
        <label className="admin-search"><Search size={15}/><input aria-label="Search inventory" placeholder="Search title, category, or format…" value={query} onChange={event => setQuery(event.target.value)}/></label>
        <label className="admin-filter-label">Show<select value={filter} onChange={event => setFilter(event.target.value)}>
          <option value="all">All books</option><option value="low">Low or out of stock</option><option value="unpriced">Not priced</option><option value="draft">Drafts</option>
          {categories.map(category => <option key={category} value={`cat:${category}`}>{category}</option>)}
        </select></label>
      </div>
      <div className="admin-table-scroll"><table className="admin-table admin-inventory-table"><thead><tr><th>Book</th><th>Category</th><th>Price</th><th>Stock</th><th>Status</th><th>Actions</th></tr></thead><tbody>
        {filtered.map(book => {
          const low = Number(book.priceNpr) > 0 && (book.stock ?? 0) <= threshold;
          return <tr key={book._id}>
            <td data-label="Book"><div className="admin-book-cell">{book.image && <img src={book.image} alt=""/>}<span><strong>{book.title}</strong><small>{book.format || "Book"}{book.year ? ` · ${book.year}` : ""}</small></span></div></td>
            <td data-label="Category">{book.category || <span className="admin-muted">Uncategorised</span>}</td>
            <td data-label="Price">{Number(book.priceNpr) > 0 ? formatNpr(book.priceNpr) : <StatusBadge value="pending" label="Set a price"/>}</td>
            <td data-label="Stock"><div className="admin-stock-cell">
              {canWrite && <button aria-label={`Remove stock for ${book.title}`} onClick={() => setAdjusting({ book, delta: -1 })}><Minus size={12}/></button>}
              <strong className={low ? (book.stock ? "low" : "out") : ""}>{book.stock ?? 0}</strong>
              {canWrite && <button aria-label={`Add stock for ${book.title}`} onClick={() => setAdjusting({ book, delta: 1 })}><Plus size={12}/></button>}
            </div>{low && <small className="admin-low-text">{book.stock ? "Low stock" : "Sold out"}</small>}</td>
            <td data-label="Status"><StatusBadge value={book.status || "published"} label={book.status || "published"}/></td>
            <td data-label="Actions"><div className="admin-row-actions">
              {canWrite && <><button title="Edit book" aria-label="Edit book" onClick={() => onEdit(book)}><Pencil size={14}/></button>
                <button className="admin-publish-toggle" onClick={() => onPublish(book)}>{book.status === "draft" ? "Publish" : "Unpublish"}</button>
                <button title="Delete book" aria-label="Delete book" className="danger" onClick={() => onDelete(book)}><Trash2 size={14}/></button></>}
              <a className="admin-icon-link" href={`/store/books/${book._id}`} target="_blank" rel="noreferrer" title="View in store" aria-label="View in store"><Eye size={14}/></a>
            </div></td>
          </tr>;
        })}
      </tbody></table>{!filtered.length && <div className="admin-empty">{books.length ? "No books match the current search or filter." : "No books yet. Use Add book to create your first one."}</div>}</div>
    </section>
    {adjusting && <StockDialog book={adjusting.book} initialDelta={adjusting.delta} api={api} onClose={() => setAdjusting(null)} onDone={async message => { setAdjusting(null); onNotice(message); await onChanged(); }}/>}
  </>;
}

function StockDialog({ book, initialDelta, api, onClose, onDone }) {
  const [mode, setMode] = useState(initialDelta > 0 ? "add" : "remove");
  const [amount, setAmount] = useState(1);
  const [reason, setReason] = useState(initialDelta > 0 ? "New stock received" : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const delta = mode === "add" ? amount : -amount;
  const next = (book.stock || 0) + delta;
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api(`/books/${book._id}/stock`, { method: "POST", body: JSON.stringify({ delta, reason }) });
      await onDone(`${book.title}: stock is now ${result.book.stock}.`);
    } catch (requestError) {
      setError(requestError.message);
      setBusy(false);
    }
  }
  return <Modal title={book.title} eyebrow="ADJUST STOCK" onClose={onClose}>
    <form onSubmit={submit} className="admin-drawer-form admin-plain-form">
      <div className="admin-segmented" role="radiogroup" aria-label="Adjustment type">
        <button type="button" role="radio" aria-checked={mode === "add"} className={mode === "add" ? "active" : ""} onClick={() => setMode("add")}><Plus size={13}/> Add stock</button>
        <button type="button" role="radio" aria-checked={mode === "remove"} className={mode === "remove" ? "active" : ""} onClick={() => setMode("remove")}><Minus size={13}/> Remove stock</button>
      </div>
      <div className="admin-dialog-fields">
        <label className="field">Copies<input type="number" min={1} max={100000} required value={amount} onChange={event => setAmount(Math.max(1, Math.floor(Number(event.target.value) || 1)))}/></label>
        <label className="field">Reason<input maxLength={200} value={reason} onChange={event => setReason(event.target.value)} placeholder={mode === "add" ? "New stock received" : "Damaged, gifted, sold at event…"}/></label>
      </div>
      <p className={`admin-stock-preview ${next < 0 ? "invalid" : ""}`}>{book.stock || 0} → <strong>{next}</strong> copies {next < 0 && "· stock cannot go below zero"}</p>
      {error && <div className="admin-error" role="alert">{error}</div>}
      <div className="admin-dialog-footer"><button type="button" className="admin-cancel" onClick={onClose}>Cancel</button><button className="button" disabled={busy || next < 0}>{busy ? "Saving…" : "Save adjustment"}</button></div>
    </form>
  </Modal>;
}

/* ------------------------------ Categories ------------------------------ */

export function CategoriesPanel({ api, refreshKey, canWrite, onNotice, onError, onCategoriesChanged }) {
  const [data, setData] = useState(null);
  const [editing, setEditing] = useState(null);
  const load = useCallback(async () => {
    try {
      setData(await api("/categories"));
    } catch (error) {
      onError(error.message);
    }
  }, [api, onError]);
  useEffect(() => { load(); }, [load, refreshKey]);

  async function remove(category) {
    if (!window.confirm(`Delete the “${category.name}” category?`)) return;
    try {
      await api(`/categories/${category._id}`, { method: "DELETE" });
      onNotice(`Category “${category.name}” deleted.`);
      await load();
      onCategoriesChanged();
    } catch (error) {
      onError(error.message);
    }
  }

  async function toggle(category) {
    try {
      await api(`/categories/${category._id}`, { method: "PATCH", body: JSON.stringify({ active: !category.active }) });
      onNotice(`“${category.name}” is now ${category.active ? "hidden from" : "shown in"} the store filters.`);
      await load();
    } catch (error) {
      onError(error.message);
    }
  }

  if (!data) return <div className="admin-empty">Loading categories…</div>;
  return <section className="admin-panel">
    <div className="admin-panel-heading"><div><h2>Store categories</h2><span>Categories organise the storefront filters. Lower sort numbers appear first.</span></div>{canWrite && <button className="admin-add" onClick={() => setEditing({})}><Plus size={15}/> Add category</button>}</div>
    <div className="admin-table-scroll"><table className="admin-table"><thead><tr><th>Category</th><th>Books</th><th>Sort</th><th>Storefront</th><th>Actions</th></tr></thead><tbody>
      {data.categories.map(category => <tr key={category._id}>
        <td data-label="Category"><strong><Tag size={12}/> {category.name}</strong>{category.description && <small>{category.description}</small>}</td>
        <td data-label="Books">{category.bookCount}</td>
        <td data-label="Sort">{category.sortOrder}</td>
        <td data-label="Storefront"><StatusBadge value={category.active ? "active" : "draft"} label={category.active ? "Shown" : "Hidden"}/></td>
        <td data-label="Actions">{canWrite && <div className="admin-row-actions">
          <button title="Edit category" aria-label={`Edit ${category.name}`} onClick={() => setEditing(category)}><Pencil size={14}/></button>
          <button className="admin-publish-toggle" onClick={() => toggle(category)}>{category.active ? "Hide" : "Show"}</button>
          <button title={category.bookCount ? "Move its books to another category first" : "Delete category"} aria-label={`Delete ${category.name}`} className="danger" disabled={category.bookCount > 0} onClick={() => remove(category)}><Trash2 size={14}/></button>
        </div>}</td>
      </tr>)}
    </tbody></table>{!data.categories.length && <div className="admin-empty">No managed categories yet. Add one, or adopt a category already used by your books below.</div>}</div>
    {data.unmanaged.length > 0 && <div className="admin-unmanaged">
      <strong>Used by books but not managed yet</strong>
      <div>{data.unmanaged.map(item => <button key={item.name} disabled={!canWrite} onClick={() => setEditing({ name: item.name, adopt: true })}><Plus size={12}/> {item.name} <small>({item.bookCount})</small></button>)}</div>
    </div>}
    {editing && <CategoryDialog category={editing} api={api} onClose={() => setEditing(null)} onSaved={async message => { setEditing(null); onNotice(message); await load(); onCategoriesChanged(); }}/>}
  </section>;
}

function CategoryDialog({ category, api, onClose, onSaved }) {
  const isNew = !category._id;
  const [form, setForm] = useState({ name: category.name || "", description: category.description || "", sortOrder: category.sortOrder ?? 100, active: category.active ?? true });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const payload = { ...form, name: form.name.trim(), sortOrder: Number(form.sortOrder) || 0 };
      const result = await api(isNew ? "/categories" : `/categories/${category._id}`, { method: isNew ? "POST" : "PATCH", body: JSON.stringify(payload) });
      await onSaved(isNew ? `Category “${payload.name}” created.` : `Category saved${result.booksMoved ? ` and ${result.booksMoved} book${result.booksMoved === 1 ? "" : "s"} moved to the new name` : ""}.`);
    } catch (requestError) {
      setError(requestError.message);
      setBusy(false);
    }
  }
  return <Modal title={isNew ? (category.adopt ? `Manage “${category.name}”` : "New category") : `Edit ${category.name}`} eyebrow="STORE CATEGORY" onClose={onClose}>
    <form onSubmit={submit} className="admin-drawer-form admin-plain-form">
      <div className="admin-dialog-fields">
        <label className="field">Name<input required maxLength={80} value={form.name} onChange={event => setForm({ ...form, name: event.target.value })}/></label>
        <label className="field">Sort order<input type="number" min={0} max={10000} value={form.sortOrder} onChange={event => setForm({ ...form, sortOrder: event.target.value })}/></label>
        <label className="field full">Description<textarea rows={3} maxLength={500} value={form.description} onChange={event => setForm({ ...form, description: event.target.value })}/></label>
        <label className="admin-check"><input type="checkbox" checked={form.active} onChange={event => setForm({ ...form, active: event.target.checked })}/> Show as a filter in the store</label>
      </div>
      {!isNew && form.name.trim() !== category.name && <p className="admin-warning"><AlertTriangle size={14}/> Renaming also moves every book in “{category.name}” to the new name.</p>}
      {error && <div className="admin-error" role="alert">{error}</div>}
      <div className="admin-dialog-footer"><button type="button" className="admin-cancel" onClick={onClose}>Cancel</button><button className="button" disabled={busy}>{busy ? "Saving…" : "Save category"}</button></div>
    </form>
  </Modal>;
}

/* ------------------------------ Customers ------------------------------ */

export function CustomersPanel({ customers, api, canWrite, onAdd, onEdit, onDelete, onOpenOrder }) {
  const [view, setView] = useState("customers");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("recent");
  const [viewing, setViewing] = useState(null);
  const filtered = customers.filter(customer => `${customer.name || ""} ${customer.email || ""} ${customer.phone || ""} ${customer.address || ""}`.toLowerCase().includes(query.toLowerCase().trim()))
    .sort(sort === "spent" ? (a, b) => (b.totalSpent || 0) - (a.totalSpent || 0)
      : sort === "orders" ? (a, b) => (b.orderCount || 0) - (a.orderCount || 0)
      : (a, b) => new Date(b.lastOrderAt || b.createdAt || 0) - new Date(a.lastOrderAt || a.createdAt || 0));
  const repeat = customers.filter(customer => customer.orderCount > 1).length;
  return <>
    <div className="admin-stat-grid admin-kpi-grid">
      <article className="admin-stat admin-kpi"><span>Customers</span><strong>{customers.length}</strong><small>With contact details on file</small></article>
      <article className="admin-stat admin-kpi"><span>Repeat customers</span><strong>{repeat}</strong><small>More than one order</small></article>
      <article className="admin-stat admin-kpi"><span>Lifetime sales</span><strong>{formatNpr(customers.reduce((sum, customer) => sum + (customer.totalSpent || 0), 0))}</strong><small>Confirmed, across all customers</small></article>
    </div>
    <div className="admin-chip-row admin-view-switch" role="tablist" aria-label="Customer views">
      <button role="tab" aria-selected={view === "customers"} className={view === "customers" ? "active" : ""} onClick={() => setView("customers")}>Customers &amp; buyers</button>
      <button role="tab" aria-selected={view === "accounts"} className={view === "accounts" ? "active" : ""} onClick={() => setView("accounts")}>Registered accounts</button>
    </div>
    {view === "accounts" ? <AccountsSection api={api} canWrite={canWrite}/> : <section className="admin-panel">
      <div className="admin-panel-heading"><div><h2>Customers</h2><span>{filtered.length} of {customers.length} customers</span></div>{canWrite && <button className="admin-add" onClick={onAdd}><Plus size={15}/> Add customer</button>}</div>
      <div className="admin-list-toolbar">
        <label className="admin-search"><Search size={15}/><input aria-label="Search customers" placeholder="Search name, email, phone, or address…" value={query} onChange={event => setQuery(event.target.value)}/></label>
        <label className="admin-filter-label">Sort<select value={sort} onChange={event => setSort(event.target.value)}><option value="recent">Most recent</option><option value="spent">Highest spend</option><option value="orders">Most orders</option></select></label>
      </div>
      <div className="admin-table-scroll"><table className="admin-table"><thead><tr><th>Customer</th><th>Phone</th><th>Orders</th><th>Total spent</th><th>Last order</th><th>Actions</th></tr></thead><tbody>
        {filtered.map(customer => <tr key={customer._id} className="admin-clickable" onClick={() => setViewing(customer)}>
          <td data-label="Customer"><strong>{customer.name || "—"}</strong><small>{customer.email}</small></td>
          <td data-label="Phone">{customer.phone || "—"}</td>
          <td data-label="Orders">{customer.orderCount || 0}</td>
          <td data-label="Total spent">{formatNpr(customer.totalSpent)}</td>
          <td data-label="Last order">{when(customer.lastOrderAt, false)}</td>
          <td data-label="Actions"><div className="admin-row-actions" onClick={event => event.stopPropagation()}>
            <button title="View customer" aria-label="View customer" onClick={() => setViewing(customer)}><Eye size={14}/></button>
            {canWrite && <><button title="Edit customer" aria-label="Edit customer" onClick={() => onEdit(customer)}><Pencil size={14}/></button>
              <button title="Delete customer" aria-label="Delete customer" className="danger" onClick={() => onDelete(customer)}><Trash2 size={14}/></button></>}
          </div></td>
        </tr>)}
      </tbody></table>{!filtered.length && <div className="admin-empty">{customers.length ? "No customers match your search." : "Customers are added automatically when they check out."}</div>}</div>
    </section>}
    {viewing && <CustomerDialog customer={viewing} api={api} onClose={() => setViewing(null)} onOpenOrder={id => { setViewing(null); onOpenOrder(id); }}/>}
  </>;
}

function AccountsSection({ api, canWrite }) {
  const [accounts, setAccounts] = useState(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(null);
  const load = useCallback(async () => {
    try {
      setAccounts((await api("/accounts")).accounts || []);
      setError("");
    } catch (requestError) {
      setError(requestError.message);
    }
  }, [api]);
  useEffect(() => { load(); }, [load]);

  async function toggle(account) {
    if (account.active && !window.confirm(`Suspend ${account.email}? They will be signed out and cannot sign in until reactivated. Their orders are kept.`)) return;
    setBusy(account.id);
    try {
      await api(`/accounts/${account.id}`, { method: "PATCH", body: JSON.stringify({ active: !account.active }) });
      await load();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(null);
    }
  }

  const rows = (accounts || []).filter(account => `${account.name} ${account.email} ${account.phone}`.toLowerCase().includes(query.toLowerCase().trim()));
  return <section className="admin-panel">
    <div className="admin-panel-heading"><div><h2>Registered accounts</h2><span>{accounts ? `${rows.length} of ${accounts.length} shopper accounts` : "Loading…"} · created through the bookstore sign-up</span></div></div>
    <div className="admin-list-toolbar"><label className="admin-search"><Search size={15}/><input aria-label="Search accounts" placeholder="Search name, email, or phone…" value={query} onChange={event => setQuery(event.target.value)}/></label></div>
    {error && <div className="admin-error" role="alert">{error}</div>}
    <div className="admin-table-scroll"><table className="admin-table"><thead><tr><th>Account</th><th>Email</th><th>Orders</th><th>Joined</th><th>Status</th><th>Actions</th></tr></thead><tbody>
      {rows.map(account => <tr key={account.id}>
        <td data-label="Account"><strong>{account.name || "—"}</strong>{account.phone && <small>{account.phone}</small>}</td>
        <td data-label="Email">{account.email}{!account.emailVerified && <small>Email not verified</small>}</td>
        <td data-label="Orders">{account.orderCount}{account.lastOrderAt && <small>Last {when(account.lastOrderAt, false)}</small>}</td>
        <td data-label="Joined">{when(account.createdAt, false)}</td>
        <td data-label="Status"><StatusBadge value={account.active ? (account.emailVerified ? "active" : "pending") : "cancelled"} label={account.active ? (account.emailVerified ? "Active" : "Unverified") : "Suspended"}/></td>
        <td data-label="Actions">{canWrite && <button className="admin-publish-toggle" disabled={busy === account.id} onClick={() => toggle(account)}>{account.active ? "Suspend" : "Reactivate"}</button>}</td>
      </tr>)}
    </tbody></table>{accounts && !rows.length && <div className="admin-empty">{accounts.length ? "No accounts match your search." : "Shoppers who create an account in the bookstore will appear here."}</div>}</div>
  </section>;
}

function CustomerDialog({ customer, api, onClose, onOpenOrder }) {
  const [orders, setOrders] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api(`/customers/${customer._id}/orders`).then(result => { if (active) setOrders(result.orders || []); }).catch(requestError => { if (active) setError(requestError.message); });
    return () => { active = false; };
  }, [api, customer._id]);
  return <Modal title={customer.name || customer.email} eyebrow="CUSTOMER" onClose={onClose} wide>
    <div className="admin-customer-summary">
      <dl className="admin-facts">
        <div><dt>Email</dt><dd><a href={`mailto:${customer.email}`}>{customer.email}</a></dd></div>
        <div><dt>Phone</dt><dd>{customer.phone ? <a href={`tel:${customer.phone}`}>{customer.phone}</a> : "—"}</dd></div>
        <div><dt>Address</dt><dd className="admin-preline">{customer.address || "—"}</dd></div>
        {customer.notes && <div><dt>Notes</dt><dd className="admin-preline">{customer.notes}</dd></div>}
      </dl>
      <div className="admin-mini-stats"><div><span>Orders</span><strong>{customer.orderCount || 0}</strong></div><div><span>Total spent</span><strong>{formatNpr(customer.totalSpent)}</strong></div><div><span>Customer since</span><strong>{when(customer.createdAt, false)}</strong></div></div>
    </div>
    <h3 className="admin-subheading"><Users size={14}/> Order history</h3>
    {error && <div className="admin-error">{error}</div>}
    {!orders ? <div className="admin-empty">Loading orders…</div> : orders.length ? <div className="admin-table-scroll"><table className="admin-table"><thead><tr><th>Order</th><th>Items</th><th>Total</th><th>Status</th></tr></thead><tbody>
      {orders.map(order => <tr key={order._id} className="admin-clickable" onClick={() => onOpenOrder(order._id)}>
        <td data-label="Order"><code>…{order._id.slice(-8)}</code><small>{when(order.createdAt)}</small></td>
        <td data-label="Items">{(order.items || []).map(item => `${item.title} × ${item.quantity}`).join(", ")}</td>
        <td data-label="Total">{formatNpr(order.total)}</td>
        <td data-label="Status"><StatusBadge value={order.status}/></td>
      </tr>)}
    </tbody></table></div> : <div className="admin-empty">No orders on record for this customer.</div>}
  </Modal>;
}

