"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, ArrowLeft, ArrowRight, BookOpen, Check, Eye, Home, Image, Settings,
  LayoutDashboard, LogOut, Mail, Pencil, Plus, RefreshCw, Search, Shield,
  Trash2, Users, X, ShoppingCart, ClipboardList, CreditCard, BarChart3, Store, Tag, Power, DatabaseBackup
} from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import BrandMark from "../brand-mark";

// Panels are split into their own chunks so the sign-in screen and each tab load only the code they use.
const panelLoading = () => <div className="admin-empty">Loading…</div>;
const MaintenancePanel = dynamic(() => import("./maintenance-panel"), { loading: panelLoading });
const BackupPanel = dynamic(() => import("./backup-panel"), { loading: panelLoading });
const NotificationBell = dynamic(() => import("./store-panels").then(module => module.NotificationBell));
const StoreDashboard = dynamic(() => import("./store-panels").then(module => module.StoreDashboard), { loading: panelLoading });
const SalesPanel = dynamic(() => import("./store-panels").then(module => module.SalesPanel), { loading: panelLoading });
const OrdersPanel = dynamic(() => import("./store-panels").then(module => module.OrdersPanel), { loading: panelLoading });
const PaymentsPanel = dynamic(() => import("./store-panels").then(module => module.PaymentsPanel), { loading: panelLoading });
const InventoryPanel = dynamic(() => import("./store-panels").then(module => module.InventoryPanel), { loading: panelLoading });
const CategoriesPanel = dynamic(() => import("./store-panels").then(module => module.CategoriesPanel), { loading: panelLoading });
const CustomersPanel = dynamic(() => import("./store-panels").then(module => module.CustomersPanel), { loading: panelLoading });

const API = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/+$/, "");
const tabs = [
  { key: "overview", label: "Portfolio overview", icon: LayoutDashboard, permission: "analytics:read", group: "PORTFOLIO" },
  { key: "home", label: "Home page", icon: Home, permission: "content:read", group: "PORTFOLIO" },
  { key: "about", label: "About page", icon: BookOpen, permission: "content:read", group: "PORTFOLIO" },
  { key: "contact", label: "Contact page", icon: Mail, permission: "content:read", group: "PORTFOLIO" },
  { key: "settings", label: "Site settings & SEO", icon: Settings, permission: "content:read", group: "PORTFOLIO" },
  { key: "books", label: "Published works", icon: BookOpen, permission: "books:read", group: "PORTFOLIO" },
  { key: "gallery", label: "Gallery", icon: Image, permission: "media:read", group: "PORTFOLIO" },
  { key: "store-dashboard", label: "Store dashboard", icon: Store, permission: "orders:read", group: "BOOKSTORE" },
  { key: "store-orders", label: "Orders", icon: ClipboardList, permission: "orders:read", group: "BOOKSTORE" },
  { key: "store-payments", label: "Payments", icon: CreditCard, permission: "payments:read", group: "BOOKSTORE" },
  { key: "store-books", label: "Inventory & prices", icon: ShoppingCart, permission: "books:read", group: "BOOKSTORE" },
  { key: "store-categories", label: "Categories", icon: Tag, permission: "books:read", group: "BOOKSTORE" },
  { key: "store-customers", label: "Customers", icon: Users, permission: "customers:read", group: "BOOKSTORE" },
  { key: "sales", label: "Sales reports", icon: BarChart3, permission: "orders:read", group: "BOOKSTORE" },
  { key: "store-settings", label: "Store & bank settings", icon: Settings, permission: "settings:read", group: "BOOKSTORE" },
  { key: "maintenance", label: "Maintenance mode", icon: Power, permission: "settings:read", group: "ADMINISTRATION" },
  { key: "backup", label: "Backup & restore", icon: DatabaseBackup, permission: "backup:manage", group: "ADMINISTRATION" },
  { key: "team", label: "Team / Roles", icon: Shield, permission: "users:manage", group: "ADMINISTRATION" },
  { key: "audit", label: "Activity log", icon: Activity, permission: "users:manage", group: "ADMINISTRATION" }
];
// Tabs whose panels fetch their own data and reload when refreshKey changes.
const selfLoadingTabs = new Set(["store-dashboard", "store-categories", "sales", "maintenance", "backup"]);

const pageFields = {
  home: [
    ["role", "Author byline", "text"], ["heroLead", "Hero opening", "text"],
    ["heroEmphasis", "Hero emphasis", "text"], ["heroDescription", "Hero introduction", "textarea"],
    ["portrait", "Author portrait image URL", "url"], ["landscape", "Home-page landscape image URL", "url"],
    ["quote", "Featured quote", "textarea"]
  ],
  about: [
    ["name", "Author name", "text"], ["location", "Location", "text"],
    ["aboutHeading", "About introduction", "text"], ["aboutBiography", "Short biography", "textarea"],
    ["aboutPageTitle", "About page heading", "text"], ["aboutPageBiography", "Full biography", "textarea"],
    ["portrait", "Author portrait image URL", "url"]
  ],
  contact: [
    ["email", "Public contact email", "email"], ["location", "Location", "text"],
    ["instagram", "Instagram URL", "url"], ["facebook", "Facebook URL", "url"],
    ["linkedin", "LinkedIn URL", "url"],
    ["tiktok", "TikTok URL", "url"], ["youtube", "YouTube URL", "url"],
    ["threads", "Threads URL", "url"]
  ],
  settings: [
    ["siteTitle", "Site title", "text"], ["seoTitle", "SEO title", "text"],
    ["seoDescription", "SEO description", "textarea"], ["ogImage", "Social sharing image URL", "url"]
  ]
};

const resources = {
  books: {
    list: "/books", key: "books", id: "_id", write: "books:write",
    fields: [
      ["title", "Title", "text", true], ["subtitle", "Subtitle", "text"], ["description", "Description", "textarea", true],
      ["image", "Cover image URL", "url", true], ["format", "Type of work", "text"], ["year", "Publication year", "number"],
      ["category", "Store category", "category"], ["priceNpr", "Price (NPR)", "number"], ["stock", "Inventory", "number"],
      ["status", "Publication status", "select", true, ["draft", "published"]]
    ]
  },
  media: {
    list: "/media", key: "media", id: "_id", write: "media:write",
    fields: [
      ["title", "Asset name", "text", true], ["url", "Image URL (HTTPS)", "url", true],
      ["altText", "Alternative text", "text"], ["category", "Category", "select", true, ["author", "book-cover", "site", "gallery", "other"]],
      ["public", "Show in public gallery", "checkbox"], ["notes", "Notes", "textarea"]
    ]
  },
  content: {
    list: "/content", key: "content", id: "key", write: "content:write",
    fields: [["key", "Page key (e.g. author-profile)", "text", true], ["value", "Page content (JSON object)", "textarea", true], ["public", "Visible publicly", "checkbox"]]
  },
  users: {
    list: "/users", key: "users", id: "_id", write: "users:manage",
    fields: [["email", "Email", "email", true], ["password", "Temporary password (12+ characters)", "password", true], ["role", "Role", "select", true, ["admin", "manager", "editor", "support"]], ["active", "Account active", "checkbox"]]
  },
  customers: {
    list: "/customers", key: "customers", id: "_id", write: "customers:write",
    fields: [
      ["name", "Customer name", "text", true], ["email", "Email", "email", true],
      ["phone", "Phone", "tel"], ["address", "Shipping address", "textarea"],
      ["notes", "Customer notes", "textarea"]
    ]
  }
};

const resourceForTab = (selectedTab) => ({
  team: "users",
  gallery: "media",
  "store-books": "books",
  "store-customers": "customers"
}[selectedTab] || selectedTab);

const display = (value) => {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return value.title || value.email || value._id || JSON.stringify(value);
  return String(value);
};

export default function AdminPage() {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);
  const [tab, setTab] = useState("overview");
  const [rows, setRows] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [storeSettings, setStoreSettings] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editing, setEditing] = useState(null);
  const [viewing, setViewing] = useState(null);
  const [login, setLogin] = useState({ email: "", password: "" });
  const [authMode, setAuthMode] = useState("login");
  const [verificationCode, setVerificationCode] = useState("");
  const [resetCode, setResetCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [focusOrderId, setFocusOrderId] = useState(null);
  const [categoryOptions, setCategoryOptions] = useState([]);
  const [lowStockThreshold, setLowStockThreshold] = useState(5);
  const [maintenanceOn, setMaintenanceOn] = useState(false);

  const api = useCallback(async (path, options = {}) => {
    const response = await fetch(`${API}/api/admin${path}`, {
      ...options,
      credentials: "include",
      headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers }
    });
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
    return data;
  }, []);

  const loadSession = useCallback(async () => {
    setChecking(true);
    try {
      const result = await api("/auth/me");
      setUser(result.user);
      if (!result.user.permissions.includes("*") && !result.user.permissions.includes("analytics:read")) {
        setTab(tabs.find(item => result.user.permissions.includes(item.permission))?.key || "books");
      }
      setError("");
    } catch (requestError) {
      if (!/sign in|expired|inactive/i.test(requestError.message)) setError(requestError.message);
    } finally {
      setChecking(false);
    }
  }, [api]);

  const loadCategoryOptions = useCallback(async () => {
    try {
      const result = await api("/categories");
      setCategoryOptions([...(result.categories || []).map(item => item.name), ...(result.unmanaged || []).map(item => item.name)]);
    } catch {
      // Category suggestions are optional; the field still accepts free text.
    }
  }, [api]);

  const loadTab = useCallback(async (selectedTab) => {
    if (!user) return;
    if (selfLoadingTabs.has(selectedTab)) {
      setRefreshKey(key => key + 1);
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (["books", "store-books"].includes(selectedTab)) loadCategoryOptions();
      if (selectedTab === "store-books" && (user.permissions.includes("*") || user.permissions.includes("settings:read"))) {
        api("/settings").then(result => setLowStockThreshold(result.settings?.lowStockThreshold ?? 5)).catch(() => {});
      }
      if (selectedTab === "overview") {
        // Both summaries are independent, so they are requested together.
        const [result, store] = await Promise.all([
          api("/analytics"),
          user.permissions.includes("*") ? api("/store/analytics") : null
        ]);
        setAnalytics(store ? { ...result, ...store } : result);
      } else if (selectedTab === "store-settings") {
        const result = await api("/settings");
        setStoreSettings(result.settings);
      } else {
        const contentPage = ["home", "about", "contact", "settings"].includes(selectedTab);
        const resourceTab = resourceForTab(selectedTab);
        const config = contentPage ? { list: "/content", key: "content" }
          : selectedTab === "audit" ? { list: "/audit", key: "events" }
          : selectedTab === "store-orders" ? { list: "/orders", key: "orders" }
          : selectedTab === "store-payments" ? { list: "/payments", key: "payments" }
          : { list: resources[resourceTab].list, key: resources[resourceTab].key };
        const result = await api(config.list);
        setRows(result[config.key] || []);
      }
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }, [api, user, loadCategoryOptions]);

  useEffect(() => { loadSession(); }, [loadSession]);
  useEffect(() => {
    if (!user || !(user.permissions.includes("*") || user.permissions.includes("settings:read"))) return;
    api("/maintenance").then(result => setMaintenanceOn(Boolean(result.maintenance?.enabled))).catch(() => {});
  }, [user, api]);
  useEffect(() => { if (user) loadTab(tab); }, [tab, user, loadTab]);

  const visibleTabs = useMemo(() => tabs.filter(item =>
    user?.permissions?.includes("*") || user?.permissions?.includes(item.permission)
  ), [user]);

  async function submitLogin(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/api/admin/auth/login`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(login)
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Could not sign in.");
      setUser(result.user);
      setLogin({ email: login.email, password: "" });
      setTab(result.user.permissions.includes("*") || result.user.permissions.includes("analytics:read")
        ? "overview"
        : tabs.find(item => result.user.permissions.includes(item.permission))?.key || "books");
      setNotice("");
    } catch (requestError) {
      setError(requestError.message || "The API could not be reached. Check the server and try again.");
    } finally {
      setBusy(false);
    }
  }

  async function submitAdminAuth(event, path, payload, onSuccess) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(`${API}/api/admin/auth${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || `Request failed (${response.status}).`);
      onSuccess(result);
    } catch (requestError) {
      setError(requestError.message || "The API could not be reached. Check the server and try again.");
    } finally {
      setBusy(false);
    }
  }

  function requestEmailVerification(event) {
    return submitAdminAuth(event, "/email/request", login, result => {
      if (result.verified) {
        setAuthMode("login");
        setNotice(result.message);
        return;
      }
      setAuthMode("verify");
      setVerificationCode("");
      setNotice("If your admin email needs verification, a code has been sent to it.");
    });
  }

  function verifyAdminEmail(event) {
    return submitAdminAuth(event, "/email/verify", { email: login.email, code: verificationCode }, () => {
      setAuthMode("login");
      setVerificationCode("");
      setNotice("Your admin email is verified. You can now sign in.");
    });
  }

  function requestPasswordReset(event) {
    return submitAdminAuth(event, "/password/request", { email: login.email }, () => {
      setAuthMode("reset");
      setResetCode("");
      setNewPassword("");
      setNotice("If an active admin account matches that email, a reset code has been sent.");
    });
  }

  function resetAdminPassword(event) {
    return submitAdminAuth(event, "/password/reset", {
      email: login.email,
      code: resetCode,
      password: newPassword
    }, () => {
      setAuthMode("login");
      setLogin(current => ({ ...current, password: "" }));
      setResetCode("");
      setNewPassword("");
      setNotice("Your password was reset. Sign in with your new password.");
    });
  }

  async function logout() {
    try { await api("/auth/logout", { method: "POST" }); }
    catch (requestError) { setError(requestError.message); }
    setUser(null);
    setRows([]);
    setAnalytics(null);
  }

  async function saveRecord(event) {
    event.preventDefault();
    const resourceTab = resourceForTab(tab);
    const config = resources[resourceTab];
    if (!config) return;
    const form = new FormData(event.currentTarget);
    const payload = {};
    for (const [name, , type] of config.fields) {
      if (type === "checkbox") {
        payload[name] = form.get(name) === "on";
        continue;
      }
      const value = form.get(name);
      if (value === null || value === "") continue;
      if (type === "number") payload[name] = Number(value);
      else if (resourceTab === "content" && name === "value") {
        try { payload[name] = JSON.parse(String(value)); }
        catch { throw new Error("Content value must be valid JSON."); }
      } else payload[name] = value;
    }
    if (resourceTab === "users" && editing?.[config.id]) delete payload.password;
    const recordId = editing?.[config.id];
    const isContentCreate = resourceTab === "content" && !recordId;
    const path = isContentCreate
      ? `/content/${encodeURIComponent(payload.key)}`
      : `${config.list}/${encodeURIComponent(recordId || "")}`;
    const method = isContentCreate ? "PUT" : recordId ? "PATCH" : "POST";
    if (resourceTab === "content" && recordId) {
      const key = editing.key;
      delete payload.key;
      await api(`/content/${encodeURIComponent(key)}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      if (resourceTab === "content") {
        delete payload.key;
        await api(path, { method, body: JSON.stringify({ value: payload.value, public: payload.public }) });
      } else {
        await api(path, { method, body: JSON.stringify(payload) });
      }
    }
    setEditing(null);
    setNotice("Changes saved.");
    await loadTab(tab);
  }

  async function deleteRecord(record) {
    if (!window.confirm("Delete this record? This action cannot be undone.")) return;
    const resourceTab = resourceForTab(tab);
    const config = resources[resourceTab];
    const id = record[config.id];
    const path = resourceTab === "content" ? `/content/${encodeURIComponent(id)}` : `${config.list}/${encodeURIComponent(id)}`;
    try {
      await api(path, { method: "DELETE" });
      setNotice("Record deleted.");
      await loadTab(tab);
    } catch (requestError) { setError(requestError.message); }
  }

  async function togglePublish(record) {
    const resourceTab = resourceForTab(tab);
    const config = resources[resourceTab];
    const next = resourceTab === "media"
      ? { public: !record.public }
      : { status: record.status !== "draft" ? "draft" : "published" };
    setBusy(true);
    setError("");
    try {
      await api(`${config.list}/${encodeURIComponent(record[config.id])}`, {
        method: "PATCH",
        body: JSON.stringify(next)
      });
      setNotice(resourceTab === "media"
        ? `Gallery image ${next.public ? "published" : "hidden"}.`
        : `${record.title || "Published work"} ${next.status === "published" ? "published" : "unpublished"}.`);
      await loadTab(tab);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  const openOrder = useCallback(orderId => {
    setFocusOrderId(orderId);
    setTab("store-orders");
    setError("");
    setNotice("");
  }, []);

  const showError = useCallback(message => setError(message), []);
  const clearFocusOrder = useCallback(() => setFocusOrderId(null), []);

  async function exportOrders() {
    setError("");
    try {
      const response = await fetch(`${API}/api/admin/orders/export`, { credentials: "include" });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `Export failed (${response.status}).`);
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `orders-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function saveStoreSettings(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = Object.fromEntries([...form.entries()].map(([key, value]) => [
      key,
      key === "lowStockThreshold" ? Number(value) : String(value).trim()
    ]));
    try {
      const result = await api("/settings", { method: "PUT", body: JSON.stringify(payload) });
      setStoreSettings(result.settings);
      setNotice("Store settings saved.");
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function savePageContent(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const key = tab === "settings" ? "site-settings" : "author-profile";
    const stored = rows.find(item => item.key === key);
    const profile = stored?.value && typeof stored.value === "object" && !Array.isArray(stored.value) ? { ...stored.value } : {};
    for (const [name] of pageFields[tab]) {
      if (!form.has(name)) continue;
      const value = String(form.get(name) || "").trim();
      if (value) profile[name] = value;
      else delete profile[name];
    }
    setBusy(true);
    setError("");
    try {
      await api(`/content/${key}`, { method: "PUT", body: JSON.stringify({ value: profile, public: true }) });
      setNotice(`${tabs.find(item => item.key === tab)?.label} content saved.`);
      await loadTab(tab);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function deletePageContent(key = "author-profile") {
    if (!window.confirm("Remove this public content override? The portfolio will fall back to its built-in defaults.")) return;
    try {
      await api(`/content/${key}`, { method: "DELETE" });
      setNotice("Public content override removed.");
      await loadTab(tab);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  if (checking) return <main className="admin-login-page"><div className="admin-login-card">Opening the Admin Panel…</div></main>;

  if (!user) return <main className="admin-login-page">
    <Link href="/" className="admin-back"><ArrowLeft size={15}/> Back to the portfolio</Link>
    <div className="admin-login-card">
      <div className="admin-logo"><BrandMark size={34}/><span>ADMIN PANEL</span></div>
      <div className="eyebrow">Private access</div>
      <h1 className="serif">{authMode === "login" ? "Welcome back." : authMode === "verify" ? "Verify your email." : authMode === "reset" ? "Reset your password." : authMode === "forgot" ? "Forgot your password?" : "Verify your email."}</h1>
      <p>{authMode === "login"
        ? <>Sign in with the admin email and password set in <code>server/.env</code>. This is not your Gmail password.</>
        : authMode === "verify"
          ? <>Enter the six-digit verification code sent to your admin email address.</>
          : authMode === "reset"
            ? <>Enter the six-digit reset code sent to your admin email address and choose a new password.</>
            : authMode === "forgot"
              ? <>Request a one-time password reset code for your admin email address.</>
              : <>Confirm your admin email address with the password configured for your account.</>}
      </p>
      {error && <div className="admin-error" role="alert">{error}</div>}
      {notice && <div className="admin-notice" role="status">{notice}</div>}

      {authMode === "login" && <form className="admin-auth-form" onSubmit={submitLogin}>
        <label className="field">Email address<input type="email" autoComplete="username" required value={login.email} onChange={event=>setLogin({...login,email:event.target.value})}/></label>
        <label className="field">Password<input type={showPassword?"text":"password"} autoComplete="current-password" required value={login.password} onChange={event=>setLogin({...login,password:event.target.value})}/></label>
        <label className="admin-check"><input type="checkbox" checked={showPassword} onChange={event=>setShowPassword(event.target.checked)}/> Show password</label>
        <button className="button" type="submit" disabled={busy}>{busy?"Signing in…":"Sign in securely"} <Shield size={14}/></button>
        <div className="admin-auth-actions">
          <button type="button" className="admin-auth-link" onClick={()=>{setAuthMode("verify-request");setError("");setNotice("");}}>Verify your email</button>
          <button type="button" className="admin-auth-link" onClick={()=>{setAuthMode("forgot");setError("");setNotice("");}}>Forgot password?</button>
        </div>
        <small>Protected with a server-side, HttpOnly session cookie.</small>
      </form>}

      {authMode === "verify-request" && <form className="admin-auth-form" onSubmit={requestEmailVerification}>
        <label className="field">Email address<input type="email" autoComplete="username" required value={login.email} onChange={event=>setLogin({...login,email:event.target.value})}/></label>
        <label className="field">Password<input type={showPassword?"text":"password"} autoComplete="current-password" required value={login.password} onChange={event=>setLogin({...login,password:event.target.value})}/></label>
        <label className="admin-check"><input type="checkbox" checked={showPassword} onChange={event=>setShowPassword(event.target.checked)}/> Show password</label>
        <button className="button" type="submit" disabled={busy}>{busy?"Sending code…":"Send verification code"} <Mail size={14}/></button>
        <button type="button" className="admin-auth-link" onClick={()=>{setAuthMode("login");setError("");}}>Back to sign in</button>
      </form>}

      {authMode === "verify" && <form className="admin-auth-form" onSubmit={verifyAdminEmail}>
        <label className="field">Verification code<input type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required value={verificationCode} onChange={event=>setVerificationCode(event.target.value.replace(/\D/g,"").slice(0,6))}/></label>
        <button className="button" type="submit" disabled={busy}>{busy?"Verifying…":"Verify email"} <Shield size={14}/></button>
        <button type="button" className="admin-auth-link" onClick={()=>{setAuthMode("verify-request");setError("");setNotice("");}}>Send another code</button>
      </form>}

      {authMode === "forgot" && <form className="admin-auth-form" onSubmit={requestPasswordReset}>
        <label className="field">Admin email address<input type="email" autoComplete="username" required value={login.email} onChange={event=>setLogin({...login,email:event.target.value})}/></label>
        <button className="button" type="submit" disabled={busy}>{busy?"Sending code…":"Send reset code"} <Mail size={14}/></button>
        <button type="button" className="admin-auth-link" onClick={()=>{setAuthMode("login");setError("");}}>Back to sign in</button>
      </form>}

      {authMode === "reset" && <form className="admin-auth-form" onSubmit={resetAdminPassword}>
        <label className="field">Reset code<input type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required value={resetCode} onChange={event=>setResetCode(event.target.value.replace(/\D/g,"").slice(0,6))}/></label>
        <label className="field">New password<input type="password" autoComplete="new-password" minLength={12} maxLength={128} required value={newPassword} onChange={event=>setNewPassword(event.target.value)}/></label>
        <button className="button" type="submit" disabled={busy}>{busy?"Resetting…":"Reset password"} <Shield size={14}/></button>
        <button type="button" className="admin-auth-link" onClick={()=>{setAuthMode("forgot");setError("");setNotice("");}}>Request another code</button>
      </form>}
    </div>
  </main>;

  const currentTab = tabs.find(item => item.key === tab);
  const resourceTab = resourceForTab(tab);
  const config = resources[resourceTab];
  const contentKey = tab === "settings" ? "site-settings" : "author-profile";
  const storedProfile = rows.find(item => item.key === contentKey)?.value;
  const canManageStore = user.permissions.includes("*") || user.permissions.includes("orders:read");
  const canWriteBooks = user.permissions.includes("*") || user.permissions.includes("books:write");

  return <main className="admin-shell">
    <aside className="admin-sidebar">
      <Link href="/" className="admin-sidebar-brand"><BrandMark size={34}/><span>ADMIN PANEL<small>AUTHOR PORTFOLIO</small></span></Link>
      <nav className="admin-side-nav">{visibleTabs.map((item, index) => {
        const Icon = item.icon;
        const groupStart = visibleTabs[index - 1]?.group !== item.group;
        return <span key={item.key} className="admin-side-item">{groupStart && <span className="admin-sidebar-label">{item.group}</span>}<button className={tab===item.key?"active":""} aria-current={tab===item.key?"page":undefined} onClick={()=>{setTab(item.key);setError("");setNotice("");}}><Icon size={16}/>{item.label}</button></span>;
      })}</nav>
      <div className="admin-side-bottom"><span className="admin-avatar">{user.email.slice(0,1).toUpperCase()}</span><div><strong>{user.email}</strong><small>{user.role}</small></div><button title="Sign out" aria-label="Sign out" onClick={logout}><LogOut size={15}/></button></div>
    </aside>
    <section className="admin-workspace">
      <header className="admin-topbar"><Link href="/" className="admin-store-link"><ArrowLeft size={14}/> View portfolio</Link><div className="admin-topbar-actions">{maintenanceOn && <button className="mt-badge" onClick={()=>{setTab("maintenance");setError("");setNotice("");}}><span aria-hidden="true"/>Maintenance ON</button>}<Link href="/store" className="admin-store-link" target="_blank">View store</Link>{canManageStore && <NotificationBell api={api} onOpenOrder={openOrder} onNavigate={key=>{setTab(key);setError("");setNotice("");}}/>}<span className="admin-mode"><i/> Protected admin session</span></div></header>
      <div className="admin-content">
        <div className="admin-page-heading"><div><div className="eyebrow">ADMIN PANEL · {user.role.toUpperCase()}</div><h1 className="serif">{currentTab?.label || "Admin Panel"}</h1></div><button className="admin-refresh" onClick={()=>loadTab(tab)} disabled={busy && !selfLoadingTabs.has(tab)}><RefreshCw size={15}/> Refresh</button></div>
        {error && <div className="admin-error" role="alert">{error}</div>}
        {notice && <div className="admin-notice"><Check size={15}/>{notice}<button onClick={()=>setNotice("")} aria-label="Dismiss"><X size={14}/></button></div>}
        {tab==="overview" && <AnalyticsPanel data={analytics}/>}
        {tab==="store-dashboard" && <StoreDashboard api={api} refreshKey={refreshKey} onNavigate={key=>{setTab(key);setNotice("");}} onOpenOrder={openOrder} onError={showError}/>}
        {tab==="sales" && <SalesPanel api={api} refreshKey={refreshKey} onError={showError} onExport={exportOrders}/>}
        {tab==="store-orders" && <OrdersPanel orders={rows} api={api} onChanged={()=>loadTab("store-orders")} focusOrderId={focusOrderId} onFocusHandled={clearFocusOrder} onNotice={setNotice} onExport={exportOrders}/>}
        {tab==="store-payments" && <PaymentsPanel payments={rows} api={api} onChanged={()=>loadTab("store-payments")} onNotice={setNotice}/>}
        {tab==="maintenance" && <MaintenancePanel key={refreshKey} api={api} canWrite={user.permissions.includes("*")||user.permissions.includes("settings:write")} onChange={setMaintenanceOn} onNotice={setNotice} onError={showError}/>}
        {tab==="backup" && <BackupPanel api={api} onNotice={setNotice} onError={showError} onRestored={()=>api("/maintenance").then(result=>setMaintenanceOn(Boolean(result.maintenance?.enabled))).catch(()=>{})}/>}
        {tab==="store-categories" && <CategoriesPanel api={api} refreshKey={refreshKey} canWrite={canWriteBooks} onNotice={setNotice} onError={showError} onCategoriesChanged={loadCategoryOptions}/>}
        {tab==="store-books" && <InventoryPanel books={rows} api={api} canWrite={canWriteBooks} threshold={lowStockThreshold} onAdd={()=>setEditing({})} onEdit={record=>setEditing(record)} onDelete={deleteRecord} onPublish={togglePublish} onChanged={()=>loadTab("store-books")} onNotice={setNotice}/>}
        {tab==="store-customers" && <CustomersPanel customers={rows} api={api} canWrite={user.permissions.includes("*")||user.permissions.includes("customers:write")} onAdd={()=>setEditing({})} onEdit={record=>setEditing(record)} onDelete={deleteRecord} onOpenOrder={openOrder}/>}
        {tab==="store-settings" && <StoreSettingsPanel settings={storeSettings} busy={busy} onSave={saveStoreSettings}/>}
        {["home","about","contact","settings"].includes(tab) && <PageContentPanel key={`${tab}-${JSON.stringify(storedProfile||{})}`} page={tab} profile={storedProfile} busy={busy} canWrite={user.permissions.includes("*")||user.permissions.includes("content:write")} onSave={savePageContent} onView={setViewing}/>}
        {tab==="audit" && <AuditPanel events={rows} onView={setViewing}/>}
        {["home","about","contact","settings"].includes(tab) && storedProfile && <div className="admin-content-help"><strong>Live content override</strong><span>Changes publish to the public site immediately. Removing this override restores the built-in defaults.</span><button className="admin-cancel" type="button" onClick={()=>deletePageContent(contentKey)}>Remove override</button></div>}
        {config && !["store-books","store-customers"].includes(tab) && <ResourcePanel tab={resourceTab} view={tab} config={config} rows={rows} canWrite={user.permissions.includes("*")||user.permissions.includes(config.write)} onAdd={()=>setEditing({})} onEdit={record=>setEditing(record)} onDelete={deleteRecord} onView={setViewing} onPublish={togglePublish}/>}
        {editing && config && <RecordDialog key={`${resourceTab}-${editing[config.id]||"new"}`} tab={resourceTab} config={config} record={editing} categoryOptions={categoryOptions} onClose={()=>setEditing(null)} onSave={saveRecord}/>}
        {viewing && <RecordViewDialog record={viewing} onClose={()=>setViewing(null)}/>}
      </div>
    </section>
  </main>;
}

function PageContentPanel({page,profile,busy,canWrite,onSave,onView}) {
  const [query,setQuery]=useState("");
  const fields=pageFields[page];
  const visibleFields=fields.filter(([name,label])=>`${name} ${label}`.toLowerCase().includes(query.toLowerCase()));
  const contentKey=page==="settings"?"site-settings":"author-profile";
  const heading=page==="settings"?"Search appearance & social sharing":`${tabs.find(item=>item.key===page)?.label} content`;
  return <section className="admin-panel">
    <div className="admin-panel-heading"><div><h2>{heading}</h2><span>{page==="settings"?"Set the browser title, search description, and social-sharing image.":"Changes update the public author profile without changing the site layout."}</span></div></div>
    <form className="admin-page-editor" onSubmit={onSave}>
      <label className="admin-search"><Search size={15}/><input aria-label="Find page fields" placeholder="Find a content field…" value={query} onChange={event=>setQuery(event.target.value)}/></label>
      <div className="admin-dialog-fields">{visibleFields.map(([name,label,type])=><label key={name} className={`field ${type==="textarea"?"full":""}`}>{label}{type==="textarea"?<textarea name={name} rows={4} defaultValue={profile?.[name]||""} maxLength={name==="seoDescription"?320:5000} disabled={!canWrite}/>:<input name={name} type={type} defaultValue={profile?.[name]||""} maxLength={type==="url"?2048:name==="siteTitle"||name==="seoTitle"?120:5000} disabled={!canWrite}/>}</label>)}</div>
      {visibleFields.length===0&&<div className="admin-empty">No fields match that search.</div>}
      <div className="admin-page-editor-footer"><span>{canWrite?(profile?"Published changes are live on the public site.":"No override yet; saving creates the public content."):"Read-only access for your role."}</span><div className="admin-page-editor-actions">{profile&&<button type="button" className="admin-cancel" onClick={()=>onView({key:contentKey,public:true,value:profile})}>View saved content</button>}{canWrite&&<button className="button" disabled={busy}>{busy?"Saving…":"Save and publish"}</button>}</div></div>
      {page==="home"&&profile?.portrait&&<div className="admin-image-preview"><span>Current portrait preview</span><img src={profile.portrait} alt={profile.name?`${profile.name} portrait`: "Current author portrait"}/></div>}
      {page==="settings"&&profile?.ogImage&&<div className="admin-image-preview"><span>Social-sharing image preview</span><img src={profile.ogImage} alt="Current social-sharing image"/></div>}
    </form>
  </section>;
}

function AnalyticsPanel({data}) {
  if (!data) return <div className="admin-empty">Loading portfolio overview…</div>;
  const statCards = [
    ["Published works", data.books || 0, "Books and essays in the bibliography"],
    ["Gallery images", data.gallery || 0, "Images shared on the portfolio"],
    ["Team members", data.team || 0, "Active content contributors"],
    ...(data.revenueNpr !== undefined ? [
      ["Store sales", formatNpr(data.revenueNpr), "Confirmed bookstore payments"],
      ["Open orders", data.pendingOrders || 0, "Orders awaiting payment"]
    ] : [])
  ];
  return <><div className="admin-stat-grid">{statCards.map(([title,value,note])=><article className="admin-stat" key={title}><span>{title}</span><strong>{value}</strong><small>{note}</small></article>)}</div>{<section className="admin-panel"><div className="admin-panel-heading"><h2>Your author portfolio & bookstore</h2><span>Content at a glance</span></div><p className="admin-overview-note">Update your biography and home page, publish new writing, manage your bibliography, curate the public gallery, and keep an eye on bookstore orders and sales.</p></section>}</>;
}

function formatNpr(value) {
  return `NPR ${Number(value || 0).toLocaleString("en-NP", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function StoreSettingsPanel({settings,busy,onSave}) {
  if(!settings)return <div className="admin-empty">Loading bookstore settings…</div>;
  return <section className="admin-panel">
    <div className="admin-panel-heading"><div><h2>Store & bank transfer details</h2><span>These bank details are shown at checkout when bank transfer is enabled.</span></div></div>
    <form className="admin-page-editor" onSubmit={onSave}>
      <div className="admin-dialog-fields">
        <label className="field">Store name<input name="storeName" maxLength={120} required defaultValue={settings.storeName||""}/></label>
        <label className="field">Store contact email<input name="contactEmail" type="email" maxLength={254} defaultValue={settings.contactEmail||""}/></label>
        <label className="field">Currency<select name="defaultCurrency" value="npr" disabled><option value="npr">Nepalese rupee (NPR)</option></select></label>
        <label className="field">Low-stock alert threshold<input name="lowStockThreshold" type="number" min="0" max="10000" required defaultValue={settings.lowStockThreshold??5}/></label>
        <label className="field">Bank name<input name="bankName" maxLength={120} defaultValue={settings.bankName||""}/></label>
        <label className="field">Account holder name<input name="bankAccountName" maxLength={160} defaultValue={settings.bankAccountName||""}/></label>
        <label className="field">Account number<input name="bankAccountNumber" maxLength={80} autoComplete="off" defaultValue={settings.bankAccountNumber||""}/></label>
        <label className="field">Branch<input name="bankBranch" maxLength={120} defaultValue={settings.bankBranch||""}/></label>
        <label className="field full">Transfer instructions<textarea name="bankInstructions" maxLength={1000} rows={4} defaultValue={settings.bankInstructions||""}/></label>
      </div>
      <div className="admin-page-editor-footer"><span>{settings.bankAccountNumber?"Bank transfer is available at checkout.":"Add bank details to enable bank transfer."}</span><button className="button" disabled={busy}>{busy?"Saving…":"Save store settings"}</button></div>
    </form>
  </section>;
}

function ResourcePanel({tab,view,config,rows,canWrite,onAdd,onEdit,onDelete,onView,onPublish}) {
  const [query,setQuery]=useState("");
  const [filter,setFilter]=useState("all");
  const columns = {
    books: [["title","Title"],["category","Category"],["format","Type"],["priceNpr","Price (NPR)"],["stock","Stock"],["status","Publication"]],
    media: [["title","Image"],["category","Category"],["url","Image URL"],["public","Public"]],
    content: [["key","Key"],["value","Value"],["public","Public"]],
    users: [["email","Email"],["role","Role"],["active","Active"],["createdAt","Created"]],
    customers: [["name","Name"],["email","Email"],["phone","Phone"],["createdAt","First order"]]
  }[tab] || [];
  const statuses=[...new Set(rows.map(record=>record.status).filter(Boolean))];
  const filteredRows=rows.filter(record=>{
    const text=`${columns.map(([key])=>display(record[key])).join(" ")} ${record._id||""}`.toLowerCase();
    if(query&&!text.includes(query.toLowerCase()))return false;
    if(filter!=="all"){
      if(tab==="users"&&filter.startsWith("role:")) {
        if(record.role!==filter.slice(5))return false;
      } else if(record.status!==filter&&(record.active?"active":"inactive")!==filter)return false;
    }
    return true;
  });
  const title=view==="store-books"?"Bookstore inventory":{books:"Published works",media:"Gallery images",content:"Editable website fields",users:"Team accounts",customers:"Customers"}[tab]||"Records";
  const addLabel={books:"book",media:"image",content:"content",users:"team member",customers:"customer"}[tab]||"record";
  return <section className="admin-panel">
    <div className="admin-panel-heading"><div><h2>{view==="team"?"Team & Roles":view==="gallery"?"Portfolio gallery":title}</h2><span>{filteredRows.length} of {rows.length} records</span></div>{canWrite&&<button className="admin-add" onClick={onAdd}><Plus size={15}/> Add {addLabel}</button>}</div>
    <div className="admin-list-toolbar">
      <label className="admin-search"><Search size={15}/><input aria-label={`Search ${title}`} placeholder={`Search ${title.toLowerCase()}…`} value={query} onChange={event=>setQuery(event.target.value)}/></label>
      <label className="admin-filter-label">Filter<select value={filter} onChange={event=>setFilter(event.target.value)}><option value="all">All records</option>{statuses.map(status=><option key={status} value={status}>{status}</option>)}{tab==="users"&&<><option value="active">Active</option><option value="inactive">Inactive</option>{["admin","manager","editor","support"].map(role=><option key={role} value={`role:${role}`}>{role}</option>)}</>}</select></label>
    </div>
    <div className="admin-table-scroll"><table className="admin-table"><thead><tr>{columns.map(([,label])=><th key={label}>{label}</th>)}<th>Updated</th><th>Actions</th></tr></thead><tbody>{filteredRows.map(record=><tr key={record[config.id]}>{columns.map(([key,label])=><td key={key} data-label={label}>{key==="status"||key==="active"||key==="public"?<Status value={key==="active"?(record.active?"Active":"Inactive"):key==="public"?(record.public?"Published":"Hidden"):tab==="books"?(record.status||"published"):record[key]}/>:key==="value"?display(record.value):key==="publishedAt"||key==="createdAt"||key==="updatedAt"?record[key]?new Date(record[key]).toLocaleDateString():"—":display(record[key])}</td>)}<td data-label="Updated">{record.updatedAt?new Date(record.updatedAt).toLocaleDateString():"—"}</td><td data-label="Actions"><div className="admin-row-actions"><button title="View details" aria-label="View details" onClick={()=>onView(record)}><Eye size={14}/></button>{canWrite&&<><button title="Edit record" aria-label="Edit record" onClick={()=>onEdit(record)}><Pencil size={14}/></button>{(tab==="books"||(tab==="media"&&record.category==="gallery"))&&<button className="admin-publish-toggle" onClick={()=>onPublish(record)}>{tab==="media"?(record.public?"Hide":"Publish"):(record.status==="published"||!record.status?"Unpublish":"Publish")}</button>}<button title="Delete record" aria-label="Delete record" className="danger" onClick={()=>onDelete(record)}><Trash2 size={14}/></button></>}</div></td></tr>)}</tbody></table>{!filteredRows.length&&<div className="admin-empty">{rows.length?"No records match the current search or filter.":"No records yet. Use Add to create your first item."}</div>}</div>
  </section>;
}

function AuditPanel({events,onView}) {
  const [query,setQuery]=useState("");
  const [action,setAction]=useState("all");
  const filtered=events.filter(event=>`${event.user?.email||""} ${event.action||""} ${event.resource||""} ${event.resourceId||""}`.toLowerCase().includes(query.toLowerCase())&&(action==="all"||event.action===action));
  return <section className="admin-panel"><div className="admin-panel-heading"><div><h2>Admin activity</h2><span>{filtered.length} of {events.length} recent audited changes</span></div></div><div className="admin-list-toolbar"><label className="admin-search"><Search size={15}/><input aria-label="Search audit log" placeholder="Search account, action, or resource…" value={query} onChange={event=>setQuery(event.target.value)}/></label><label className="admin-filter-label">Action<select value={action} onChange={event=>setAction(event.target.value)}><option value="all">All actions</option>{[...new Set(events.map(event=>event.action).filter(Boolean))].map(item=><option key={item} value={item}>{item}</option>)}</select></label></div><div className="admin-table-scroll"><table className="admin-table"><thead><tr><th>When</th><th>Account</th><th>Action</th><th>Resource</th><th>Record</th><th>Details</th></tr></thead><tbody>{filtered.map(event=><tr key={event._id}><td data-label="When">{new Date(event.createdAt).toLocaleString()}</td><td data-label="Account">{event.user?.email}</td><td data-label="Action">{event.action}</td><td data-label="Resource">{event.resource}</td><td data-label="Record">{event.resourceId||"—"}</td><td data-label="Details"><button className="admin-reconcile" onClick={()=>onView(event)}>View</button></td></tr>)}</tbody></table>{!filtered.length&&<div className="admin-empty">No activity matches the current search or filter.</div>}</div></section>;
}

function RecordViewDialog({record,onClose}) {
  const image=record.url||record.image;
  return <div className="admin-dialog-backdrop" role="presentation" onMouseDown={event=>event.target===event.currentTarget&&onClose()}><section className="admin-dialog admin-view-dialog" role="dialog" aria-modal="true" aria-label="Record details">
    <div className="admin-dialog-head"><div><div className="eyebrow">RECORD DETAILS</div><h2 className="serif">{record.title||record.name||record.provider||record.key||"Record"}</h2></div><button type="button" onClick={onClose} aria-label="Close details"><X size={18}/></button></div>
    {image&&<img className="admin-image-detail" src={image} alt={record.altText||record.title||"Record image"}/>}
    <pre className="admin-record-json">{JSON.stringify(record,null,2)}</pre>
    <div className="admin-dialog-footer"><button type="button" className="admin-cancel" onClick={onClose}>Close</button></div>
  </section></div>;
}

function Status({value}) {
  const normalized = String(value||"").toLowerCase();
  const pending = ["pending","initiated","draft","inactive","cancelled","failed","rejected","low stock"].includes(normalized);
  const good = ["paid","completed","approved","published","active","fulfilled"].includes(normalized);
  return <span className={`admin-status ${pending?"pending":""} ${good?"good":""}`}>{value||"—"}</span>;
}

function RecordDialog({tab,config,record,categoryOptions=[],onClose,onSave}) {
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const isNew=!record[config.id];
  const fields=config.fields.filter(([name])=>!(tab==="users"&&!isNew&&name==="password"));
  function initialValue(name,type) {
    if(name==="password")return "";
    const value=record[name];
    if(value===undefined||value===null)return type==="checkbox"?name==="active"&&isNew:"";
    if(tab==="content"&&name==="value")return JSON.stringify(value,null,2);
    if(type==="checkbox")return Boolean(value);
    if(type==="date")return new Date(value).toISOString().slice(0,10);
    if(typeof value==="object")return value._id||"";
    return String(value);
  }
  async function submit(event) {
    setSaving(true);setError("");
    try{await onSave(event);}catch(saveError){setError(saveError.message||"Unable to save these changes.");setSaving(false);}
  }
  return <div className="admin-dialog-backdrop" role="presentation" onMouseDown={event=>event.target===event.currentTarget&&onClose()}><form className="admin-dialog" onSubmit={submit}><div className="admin-dialog-head"><div><div className="eyebrow">{isNew?"NEW RECORD":"EDIT RECORD"}</div><h2 className="serif">{isNew?"Add":"Edit"} {tab==="content"?"website content":tab==="users"?"team account":tab.slice(0,-1)}</h2></div><button type="button" onClick={onClose} aria-label="Close dialog"><X size={18}/></button></div><div className="admin-dialog-fields">{fields.map(([name,label,type,required,choices])=>  <label key={name} className={`field ${type==="textarea"?"full":""}`}>{label}{type==="textarea"?<textarea name={name} required={required} defaultValue={initialValue(name,type)} rows={name==="body"||name==="description"?7:3}/>:type==="select"?<select name={name} required={required} defaultValue={initialValue(name,type)||(tab==="books"&&name==="status"?(isNew?"draft":"published"):choices?.[0])}>{choices?.map(choice=><option key={choice} value={choice}>{choice}</option>)}</select>:type==="checkbox"?<input type="checkbox" name={name} defaultChecked={initialValue(name,type)}/>:type==="category"?<><input name={name} list="admin-category-options" maxLength={80} defaultValue={initialValue(name,type)} placeholder="Choose or type a category"/><datalist id="admin-category-options">{[...new Set(categoryOptions)].map(option=><option key={option} value={option}/>)}</datalist></>:<input type={type} name={name} required={required&&!(!isNew&&name==="password")} defaultValue={initialValue(name,type)} min={type==="number"?0:undefined} step={name==="priceNpr"?"0.01":undefined}/>}</label>)}</div>{error&&<div className="admin-error">{error}</div>}<div className="admin-dialog-footer"><button type="button" className="admin-cancel" onClick={onClose}>Cancel</button><button className="button" disabled={saving}>{saving?"Saving…":"Save changes"}</button></div></form></div>;
}
