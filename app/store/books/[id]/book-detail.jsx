"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight, BadgeCheck, ChevronRight, Link2, Minus, PackageCheck, Plus, ShieldCheck,
  ShoppingBag, Truck
} from "lucide-react";
import { useStore } from "../../store-shell";
import StoreBookCard from "../../store-book-card";
import { OBJECT_ID, availabilityLabel, formatNpr, isPurchasable, requestJson } from "../../store-shared";
import { responsiveSrcSet } from "../../../image-sources";

export default function BookDetail({ id, initial }) {
  const { books, addToCart, startCheckout, notify, cartItems } = useStore();
  const [data, setData] = useState(initial);
  const [error, setError] = useState("");
  const [quantity, setQuantity] = useState(1);

  useEffect(() => {
    if (initial || !OBJECT_ID.test(id)) {
      if (!OBJECT_ID.test(id)) setError("This book could not be found.");
      return;
    }
    let active = true;
    requestJson(`/api/store/books/${id}`)
      .then(result => { if (active) setData(result); })
      .catch(requestError => { if (active) setError(requestError.status === 404 ? "This book could not be found." : requestError.message); });
    return () => { active = false; };
  }, [id, initial]);

  // Prefer the live catalog entry so stock reflects what the bag will validate against.
  const book = books.find(item => item._id === id) || data?.book;
  const related = data?.related || [];
  const inBag = cartItems.find(item => item.bookId === id)?.quantity || 0;
  const maxQuantity = Math.max(0, Math.min(book?.stock || 0, 20) - inBag);

  useEffect(() => {
    setQuantity(current => Math.max(1, Math.min(current, maxQuantity || 1)));
  }, [maxQuantity]);

  if (error) return <section className="store-detail-page store-detail-missing">
    <span className="store-eyebrow">NOT FOUND</span>
    <h1>{error}</h1>
    <p>It may have been unpublished or the link may be incomplete.</p>
    <Link className="store-checkout-button" href="/store">Browse the bookshelf <ArrowRight size={15}/></Link>
  </section>;

  if (!book) return <section className="store-detail-page"><div className="store-detail-layout" aria-busy="true"><div className="store-skeleton store-detail-skeleton"><span/></div><div className="store-skeleton"><i/><i/><i/></div></div></section>;

  const purchasable = isPurchasable(book);
  const category = book.category || book.format || "Books";

  async function share() {
    const url = window.location.href;
    try {
      if (navigator.share) await navigator.share({ title: book.title, url });
      else {
        await navigator.clipboard.writeText(url);
        notify("Link copied to your clipboard.");
      }
    } catch {
      // The visitor closed the share sheet; nothing to report.
    }
  }

  return <>
    <section className="store-detail-page">
      <nav className="store-breadcrumb" aria-label="Breadcrumb">
        <Link href="/store">Bookstore</Link><ChevronRight size={12}/>
        <span>{category}</span><ChevronRight size={12}/>
        <span aria-current="page">{book.title}</span>
      </nav>
      <div className="store-detail-layout">
        <div className="store-detail-gallery">
          <div className="store-detail-cover-large"><img src={book.image} {...responsiveSrcSet(book.image)} sizes="(max-width: 900px) 70vw, 340px" alt={`Cover artwork for ${book.title}`} fetchPriority="high"/></div>
        </div>
        <div className="store-detail-info">
          <span className="store-eyebrow">{category}{book.year ? ` · ${book.year}` : ""}</span>
          <h1>{book.title}</h1>
          {book.subtitle && <p className="store-detail-subtitle">{book.subtitle}</p>}
          <div className="store-detail-price-row">
            <strong>{Number(book.priceNpr) > 0 ? formatNpr(book.priceNpr) : "Pricing soon"}</strong>
            <span className={`store-availability ${purchasable ? (book.stock <= 3 ? "low" : "ok") : "out"}`}>{availabilityLabel(book)}</span>
          </div>

          {purchasable ? <div className="store-detail-buy">
            <div className="store-quantity store-quantity-large" aria-label="Quantity">
              <button aria-label="Decrease quantity" disabled={quantity <= 1} onClick={() => setQuantity(quantity - 1)}><Minus size={14}/></button>
              <span aria-live="polite">{quantity}</span>
              <button aria-label="Increase quantity" disabled={quantity >= maxQuantity} onClick={() => setQuantity(quantity + 1)}><Plus size={14}/></button>
            </div>
            <button className="store-add-button" disabled={maxQuantity < 1} onClick={() => addToCart(book, quantity)}><ShoppingBag size={15}/> {maxQuantity < 1 ? "All available copies are in your bag" : "Add to bag"}</button>
            <button className="store-buy-now" disabled={maxQuantity < 1 && !inBag} onClick={() => { if (maxQuantity > 0) addToCart(book, quantity, { silent: true }); startCheckout(); }}>Buy now</button>
          </div> : <p className="store-detail-unavailable">{Number(book.priceNpr) > 0 ? "This book is currently sold out. Please check back soon." : "This book will be available to order soon."}</p>}
          {inBag > 0 && <p className="store-in-bag"><BadgeCheck size={14}/> {inBag} {inBag === 1 ? "copy is" : "copies are"} in your bag.</p>}

          <ul className="store-assurances">
            <li><ShieldCheck size={16}/><span><strong>Verified payments</strong>eSewa, Khalti and bank transfers are confirmed on our server.</span></li>
            <li><PackageCheck size={16}/><span><strong>Packed with care</strong>Every order is prepared from the author's own bookshelf.</span></li>
            <li><Truck size={16}/><span><strong>Order tracking</strong>Follow your order from payment to delivery.</span></li>
          </ul>

          {book.description && <div className="store-detail-section">
            <h2>About this book</h2>
            <p>{book.description}</p>
          </div>}
          <dl className="store-detail-specs">
            <div><dt>Format</dt><dd>{book.format || "Book"}</dd></div>
            {book.year && <div><dt>Published</dt><dd>{book.year}</dd></div>}
            <div><dt>Category</dt><dd>{category}</dd></div>
            <div><dt>Availability</dt><dd>{availabilityLabel(book)}</dd></div>
          </dl>
          <button className="store-link-button store-share" onClick={share}><Link2 size={14}/> Share this book</button>
        </div>
      </div>
    </section>

    {related.length > 0 && <section className="store-catalog store-related">
      <div className="store-catalog-heading"><div><span className="store-eyebrow">KEEP READING</span><h2>You may also like</h2></div><Link className="store-link-button" href="/store">View all <ArrowRight size={13}/></Link></div>
      <div className="store-grid">{related.map(item => <StoreBookCard key={item._id} book={books.find(entry => entry._id === item._id) || item}/>)}</div>
    </section>}
  </>;
}
