import { cache } from "react";
import BookDetail from "./book-detail";

// cache() shares one API request between generateMetadata and the page for each render.
const fetchBook = cache(async function fetchBook(id) {
  const apiUrl = (process.env.API_SERVER_URL || process.env.NEXT_PUBLIC_API_URL || "").replace(/\/+$/, "");
  if (!apiUrl || !/^[a-fA-F0-9]{24}$/.test(id)) return null;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2500);
  try {
    const response = await fetch(`${apiUrl}/api/store/books/${id}`, { signal: controller.signal, cache: "no-store" });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
});

export async function generateMetadata({ params }) {
  const { id } = await params;
  const result = await fetchBook(id);
  const book = result?.book;
  if (!book) return { title: "Book — Bookstore" };
  const description = String(book.description || book.subtitle || "").slice(0, 200);
  const images = typeof book.image === "string" && book.image.startsWith("https://") ? [book.image] : [];
  return {
    title: `${book.title} — Bookstore`,
    description,
    openGraph: { title: book.title, description, type: "book", images },
    twitter: { card: images.length ? "summary_large_image" : "summary", title: book.title, description, images }
  };
}

export default async function BookPage({ params }) {
  const { id } = await params;
  const initial = await fetchBook(id);
  return <BookDetail id={id} initial={initial}/>;
}
