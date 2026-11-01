"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, BookOpen, Search, SlidersHorizontal } from "lucide-react";
import { useStore } from "./store-shell";
import StoreBookCard from "./store-book-card";
import { OBJECT_ID, rememberedOrders } from "./store-shared";
import { responsiveSrcSet } from "../image-sources";

const sorters = {
  featured: () => 0,
  newest: (a, b) => (Number(b.year) || 0) - (Number(a.year) || 0),
  "price-asc": (a, b) => (Number(a.priceNpr) || Infinity) - (Number(b.priceNpr) || Infinity),
  "price-desc": (a, b) => (Number(b.priceNpr) || 0) - (Number(a.priceNpr) || 0),
  title: (a, b) => String(a.title).localeCompare(String(b.title))
};

export default function StorePage() {
  const router = useRouter();
  const { books, categories, loading, loadError } = useStore();
  const [category, setCategory] = useState("All books");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("featured");
  const [inStockOnly, setInStockOnly] = useState(false);

  useEffect(() => {
    // Older payment return links pointed at /store?orderId=…; send them to the order page.
    const params = new URLSearchParams(window.location.search);
    const orderId = params.get("orderId") || (params.get("payment") === "return" ? rememberedOrders()[0]?.id : "");
    if (orderId && OBJECT_ID.test(orderId)) router.replace(`/store/orders/${orderId}?payment=return`);
  }, [router]);

  const visibleBooks = useMemo(() => {
    const text = query.toLowerCase().trim();
    return books.filter(book => {
      const matchesCategory = category === "All books" || (book.category || book.format || "Books") === category;
      const haystack = `${book.title} ${book.subtitle || ""} ${book.description || ""} ${book.category || ""} ${book.format || ""}`.toLowerCase();
      const available = book.stock > 0 && Number(book.priceNpr) > 0;
      return matchesCategory && haystack.includes(text) && (!inStockOnly || available);
    }).sort(sorters[sort]);
  }, [books, category, query, sort, inStockOnly]);

  const featured = books.find(book => book.stock > 0 && Number(book.priceNpr) > 0) || books[0];

  return <>
    <section className="store-hero">
      <div className="store-hero-inner">
        <span className="store-eyebrow">THE AUTHOR'S BOOKSHELF</span>
        <h1>Stories to <em>keep.</em></h1>
        <p>Thoughtful books, signed with care and sent from the author's bookshelf to yours.</p>
        <a href="#store-catalog" className="store-hero-link">Find your next read <ArrowRight size={15}/></a>
      </div>
      {featured?.image
        ? <Link className="store-hero-feature" href={`/store/books/${featured._id}`} aria-label={`Featured: ${featured.title}`}>
          <img src={featured.image} {...responsiveSrcSet(featured.image)} sizes="210px" alt="" fetchPriority="high"/>
          <span><small>FEATURED</small>{featured.title}</span>
        </Link>
        : <div className="store-hero-decoration" aria-hidden="true"><BookOpen size={96}/></div>}
    </section>

    <section className="store-catalog" id="store-catalog">
      <div className="store-catalog-heading">
        <div><span className="store-eyebrow">A CURATED COLLECTION</span><h2>Browse the bookshelf</h2></div>
        <span className="store-catalog-count">{visibleBooks.length} {visibleBooks.length === 1 ? "book" : "books"}</span>
      </div>
      <div className="store-toolbar">
        <label className="store-search"><Search size={16}/><input type="search" aria-label="Search books" placeholder="Search by title or story…" value={query} onChange={event => setQuery(event.target.value)}/></label>
        <div className="store-toolbar-controls">
          <label className="store-instock"><input type="checkbox" checked={inStockOnly} onChange={event => setInStockOnly(event.target.checked)}/> In stock only</label>
          <label className="store-sort"><SlidersHorizontal size={14}/><span className="sr-only">Sort books</span>
            <select value={sort} onChange={event => setSort(event.target.value)}>
              <option value="featured">Featured</option>
              <option value="newest">Newest first</option>
              <option value="price-asc">Price: low to high</option>
              <option value="price-desc">Price: high to low</option>
              <option value="title">Title A–Z</option>
            </select>
          </label>
        </div>
      </div>
      {categories.length > 1 && <div className="store-categories store-category-row" aria-label="Book categories">
        {["All books", ...categories].map(option => <button key={option} className={category === option ? "active" : ""} aria-pressed={category === option} onClick={() => setCategory(option)}>{option}</button>)}
      </div>}

      {loadError && <div className="store-alert" role="alert">{loadError}</div>}
      {loading ? <div className="store-grid" aria-busy="true">{Array.from({ length: 4 }, (_, index) => <div className="store-skeleton" key={index}><span/><i/><i/></div>)}</div>
        : visibleBooks.length ? <div className="store-grid">{visibleBooks.map(book => <StoreBookCard key={book._id} book={book}/>)}</div>
        : <div className="store-empty">{books.length ? <>No books match your search. <button className="store-link-button" onClick={() => { setQuery(""); setCategory("All books"); setInStockOnly(false); }}>Clear filters</button></> : "The shop is getting ready. Please check back soon."}</div>}
    </section>
  </>;
}
