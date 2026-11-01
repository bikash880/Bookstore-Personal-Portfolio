"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight, ArrowUpRight, Facebook, Instagram, Linkedin, LockKeyhole, Mail, MapPin,
  Menu, Quote, ShoppingBag, X
} from "lucide-react";
import BrandMark from "./brand-mark";
import ThemeToggle from "./theme-toggle";
import { responsiveSrcSet } from "./image-sources";

const apiBase = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/+$/, "");

const defaultProfile = {
  name: "Binod Kumar Mahato",
  role: "AUTHOR · CULTURAL RESEARCHER",
  email: "hello@evelynhartbooks.com",
  facebook: "https://facebook.com/",
  instagram: "https://instagram.com/",
  linkedin: "https://linkedin.com/",
  location: "Portland, Oregon",
  portrait: "https://images.unsplash.com/photo-1508214751196-bcfd4ca60f91?auto=format&fit=crop&w=1100&q=85",
  landscape: "https://images.unsplash.com/photo-1470252649378-9c29740c9fa8?auto=format&fit=crop&w=1200&q=85",
  heroLead: "Preserving Heritage,",
  heroEmphasis: "Sharing Stories",
  heroDescription: "Exploring the traditions, histories, and voices that keep cultural heritage alive.",
  aboutHeading: "An author and cultural researcher sharing stories that preserve heritage.",
  aboutBiography: "Through writing and cultural research, I work to preserve heritage and share the stories that connect communities across generations.",
  aboutPageTitle: "Preserving heritage, one story at a time.",
  aboutPageBiography: "I am Binod Kumar Mahato, an author and cultural researcher. My work is guided by a belief in the value of preserving heritage and sharing the stories that help it live on."
};

const defaultBooks = [
  { title: "The Quiet Between", subtitle: "A novel of homecoming", year: 2025, format: "Novel", image: "https://images.unsplash.com/photo-1544947950-fa07a98d237f?auto=format&fit=crop&w=800&q=85", description: "When Mara returns to the salt-worn town she swore she had left behind, she finds the old house full of familiar silences—and a letter that changes everything she thought she knew about her mother." },
  { title: "A Map of Small Things", subtitle: "Finding wonder, one day at a time", year: 2024, format: "Essays", image: "https://images.unsplash.com/photo-1512820790803-83ca734da794?auto=format&fit=crop&w=800&q=85", description: "A tender collection of essays about noticing the life already unfolding around us, told through tiny rituals, unexpected friendships, and the places we call home." },
  { title: "The Wildflower Season", subtitle: "A story of courage & becoming", year: 2023, format: "Novel", image: "https://images.unsplash.com/photo-1519682337058-a94d519337bc?auto=format&fit=crop&w=800&q=85", description: "In a mountain valley on the edge of spring, two sisters begin again. A luminous story about the families we inherit, the ones we choose, and the courage to grow toward the light." },
  { title: "Letters to the Sea", subtitle: "A coastal story of second chances", year: 2022, format: "Novel", image: "https://images.unsplash.com/photo-1513001900722-370f803f498d?auto=format&fit=crop&w=800&q=85", description: "A box of unsent letters washes ashore and draws a young archivist into the intertwined lives of three generations of women on the Oregon coast." }
];

const navigation = [
  ["home", "Home"], ["about", "About"], ["books", "Published works"],
  ["gallery", "Gallery"], ["contact", "Contact"]
];

function safeProfile(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return defaultProfile;
  const result = { ...defaultProfile };
  for (const key of ["name", "role", "location", "heroLead", "heroEmphasis", "heroDescription", "aboutHeading", "aboutBiography", "aboutPageTitle", "aboutPageBiography", "quote"]) {
    if (typeof value[key] === "string" && value[key].length <= 5000) result[key] = value[key];
  }
  if (typeof value.email === "string" && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.email)) result.email = value.email;
  for (const key of ["instagram", "facebook", "linkedin", "tiktok", "youtube", "threads"]) {
    if (typeof value[key] === "string" && (!value[key] || /^https:\/\//i.test(value[key]))) result[key] = value[key];
  }
  for (const key of ["portrait", "landscape"]) {
    if (typeof value[key] === "string" && (value[key].startsWith("https://") || (value[key].startsWith("/") && !value[key].startsWith("//")))) result[key] = value[key];
  }
  return result;
}

function safeSiteSettings(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const settings = {};
  for (const key of ["siteTitle", "seoTitle", "seoDescription"]) {
    if (typeof value[key] === "string" && value[key].length <= 5000) settings[key] = value[key];
  }
  if (typeof value.ogImage === "string" && /^https:\/\//i.test(value.ogImage)) settings.ogImage = value.ogImage;
  return settings;
}

function formatNpr(value) {
  return `NPR ${Number(value || 0).toLocaleString("en-NP", { maximumFractionDigits: 2 })}`;
}

// Fades and lifts its children into view once, the first time they scroll onscreen.
function Reveal({ as: Tag = "div", className = "", delay = 0, children, ...rest }) {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (!("IntersectionObserver" in window)) { setVisible(true); return; }
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) { setVisible(true); observer.disconnect(); }
    }, { rootMargin: "0px 0px -8% 0px", threshold: .12 });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return <Tag ref={ref} className={`pf-reveal ${visible ? "is-visible" : ""} ${className}`} style={{ "--pf-delay": `${delay}ms` }} {...rest}>{children}</Tag>;
}

function SectionTitle({ eyebrow, title, note }) {
  return <div className="pf-page-hero"><div className="wrap">
    <Reveal><div className="pf-eyebrow">{eyebrow}</div></Reveal>
    <Reveal as="h1" delay={80}>{title}</Reveal>
    {note && <Reveal as="p" delay={160}>{note}</Reveal>}
  </div><span className="pf-page-hero-mark" aria-hidden="true"><BrandMark size={220}/></span></div>;
}

function BookCard({ book, storeBook, index = 0 }) {
  const purchasable = storeBook && Number(storeBook.priceNpr) > 0 && storeBook.stock > 0;
  return <Reveal as="article" className="pf-book" delay={index * 90}>
    <a className="pf-book-cover" href={book._id ? `/store/books/${book._id}` : "/store"} aria-label={`${book.title} in the bookstore`}>
      <img src={book.image} {...responsiveSrcSet(book.image)} sizes="(max-width: 700px) 92vw, (max-width: 1100px) 46vw, 400px" alt={`Cover artwork for ${book.title}`} loading="lazy" decoding="async"/>
      <span className="pf-book-spine" aria-hidden="true"/>
      {purchasable && <span className="pf-book-badge">Available</span>}
    </a>
    <div className="pf-book-body">
      <div className="pf-eyebrow">{book.format || "Published work"}{book.year ? ` · ${book.year}` : ""}</div>
      <h3>{book.title}</h3>
      {book.subtitle && <p className="pf-book-subtitle">{book.subtitle}</p>}
      {book.description && <p className="pf-book-description">{book.description}</p>}
      {book._id && <a className="pf-book-link" href={`/store/books/${book._id}`}>
        {purchasable ? <>Buy now · {formatNpr(storeBook.priceNpr)}</> : "View in the bookstore"} <ArrowRight size={13}/>
      </a>}
    </div>
  </Reveal>;
}

export default function Home() {
  const [page, setPage] = useState("home");
  const [profile, setProfile] = useState(defaultProfile);
  const [books, setBooks] = useState(defaultBooks);
  const [storeBooks, setStoreBooks] = useState([]);
  const [gallery, setGallery] = useState([]);
  const [siteSettings, setSiteSettings] = useState({});
  const [menuOpen, setMenuOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const [lightbox, setLightbox] = useState(null);
  const [newsletterEmail, setNewsletterEmail] = useState("");
  const [newsletterState, setNewsletterState] = useState({ status: "idle", message: "" });
  const firstName = (profile.name || "the author").split(" ")[0];
  const pageRef = useRef(page);
  const refreshRef = useRef(null);

  useEffect(() => {
    let active = true;
    let timer;
    let galleryLoaded = false;
    // "no-cache" revalidates with the API's ETag, so unchanged data comes back as an empty 304.
    const readJson = (path, message) => fetch(`${apiBase}${path}`, { cache: "no-cache" })
      .then(response => response.ok ? response.json() : Promise.reject(new Error(message)));
    async function refreshPortfolio() {
      // The gallery is loaded once up front, then only kept fresh while it is on screen.
      const wantGallery = !galleryLoaded || pageRef.current === "gallery";
      const results = await Promise.allSettled([
        readJson("/api/books", "Published works unavailable."),
        readJson("/api/content", "Website content unavailable."),
        wantGallery ? readJson("/api/gallery", "Gallery unavailable.") : Promise.resolve(null)
      ]);
      if (!active) return;
      const [bookResult, contentResult, galleryResult] = results;
      if (galleryResult.status === "fulfilled" && galleryResult.value) galleryLoaded = true;
      if (bookResult.status === "fulfilled" && Array.isArray(bookResult.value.books)) setBooks(bookResult.value.books);
      if (contentResult.status === "fulfilled") {
        const content = contentResult.value.content || [];
        setProfile(safeProfile(content.find(item => item.key === "author-profile")?.value));
        setSiteSettings(safeSiteSettings(content.find(item => item.key === "site-settings")?.value));
      }
      if (galleryResult.status === "fulfilled" && Array.isArray(galleryResult.value?.images)) setGallery(galleryResult.value.images);
      scheduleRefresh();
    }
    refreshRef.current = () => { window.clearTimeout(timer); refreshPortfolio(); };
    // Admin edits appear within 20 seconds. Polling pauses in background tabs so a page left open
    // stays well under the API's per-visitor rate limit (150 requests per 15 minutes per endpoint).
    function scheduleRefresh() {
      window.clearTimeout(timer);
      if (!document.hidden) timer = window.setTimeout(refreshPortfolio, 20000);
    }
    function onVisibilityChange() {
      if (document.hidden) window.clearTimeout(timer);
      else refreshPortfolio();
    }
    document.addEventListener("visibilitychange", onVisibilityChange);
    refreshPortfolio();
    // Prices and stock are shown beside each work; the portfolio works without them.
    fetch(`${apiBase}/api/store/books`, { cache: "no-cache" })
      .then(response => response.ok ? response.json() : null)
      .then(result => { if (active && Array.isArray(result?.books)) setStoreBooks(result.books); })
      .catch(() => {});
    return () => {
      active = false;
      refreshRef.current = null;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, []);

  useEffect(() => {
    const previous = pageRef.current;
    pageRef.current = page;
    // Opening the gallery fetches its latest images right away instead of waiting for the next poll.
    if (page === "gallery" && previous !== "gallery") refreshRef.current?.();
  }, [page]);

  useEffect(() => {
    const title = siteSettings.seoTitle || siteSettings.siteTitle || `${profile.name} — Preserving Heritage, Sharing Stories`;
    const description = siteSettings.seoDescription || `Discover published works and the author profile of ${profile.name}.`;
    document.title = title;
    for (const [selector, attribute, name, content] of [
      ['meta[name="description"]', "name", "description", description],
      ['meta[property="og:title"]', "property", "og:title", title],
      ['meta[property="og:description"]', "property", "og:description", description],
      ['meta[name="twitter:title"]', "name", "twitter:title", title],
      ['meta[name="twitter:description"]', "name", "twitter:description", description]
    ]) {
      let tag = document.head.querySelector(selector);
      if (!tag) {
        tag = document.createElement("meta");
        tag.setAttribute(attribute, name);
        document.head.appendChild(tag);
      }
      tag.setAttribute("content", content);
    }
    if (siteSettings.ogImage) {
      let imageTag = document.head.querySelector('meta[property="og:image"]');
      if (!imageTag) {
        imageTag = document.createElement("meta");
        imageTag.setAttribute("property", "og:image");
        document.head.appendChild(imageTag);
      }
      imageTag.setAttribute("content", siteSettings.ogImage);
      let twitterImage = document.head.querySelector('meta[name="twitter:image"]');
      if (!twitterImage) {
        twitterImage = document.createElement("meta");
        twitterImage.setAttribute("name", "twitter:image");
        document.head.appendChild(twitterImage);
      }
      twitterImage.setAttribute("content", siteSettings.ogImage);
    } else {
      document.head.querySelector('meta[property="og:image"]')?.remove();
      document.head.querySelector('meta[name="twitter:image"]')?.remove();
    }
  }, [profile.name, siteSettings]);

  useEffect(() => {
    function onScroll() { setScrolled(window.scrollY > 24); }
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    document.body.style.overflow = menuOpen || lightbox ? "hidden" : "";
    if (!menuOpen && !lightbox) return;
    function onKey(event) {
      if (event.key !== "Escape") return;
      setMenuOpen(false);
      setLightbox(null);
    }
    window.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = ""; window.removeEventListener("keydown", onKey); };
  }, [menuOpen, lightbox]);

  const storeById = useMemo(() => Object.fromEntries(storeBooks.map(book => [book._id, book])), [storeBooks]);
  const years = books.map(book => Number(book.year)).filter(Boolean);
  const stats = [
    [books.length, books.length === 1 ? "Published work" : "Published works"],
    years.length ? [Math.min(...years), "First publication"] : null,
    [new Set(books.map(book => book.format).filter(Boolean)).size || 1, "Forms of writing"]
  ].filter(Boolean);
  const titles = books.map(book => book.title).filter(Boolean);

  function navigate(next) {
    if (next === "admin") {
      window.location.assign("/admin");
      return;
    }
    setPage(next);
    setMenuOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function subscribeToNewsletter(event) {
    event.preventDefault();
    setNewsletterState({ status: "submitting", message: "" });
    try {
      const response = await fetch(`${apiBase}/api/newsletter/subscribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: newsletterEmail })
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || "Could not complete your subscription.");
      setNewsletterEmail("");
      setNewsletterState({ status: "success", message: result.message || "Thanks for subscribing." });
    } catch (requestError) {
      setNewsletterState({
        status: "error",
        message: requestError.message || "The newsletter could not be reached. Please try again."
      });
    }
  }

  const socials = [
    ["Facebook", Facebook, profile.facebook || defaultProfile.facebook],
    ["Instagram", Instagram, profile.instagram || defaultProfile.instagram],
    ["LinkedIn", Linkedin, profile.linkedin || defaultProfile.linkedin]
  ];

  return <div className="pf">
    <header className={`pf-header ${scrolled ? "is-scrolled" : ""}`}>
      <div className="wrap pf-header-inner">
        <button className="pf-brand" onClick={() => navigate("home")} aria-label={`${profile.name} — Author Home`}>
          <BrandMark size={42}/>
          <span className="pf-brand-copy"><strong>{profile.name}</strong><small>{profile.role}</small></span>
        </button>
        <nav id="portfolio-navigation" className="pf-nav" aria-label="Primary navigation">
          {navigation.map(([key, label]) => <button key={key} className={page === key ? "active" : ""} aria-current={page === key ? "page" : undefined} onClick={() => navigate(key)}>{label}</button>)}
        </nav>
        <div className="pf-header-actions">
          <ThemeToggle/>
          <a className="pf-icon-button" aria-label={`Send an email to ${profile.name}`} title="Send an email to the author" href={`mailto:${profile.email}`}><Mail size={16}/></a>
          <a className="pf-store-button" href="/store"><ShoppingBag size={15}/><span>Bookstore</span></a>
          <button className="pf-icon-button pf-menu-button" aria-label={menuOpen ? "Close navigation menu" : "Open navigation menu"} aria-expanded={menuOpen} aria-controls="portfolio-mobile-nav" onClick={() => setMenuOpen(!menuOpen)}>
            {menuOpen ? <X size={20}/> : <Menu size={20}/>}
          </button>
        </div>
      </div>
    </header>

    <div id="portfolio-mobile-nav" className={`pf-drawer ${menuOpen ? "open" : ""}`} aria-hidden={!menuOpen}>
      <div className="pf-drawer-inner">
        {navigation.map(([key, label], index) => <button key={key} tabIndex={menuOpen ? 0 : -1} className={page === key ? "active" : ""} style={{ "--pf-delay": `${index * 50}ms` }} onClick={() => navigate(key)}>
          <span>{`0${index + 1}`}</span>{label}<ArrowRight size={18}/>
        </button>)}
        <a href="/store" tabIndex={menuOpen ? 0 : -1} style={{ "--pf-delay": `${navigation.length * 50}ms` }}><span>{`0${navigation.length + 1}`}</span>Bookstore<ArrowRight size={18}/></a>
        <div className="pf-drawer-foot">
          <span>{profile.location} · {profile.role}</span>
          <a href={`mailto:${profile.email}`} tabIndex={menuOpen ? 0 : -1}><Mail size={14}/> {profile.email}</a>
        </div>
      </div>
    </div>

    <main key={page} className="pf-main">
      {page === "home" && <>
        <section className="pf-hero">
          <div className="pf-hero-glow" aria-hidden="true"/>
          <div className="wrap pf-hero-grid">
            <div className="pf-hero-copy">
              <div className="pf-eyebrow pf-rise" style={{ "--pf-delay": "60ms" }}>{profile.role}</div>
              <h1 className={`pf-rise ${`${profile.heroLead} ${profile.heroEmphasis}`.length > 40 ? "is-long" : ""}`} style={{ "--pf-delay": "140ms" }}>{profile.heroLead} <em>{profile.heroEmphasis}</em>.</h1>
              <p className="pf-rise" style={{ "--pf-delay": "240ms" }}>{profile.heroDescription}</p>
              <div className="pf-hero-actions pf-rise" style={{ "--pf-delay": "330ms" }}>
                <button className="pf-button" onClick={() => navigate("books")}>Explore published works <ArrowRight size={15}/></button>
                <a className="pf-button pf-button-ghost" href="/store"><ShoppingBag size={15}/> Visit the bookstore</a>
              </div>
              <dl className="pf-stats pf-rise" style={{ "--pf-delay": "420ms" }}>
                {stats.map(([value, label]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
              </dl>
            </div>
            <div className="pf-hero-art pf-rise" style={{ "--pf-delay": "200ms" }}>
              <div className="pf-orbit" aria-hidden="true"><span/><span/></div>
              <div className="pf-portrait"><img src={profile.portrait} {...responsiveSrcSet(profile.portrait)} sizes="(max-width: 700px) 92vw, 560px" alt={`${profile.name} author portrait`} fetchPriority="high"/></div>
              <span className="pf-hero-seal" aria-hidden="true"><BrandMark size={74}/></span>
            </div>
          </div>
          <button className="pf-scroll-cue" onClick={() => document.getElementById("pf-works")?.scrollIntoView({ behavior: "smooth" })} aria-label="Scroll to published works"><span/></button>
        </section>

        {titles.length > 0 && <div className="pf-marquee" aria-hidden="true"><div className="pf-marquee-track">
          {[...titles, ...titles, ...titles, ...titles].map((title, index) => <span key={index}>{title}<i>✦</i></span>)}
        </div></div>}

        <section className="pf-section" id="pf-works"><div className="wrap">
          <div className="pf-section-head">
            <Reveal><div className="pf-eyebrow">Selected bibliography</div><h2>Published works</h2><p>Stories, essays, and the worlds I return to.</p></Reveal>
            <Reveal delay={120}><button className="pf-text-link" onClick={() => navigate("books")}>View all works <ArrowRight size={14}/></button></Reveal>
          </div>
          <div className="pf-book-grid">{books.slice(0, 3).map((book, index) => <BookCard key={book._id || book.title || index} book={book} storeBook={storeById[book._id]} index={index}/>)}</div>
        </div></section>

        {profile.quote && <section className="pf-quote"><div className="wrap">
          <Reveal as="figure"><Quote size={34} aria-hidden="true"/><blockquote>{profile.quote}</blockquote><figcaption>— {profile.name}</figcaption></Reveal>
        </div></section>}

        <section className="pf-about-band"><div className="wrap pf-about-grid">
          <Reveal className="pf-about-photo"><img src={profile.landscape} {...responsiveSrcSet(profile.landscape)} sizes="(max-width: 700px) 92vw, 600px" alt="Landscape that inspires the author's work" loading="lazy" decoding="async"/><span className="pf-about-frame" aria-hidden="true"/></Reveal>
          <Reveal className="pf-about-copy" delay={120}>
            <div className="pf-eyebrow">The person behind the pages</div>
            <h2 className={profile.aboutHeading.length > 90 ? "pf-heading-long" : undefined}>{profile.aboutHeading}</h2>
            <p>{profile.aboutBiography}</p>
            <button className="pf-text-link" onClick={() => navigate("about")}>Read my story <ArrowRight size={14}/></button>
          </Reveal>
        </div></section>

        <section className="pf-store-band"><div className="wrap pf-store-band-grid">
          <Reveal className="pf-store-band-copy">
            <div className="pf-eyebrow">From the author's bookshelf</div>
            <h2>Signed copies, sent with care.</h2>
            <p>Order books directly from the author. Pay securely with eSewa, Khalti or bank transfer, and follow your order from payment to your doorstep.</p>
            <a className="pf-button pf-button-light" href="/store">Shop the bookstore <ArrowRight size={15}/></a>
          </Reveal>
          <Reveal className="pf-store-fan" delay={150} aria-hidden="true">
            {books.slice(0, 3).map((book, index) => <img key={book._id || book.title} src={book.image} {...responsiveSrcSet(book.image)} sizes="(max-width: 700px) 150px, 240px" alt="" loading="lazy" decoding="async" style={{ "--i": index }}/>)}
          </Reveal>
        </div></section>
      </>}

      {page === "about" && <>
        <SectionTitle eyebrow="A little about me" title={`Hello, I'm ${firstName}.`} note={profile.aboutHeading}/>
        <section className="wrap pf-about-grid pf-section">
          <Reveal className="pf-about-photo pf-about-portrait"><img src={profile.portrait} {...responsiveSrcSet(profile.portrait)} sizes="(max-width: 700px) 92vw, 600px" alt={`${profile.name} author portrait`} decoding="async"/><span className="pf-about-frame" aria-hidden="true"/></Reveal>
          <Reveal className="pf-about-copy" delay={120}>
            <div className="pf-eyebrow">The person behind the pages</div>
            <h2 className={profile.aboutPageTitle.length > 90 ? "pf-heading-long" : undefined}>{profile.aboutPageTitle}</h2>
            <p style={{ whiteSpace: "pre-line" }}>{profile.aboutPageBiography}</p>
            <p>I'm {profile.name}, a writer living in {profile.location}. I'm so glad you've found your way here.</p>
            <div className="pf-hero-actions">
              <button className="pf-button" onClick={() => navigate("books")}>Explore published works <ArrowRight size={15}/></button>
              <button className="pf-button pf-button-ghost" onClick={() => navigate("contact")}>Get in touch</button>
            </div>
          </Reveal>
        </section>
      </>}

      {page === "books" && <>
        <SectionTitle eyebrow="Bibliography" title="Published works" note="A collection of stories, essays, and ideas to spend time with."/>
        <section className="wrap pf-section"><div className="pf-book-grid">{books.map((book, index) => <BookCard key={book._id || book.title || index} book={book} storeBook={storeById[book._id]} index={index % 3}/>)}</div></section>
      </>}

      {page === "gallery" && <>
        <SectionTitle eyebrow="Inspiration & everyday life" title="A small visual collection" note="Places, pages, and moments gathered along the way."/>
        <section className="wrap pf-section">
          {gallery.length ? <div className="pf-gallery">{gallery.map((image, index) => <Reveal as="figure" key={image._id || image.url || index} delay={(index % 3) * 80}>
            <button onClick={() => setLightbox(image)} aria-label={`Open ${image.title || "image"}`}><img src={image.url} alt={image.altText || image.title || "Author gallery"} loading="lazy"/></button>
            {image.title && <figcaption>{image.title}</figcaption>}
          </Reveal>)}</div> : <div className="pf-empty"><BrandMark size={54}/><span>Gallery photographs will appear here soon.</span></div>}
        </section>
      </>}

      {page === "contact" && <>
        <SectionTitle eyebrow="Let's keep in touch" title="Send a little note." note="Reader notes, event invitations, and press inquiries are welcome."/>
        <section className="wrap pf-section pf-contact-grid">
          <Reveal className="pf-contact-card">
            <h2>I would love to hear from you.</h2>
            <p>For book club visits, interviews, speaking, or simply to say hello, please get in touch.</p>
            <a className="pf-contact-line" href={`mailto:${profile.email}`}><span><Mail size={16}/></span><div><small>Email</small>{profile.email}</div></a>
            <div className="pf-contact-line"><span><MapPin size={16}/></span><div><small>Location</small>{profile.location}</div></div>
            {["instagram", "facebook", "tiktok", "youtube", "threads"].some(key => profile[key]) && <div className="pf-contact-socials">
              {["instagram", "facebook", "tiktok", "youtube", "threads"].filter(key => profile[key]).map(key => <a key={key} href={profile[key]} target="_blank" rel="noreferrer">{key[0].toUpperCase() + key.slice(1)} <ArrowUpRight size={12}/></a>)}
            </div>}
          </Reveal>
          <Reveal as="form" className="pf-contact-form" delay={120} onSubmit={event => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            const subject = encodeURIComponent(String(form.get("subject") || "A note from your website"));
            const body = encodeURIComponent(`${form.get("name")}\n${form.get("email")}\n\n${form.get("message")}`);
            window.location.href = `mailto:${profile.email}?subject=${subject}&body=${body}`;
          }}>
            <div className="pf-form-grid">
              <label className="pf-field">Your name<input name="name" required autoComplete="name"/></label>
              <label className="pf-field">Email address<input name="email" type="email" required autoComplete="email"/></label>
              <label className="pf-field full">Subject<input name="subject"/></label>
              <label className="pf-field full">Your note<textarea name="message" required rows={6} placeholder="Write your note here..."/></label>
            </div>
            <button className="pf-button">Write to me <ArrowRight size={15}/></button>
          </Reveal>
        </section>
      </>}
    </main>

    {lightbox && <div className="pf-lightbox" role="dialog" aria-modal="true" aria-label={lightbox.title || "Gallery image"} onMouseDown={event => event.target === event.currentTarget && setLightbox(null)}>
      <button className="pf-icon-button" onClick={() => setLightbox(null)} aria-label="Close image"><X size={18}/></button>
      <figure><img src={lightbox.url} alt={lightbox.altText || lightbox.title || "Author gallery"}/>{lightbox.title && <figcaption>{lightbox.title}</figcaption>}</figure>
    </div>}

    <footer className="pf-footer">
      <div className="wrap">
        <div className="pf-footer-main">
          <div className="pf-footer-identity">
            <button className="pf-brand" onClick={() => navigate("home")} aria-label={`${profile.name} — Home`}>
              <BrandMark size={46}/>
              <span className="pf-brand-copy"><strong>{profile.name}</strong><small>{profile.role}</small></span>
            </button>
            <p className="pf-footer-tagline">Preserving Heritage, Sharing Stories</p>
            <div className="pf-footer-socials" aria-label="Social media">
              {socials.map(([label, Icon, href]) => <a key={label} href={href} target="_blank" rel="noreferrer" aria-label={`${profile.name} on ${label}`} title={label}><Icon size={15} strokeWidth={1.7}/></a>)}
            </div>
          </div>
          <nav className="pf-footer-nav" aria-label="Footer">
            <span className="pf-footer-label">Explore</span>
            {navigation.map(([key, label]) => <button key={key} onClick={() => navigate(key)}>{label}</button>)}
            <a href="/store">Bookstore</a>
            <a href="/store/track">Track an order</a>
          </nav>
          <section className="pf-footer-newsletter" aria-labelledby="newsletter-title">
            <span className="pf-footer-label">A letter now and then</span>
            <h2 id="newsletter-title">Notes from {firstName}</h2>
            <p>New books and occasional letters from my desk.</p>
            <form className="pf-newsletter" onSubmit={subscribeToNewsletter}>
              <label className="sr-only" htmlFor="newsletter-email">Email address</label>
              <input id="newsletter-email" type="email" name="email" autoComplete="email" placeholder="Your email address" required maxLength={320} value={newsletterEmail} onChange={event => {
                setNewsletterEmail(event.target.value);
                if (newsletterState.status !== "idle") setNewsletterState({ status: "idle", message: "" });
              }}/>
              <button type="submit" disabled={newsletterState.status === "submitting"}>{newsletterState.status === "submitting" ? "Joining…" : "Join"} <ArrowRight size={13}/></button>
            </form>
            <span className={`pf-newsletter-message ${newsletterState.status}`} aria-live="polite">{newsletterState.message}</span>
          </section>
        </div>
        <div className="pf-footer-bottom">
          <span>© {new Date().getFullYear()} {profile.name}. All rights reserved.</span>
          <div>
            <a href={`mailto:${profile.email}`}>Contact {firstName} <ArrowUpRight size={12}/></a>
            <button className="pf-admin-link" onClick={() => navigate("admin")}><LockKeyhole size={12}/> Admin Panel</button>
          </div>
        </div>
      </div>
    </footer>
  </div>;
}

