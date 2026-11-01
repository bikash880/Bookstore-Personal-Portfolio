"use client";

import Link from "next/link";
import { Plus } from "lucide-react";
import { useStore } from "./store-shell";
import { availabilityLabel, formatNpr, isPurchasable } from "./store-shared";
import { responsiveSrcSet } from "../image-sources";

export default function StoreBookCard({ book }) {
  const { addToCart } = useStore();
  const purchasable = isPurchasable(book);
  const label = availabilityLabel(book);
  const href = `/store/books/${book._id}`;
  return <article className="store-book-card">
    <Link className="store-book-cover" href={href} aria-label={`View details for ${book.title}`}>
      <img src={book.image} {...responsiveSrcSet(book.image)} sizes="(max-width: 700px) 48vw, (max-width: 1100px) 32vw, 300px" alt={`Cover artwork for ${book.title}`} loading="lazy" decoding="async"/>
      <span>{book.category || book.format || "Book"}</span>
      {purchasable && book.stock <= 3 && <em className="store-stock-flag">{label}</em>}
      {Number(book.priceNpr) > 0 && book.stock < 1 && <em className="store-stock-flag sold-out">Sold out</em>}
    </Link>
    <div className="store-book-info">
      <div className="store-book-meta">{book.format || "Book"}{book.year ? ` · ${book.year}` : ""}</div>
      <h3><Link href={href}>{book.title}</Link></h3>
      {book.subtitle && <p className="store-book-subtitle">{book.subtitle}</p>}
      <div className="store-book-buy-row">
        <strong>{Number(book.priceNpr) > 0 ? formatNpr(book.priceNpr) : "Pricing soon"}</strong>
        <span className={purchasable ? "in-stock" : ""}>{label}</span>
      </div>
      <div className="store-book-actions">
        <Link className="store-details-button" href={href}>Details</Link>
        <button className="store-add-button" disabled={!purchasable} onClick={() => addToCart(book)}><Plus size={14}/> Add to bag</button>
      </div>
    </div>
  </article>;
}
