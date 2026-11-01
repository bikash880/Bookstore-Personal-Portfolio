"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  ArrowLeft, ArrowRight, Landmark, Lock, Minus, PackageSearch, Plus,
  ShieldCheck, ShoppingBag, UserRound, Wallet, X
} from "lucide-react";
import BrandMark from "../brand-mark";
import ThemeToggle from "../theme-toggle";
import {
  CART_KEY, CUSTOMER_KEY, PAYMENT_LABELS, formatNpr, isPurchasable, readStorage,
  rememberOrder, requestJson, sanitizeCart, writeStorage
} from "./store-shared";

const StoreContext = createContext(null);

export function useStore() {
  const value = useContext(StoreContext);
  if (!value) throw new Error("useStore must be used inside the bookstore layout.");
  return value;
}

const emptyCustomer = { name: "", email: "", phone: "", address: "" };

export default function StoreShell({ children }) {
  const router = useRouter();
  const pathname = usePathname();
  const [books, setBooks] = useState([]);
  const [categories, setCategories] = useState([]);
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [cart, setCart] = useState([]);
  const [cartReady, setCartReady] = useState(false);
  const [cartOpen, setCartOpen] = useState(false);
  const [checkoutOpen, setCheckoutOpen] = useState(false);
  const [toast, setToast] = useState("");
  const [account, setAccount] = useState(null);
  const [accountReady, setAccountReady] = useState(false);

  const refreshAccount = useCallback(async () => {
    try {
      const result = await requestJson("/api/auth/me");
      setAccount(result.user || null);
      return result.user || null;
    } catch {
      setAccount(null);
      return null;
    } finally {
      setAccountReady(true);
    }
  }, []);

  const logout = useCallback(async () => {
    try { await requestJson("/api/auth/logout", { method: "POST" }); } catch { /* the cookie is cleared server-side when reachable */ }
    setAccount(null);
  }, []);

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    try {
      const [catalog, store] = await Promise.all([
        requestJson("/api/store/books"),
        requestJson("/api/store/settings")
      ]);
      setBooks(Array.isArray(catalog.books) ? catalog.books : []);
      setCategories(Array.isArray(catalog.categories) ? catalog.categories : []);
      setSettings(store.settings || {});
      setLoadError("");
    } catch (requestError) {
      setLoadError(requestError.message || "The bookstore could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCatalog();
    refreshAccount();
    setCart(sanitizeCart(readStorage(CART_KEY, [])));
    setCartReady(true);
    function syncCart(event) {
      if (event.key === CART_KEY) setCart(sanitizeCart(readStorage(CART_KEY, [])));
    }
    window.addEventListener("storage", syncCart);
    return () => window.removeEventListener("storage", syncCart);
  }, [loadCatalog, refreshAccount]);

  useEffect(() => {
    if (cartReady) writeStorage(CART_KEY, cart);
  }, [cart, cartReady]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 3200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    const open = cartOpen || checkoutOpen;
    document.body.style.overflow = open ? "hidden" : "";
    if (!open) return;
    function closeOnEscape(event) {
      if (event.key !== "Escape") return;
      setCartOpen(false);
      setCheckoutOpen(false);
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = "";
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [cartOpen, checkoutOpen]);

  const cartItems = useMemo(() => cart.map(entry => ({
    ...entry,
    book: books.find(book => book._id === entry.bookId)
  })).filter(entry => isPurchasable(entry.book)), [cart, books]);
  const cartCount = cartItems.reduce((sum, item) => sum + item.quantity, 0);
  const subtotal = cartItems.reduce((sum, item) => sum + Number(item.book.priceNpr) * item.quantity, 0);

  const addToCart = useCallback((book, quantity = 1, { silent = false } = {}) => {
    if (!isPurchasable(book)) return false;
    setCart(current => {
      const existing = current.find(item => item.bookId === book._id);
      const limit = Math.min(book.stock, 20);
      if (existing) return current.map(item => item.bookId === book._id
        ? { ...item, quantity: Math.min(item.quantity + quantity, limit) }
        : item);
      return [...current, { bookId: book._id, quantity: Math.min(quantity, limit) }];
    });
    if (!silent) setToast(`“${book.title}” was added to your bag.`);
    return true;
  }, []);

  const changeQuantity = useCallback((book, quantity) => {
    setCart(current => quantity < 1
      ? current.filter(item => item.bookId !== book._id)
      : current.map(item => item.bookId === book._id
        ? { ...item, quantity: Math.min(quantity, book.stock, 20) }
        : item));
  }, []);

  const clearCart = useCallback(() => setCart([]), []);

  const startCheckout = useCallback(() => {
    setCartOpen(false);
    setCheckoutOpen(true);
  }, []);

  const openCart = useCallback(() => setCartOpen(true), []);

  // Memoized so every book card using the store context doesn't re-render when only the toast,
  // drawer, or checkout state changes.
  const value = useMemo(() => ({
    books, categories, settings, loading, loadError, reload: loadCatalog,
    cartItems, cartCount, subtotal, addToCart, changeQuantity, clearCart,
    openCart, startCheckout, notify: setToast,
    account, accountReady, setAccount, refreshAccount, logout
  }), [
    books, categories, settings, loading, loadError, loadCatalog, cartItems, cartCount, subtotal,
    addToCart, changeQuantity, clearCart, openCart, startCheckout, account, accountReady, refreshAccount, logout
  ]);

  return <StoreContext.Provider value={value}>
    <main className="store-page">
      <header className="store-header">
        <div className="store-topline">Secure checkout with eSewa, Khalti &amp; bank transfer · Prices in Nepalese rupees</div>
        <div className="store-header-main">
          <Link className="store-back-link" href="/"><ArrowLeft size={15}/> Portfolio</Link>
          <Link className="store-brand" href="/store" aria-label="Bookstore home">
            <BrandMark size={40} className="store-brand-logo"/>
            <span><strong>{settings?.storeName || "The Bookshop"}</strong><small>BOOKS FOR THE QUIET HOURS</small></span>
          </Link>
          <div className="store-header-actions">
            <ThemeToggle/>
            <Link className={`store-track-link ${pathname?.startsWith("/store/track") || pathname?.startsWith("/store/orders") ? "active" : ""}`} href="/store/track" aria-label="Track an order">
              <PackageSearch size={17}/><span>Track order</span>
            </Link>
            <Link className={`store-track-link ${pathname?.startsWith("/store/account") ? "active" : ""}`} href="/store/account" aria-label={account ? `Your account, ${account.name || account.email}` : "Sign in or create an account"}>
              <UserRound size={17}/><span>{account ? (account.name || "Account").split(" ")[0] : "Sign in"}</span>
            </Link>
            <button className="store-bag-button" onClick={() => setCartOpen(true)} aria-label={`Open shopping bag, ${cartCount} items`}>
              <ShoppingBag size={18}/><span>Bag</span><b>{cartCount}</b>
            </button>
          </div>
        </div>
      </header>

      {children}

      <footer className="store-footer">
        <div><BrandMark size={26}/><span>{settings?.storeName || "The Bookshop"}</span></div>
        <p className="store-footer-pay"><span>eSewa</span><span>Khalti</span><span>Bank transfer</span></p>
        <nav className="store-footer-links" aria-label="Bookstore">
          <Link href="/store">Shop</Link>
          <Link href="/store/track">Track an order</Link>
          <Link href="/store/account">{account ? "My account" : "Sign in"}</Link>
          {settings?.contactEmail && <a href={`mailto:${settings.contactEmail}`}>Contact</a>}
          <Link href="/">Portfolio <ArrowRight size={13}/></Link>
        </nav>
      </footer>

      {toast && <div className="store-toast" role="status">
        <ShoppingBag size={15}/><span>{toast}</span>
        <button onClick={() => { setToast(""); setCartOpen(true); }}>View bag</button>
      </div>}

      {cartOpen && <CartDrawer
        items={cartItems} count={cartCount} subtotal={subtotal}
        onClose={() => setCartOpen(false)} onQuantity={changeQuantity} onCheckout={startCheckout}
      />}

      {checkoutOpen && <CheckoutDialog
        items={cartItems} count={cartCount} subtotal={subtotal} settings={settings} account={account}
        onClose={() => setCheckoutOpen(false)}
        onPlaced={orderId => {
          rememberOrder(orderId);
          setCart([]);
          setCheckoutOpen(false);
          router.push(`/store/orders/${orderId}?placed=1`);
        }}
        onRefreshCatalog={loadCatalog}
      />}
    </main>
  </StoreContext.Provider>;
}

function CartDrawer({ items, count, subtotal, onClose, onQuantity, onCheckout }) {
  return <div className="store-overlay store-drawer-overlay" role="presentation" onMouseDown={event => event.target === event.currentTarget && onClose()}>
    <aside className="store-cart-drawer" role="dialog" aria-modal="true" aria-labelledby="store-cart-title">
      <div className="store-drawer-heading">
        <div><span className="store-eyebrow">YOUR READING LIST</span><h2 id="store-cart-title">Shopping bag <small>({count})</small></h2></div>
        <button className="store-modal-close" onClick={onClose} aria-label="Close bag"><X size={18}/></button>
      </div>
      {items.length ? <>
        <div className="store-cart-items">{items.map(item => <article className="store-cart-item" key={item.bookId}>
          <Link href={`/store/books/${item.bookId}`} onClick={onClose}><img src={item.book.image} alt=""/></Link>
          <div className="store-cart-item-copy">
            <Link href={`/store/books/${item.bookId}`} onClick={onClose}><strong>{item.book.title}</strong></Link>
            <small>{formatNpr(item.book.priceNpr)} each</small>
            <div className="store-quantity">
              <button aria-label={`Remove one ${item.book.title}`} onClick={() => onQuantity(item.book, item.quantity - 1)}><Minus size={13}/></button>
              <span aria-live="polite">{item.quantity}</span>
              <button aria-label={`Add one ${item.book.title}`} disabled={item.quantity >= Math.min(item.book.stock, 20)} onClick={() => onQuantity(item.book, item.quantity + 1)}><Plus size={13}/></button>
            </div>
          </div>
          <div className="store-cart-item-side">
            <button className="store-remove-item" aria-label={`Remove ${item.book.title}`} onClick={() => onQuantity(item.book, 0)}><X size={15}/></button>
            <strong>{formatNpr(Number(item.book.priceNpr) * item.quantity)}</strong>
          </div>
        </article>)}</div>
        <div className="store-cart-total"><span>Subtotal</span><strong>{formatNpr(subtotal)}</strong></div>
        <p className="store-cart-shipping">Delivery details are collected at checkout. Stock is reserved when you place your order.</p>
        <button className="store-checkout-button" onClick={onCheckout}>Continue to checkout <ArrowRight size={15}/></button>
        <div className="store-secure-note"><Lock size={13}/> Payments are verified securely on our server.</div>
      </> : <div className="store-cart-empty">
        <ShoppingBag size={28}/>
        <strong>Your bag is taking a quiet moment.</strong>
        <span>Add a book to get started.</span>
        <button onClick={onClose}>Continue browsing</button>
      </div>}
    </aside>
  </div>;
}

const paymentOptions = [
  ["esewa", "esewaEnabled", Wallet, "Pay instantly from your eSewa wallet"],
  ["khalti", "khaltiEnabled", Wallet, "Pay with Khalti wallet, mobile banking or cards"],
  ["bank_transfer", "bankTransferEnabled", Landmark, "Transfer to our bank account; confirmed after we verify it"]
];

function CheckoutDialog({ items, count, subtotal, settings, account, onClose, onPlaced, onRefreshCatalog }) {
  const saved = useMemo(() => readStorage(CUSTOMER_KEY, null), []);
  const [customer, setCustomer] = useState(() => {
    const base = { ...emptyCustomer, ...(saved && typeof saved === "object" ? saved : {}) };
    if (!account) return base;
    // Account details win over device-saved ones; the email is fixed to the verified address.
    return { ...base, ...Object.fromEntries(["name", "phone", "address"].filter(key => account[key]).map(key => [key, account[key]])), email: account.email };
  });
  const [remember, setRemember] = useState(Boolean(saved));
  const available = useMemo(() => paymentOptions.filter(([, flag]) => settings?.[flag]).map(([method]) => method), [settings]);
  const [paymentMethod, setPaymentMethod] = useState(available[0] || "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!available.includes(paymentMethod)) setPaymentMethod(available[0] || "");
  }, [available, paymentMethod]);

  function update(field) {
    return event => setCustomer(current => ({ ...current, [field]: event.target.value }));
  }

  async function submit(event) {
    event.preventDefault();
    if (!available.includes(paymentMethod)) {
      setError("No payment method is configured yet. Please contact the bookstore.");
      return;
    }
    setSubmitting(true);
    setError("");
    const payload = {
      customer: Object.fromEntries(Object.keys(emptyCustomer).map(key => [key, String(customer[key] || "").trim()])),
      items: items.map(item => ({ bookId: item.bookId, quantity: item.quantity }))
    };
    writeStorage(CUSTOMER_KEY, remember ? payload.customer : null);
    try {
      if (paymentMethod === "bank_transfer") {
        const result = await requestJson("/api/orders/bank-transfer", { method: "POST", body: JSON.stringify(payload) });
        onPlaced(result.orderId);
        return;
      }
      const result = await requestJson(`/api/payments/nepal/${paymentMethod}/initiate`, { method: "POST", body: JSON.stringify(payload) });
      rememberOrder(result.orderId);
      if (paymentMethod === "khalti") {
        const checkoutUrl = new URL(result.paymentUrl);
        if (checkoutUrl.protocol !== "https:" || !["khalti.com", "pay.khalti.com", "dev.khalti.com", "test-pay.khalti.com"].includes(checkoutUrl.hostname)) {
          throw new Error("The payment provider returned an unexpected checkout address.");
        }
        window.location.assign(checkoutUrl.toString());
        return;
      }
      const actionUrl = new URL(result.action);
      if (actionUrl.protocol !== "https:" || !["epay.esewa.com.np", "rc-epay.esewa.com.np"].includes(actionUrl.hostname) || actionUrl.pathname !== "/api/epay/main/v2/form") {
        throw new Error("The payment provider returned an unexpected checkout address.");
      }
      const form = document.createElement("form");
      form.method = "POST";
      form.action = actionUrl.toString();
      form.hidden = true;
      for (const [name, value] of Object.entries(result.fields || {})) {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = name;
        input.value = String(value);
        form.append(input);
      }
      document.body.append(form);
      form.submit();
    } catch (requestError) {
      setError(requestError.message || "Checkout could not be started.");
      if (requestError.status === 409 || requestError.status === 400) onRefreshCatalog();
      setSubmitting(false);
    }
  }

  return <div className="store-overlay" role="presentation" onMouseDown={event => event.target === event.currentTarget && !submitting && onClose()}>
    <section className="store-checkout-dialog store-checkout-wide" role="dialog" aria-modal="true" aria-labelledby="store-checkout-title">
      <div className="store-drawer-heading">
        <div><span className="store-eyebrow">A SECURE, SIMPLE CHECKOUT</span><h2 id="store-checkout-title">Checkout</h2></div>
        <button className="store-modal-close" onClick={onClose} disabled={submitting} aria-label="Close checkout"><X size={18}/></button>
      </div>
      <form className="store-checkout-layout" onSubmit={submit}>
        <div className="store-checkout-form">
          <span className="store-step-label"><b>1</b> Delivery details</span>
          <div className="store-checkout-fields">
            <label>Full name<input name="name" autoComplete="name" maxLength={160} required value={customer.name} onChange={update("name")}/></label>
            <label>Email<input name="email" type="email" autoComplete="email" maxLength={320} required value={account ? account.email : customer.email} readOnly={Boolean(account)} onChange={update("email")}/></label>
            <label>Phone<input name="phone" type="tel" autoComplete="tel" maxLength={32} value={customer.phone} onChange={update("phone")} placeholder="98XXXXXXXX"/></label>
            <label className="store-field-wide">Delivery address<textarea name="address" autoComplete="street-address" rows={3} minLength={5} maxLength={500} required value={customer.address} onChange={update("address")} placeholder="Street, tole, municipality, district"/></label>
          </div>
          {account ? <p className="store-signed-in"><UserRound size={13}/> Signed in as {account.email}. This order will appear in <Link href="/store/account" onClick={onClose}>your account</Link>.</p>
            : <p className="store-signed-in"><UserRound size={13}/> <Link href="/store/account" onClick={onClose}>Sign in or create an account</Link> to keep all your orders in one place, or continue as a guest.</p>}
          <label className="store-remember"><input type="checkbox" checked={remember} onChange={event => setRemember(event.target.checked)}/> Remember these details on this device</label>

          <div className="store-payment-options">
            <span className="store-step-label"><b>2</b> Payment method</span>
            {paymentOptions.map(([value, flag, Icon, note]) => {
              const enabled = Boolean(settings?.[flag]);
              return <label key={value} className={`store-payment-option ${!enabled ? "unavailable" : ""} ${paymentMethod === value ? "selected" : ""}`}>
                <input type="radio" name="payment" value={value} disabled={!enabled} checked={paymentMethod === value} onChange={() => setPaymentMethod(value)}/>
                <span className={`store-payment-logo store-payment-logo-${value}`}><Icon size={16}/></span>
                <span><strong>{PAYMENT_LABELS[value]}</strong><small>{enabled ? note : "Not available yet"}</small></span>
              </label>;
            })}
          </div>
        </div>

        <aside className="store-checkout-aside">
          <span className="store-eyebrow">ORDER SUMMARY</span>
          <ul className="store-summary-items">{items.map(item => <li key={item.bookId}>
            <img src={item.book.image} alt=""/>
            <span><strong>{item.book.title}</strong><small>Qty {item.quantity} × {formatNpr(item.book.priceNpr)}</small></span>
            <b>{formatNpr(Number(item.book.priceNpr) * item.quantity)}</b>
          </li>)}</ul>
          <div className="store-summary-row"><span>Subtotal ({count} {count === 1 ? "book" : "books"})</span><span>{formatNpr(subtotal)}</span></div>
          <div className="store-summary-row store-summary-total"><span>Total</span><strong>{formatNpr(subtotal)}</strong></div>
          {error && <div className="store-alert" role="alert">{error}</div>}
          <button className="store-checkout-button" disabled={submitting || !items.length || !paymentMethod}>
            {submitting ? "Connecting securely…" : paymentMethod === "bank_transfer" ? "Place order" : `Pay with ${PAYMENT_LABELS[paymentMethod] || "…"}`} <ArrowRight size={15}/>
          </button>
          <div className="store-secure-note"><ShieldCheck size={15}/> Prices and stock are checked on our server, and every payment is verified with the provider before your order is confirmed.</div>
        </aside>
      </form>
    </section>
  </div>;
}
