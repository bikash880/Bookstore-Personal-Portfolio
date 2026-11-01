"use client";

export const API = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/+$/, "");
export const CART_KEY = "author-store-cart";
export const ORDERS_KEY = "author-store-orders";
export const CUSTOMER_KEY = "author-store-customer";
export const OBJECT_ID = /^[a-fA-F0-9]{24}$/;

export const PAYMENT_LABELS = {
  esewa: "eSewa",
  khalti: "Khalti",
  bank_transfer: "Bank transfer"
};

export const STATUS_LABELS = {
  pending: "Awaiting payment",
  paid: "Payment confirmed",
  processing: "Being prepared",
  shipped: "On its way",
  fulfilled: "Delivered",
  cancelled: "Cancelled"
};

export function formatNpr(value) {
  return `NPR ${Number(value || 0).toLocaleString("en-NP", { maximumFractionDigits: 2 })}`;
}

export function formatDate(value, withTime = false) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("en-GB", withTime
    ? { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }
    : { day: "numeric", month: "short", year: "numeric" });
}

export async function requestJson(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers
    }
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(result.error || `Request failed (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return result;
}

export function isPurchasable(book) {
  return Boolean(book) && book.stock > 0 && Number(book.priceNpr) > 0;
}

export function availabilityLabel(book) {
  if (!(Number(book?.priceNpr) > 0)) return "Availability soon";
  if (book.stock < 1) return "Sold out";
  if (book.stock <= 3) return `Only ${book.stock} left`;
  return "In stock";
}

export function readStorage(key, fallback) {
  try {
    const value = JSON.parse(window.localStorage.getItem(key) || "null");
    return value ?? fallback;
  } catch {
    return fallback;
  }
}

export function writeStorage(key, value) {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export function sanitizeCart(value) {
  if (!Array.isArray(value)) return [];
  return value.filter(item =>
    item && OBJECT_ID.test(item.bookId) && Number.isInteger(item.quantity) && item.quantity > 0 && item.quantity <= 20
  );
}

export function rememberOrder(orderId) {
  if (!OBJECT_ID.test(orderId)) return;
  const saved = readStorage(ORDERS_KEY, []);
  const orders = (Array.isArray(saved) ? saved : []).filter(item => item?.id !== orderId);
  writeStorage(ORDERS_KEY, [{ id: orderId, at: new Date().toISOString() }, ...orders].slice(0, 10));
}

export function rememberedOrders() {
  const saved = readStorage(ORDERS_KEY, []);
  return Array.isArray(saved) ? saved.filter(item => OBJECT_ID.test(item?.id)) : [];
}
