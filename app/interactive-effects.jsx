"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { ArrowUp } from "lucide-react";

// Elements that get a 3D tilt and a soft light glare following the pointer.
const TILT_SELECTOR = ".pf-book-cover, .store-book-cover, .store-detail-cover-large, .pf-portrait, .pf-floating-book, .store-hero-feature";

export default function InteractiveEffects() {
  const pathname = usePathname() || "";
  const isAdmin = pathname.startsWith("/admin");
  const progressBar = useRef(null);
  const [showTop, setShowTop] = useState(false);

  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
    if (reduced || !finePointer) return;
    let frame = 0;
    let active = null;

    function reset(element) {
      element.style.removeProperty("--tilt-x");
      element.style.removeProperty("--tilt-y");
      element.classList.remove("is-tilting");
    }

    function onMove(event) {
      const target = event.target instanceof Element ? event.target.closest(TILT_SELECTOR) : null;
      if (active && active !== target) reset(active);
      active = target;
      if (!target) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const box = target.getBoundingClientRect();
        const x = (event.clientX - box.left) / box.width;
        const y = (event.clientY - box.top) / box.height;
        target.style.setProperty("--tilt-x", `${((0.5 - y) * 9).toFixed(2)}deg`);
        target.style.setProperty("--tilt-y", `${((x - 0.5) * 11).toFixed(2)}deg`);
        target.style.setProperty("--glare-x", `${(x * 100).toFixed(1)}%`);
        target.style.setProperty("--glare-y", `${(y * 100).toFixed(1)}%`);
        target.classList.add("is-tilting");
      });
    }

    function onLeave() {
      if (active) reset(active);
      active = null;
    }

    document.addEventListener("pointermove", onMove, { passive: true });
    document.addEventListener("pointerleave", onLeave);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerleave", onLeave);
    };
  }, []);

  useEffect(() => {
    if (isAdmin) return;
    let frame = 0;
    function update() {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const max = document.documentElement.scrollHeight - window.innerHeight;
        // Written straight to the element so scrolling never re-renders React.
        if (progressBar.current) progressBar.current.style.transform = `scaleX(${max > 0 ? Math.min(1, window.scrollY / max) : 0})`;
        setShowTop(window.scrollY > 700);
      });
    }
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [isAdmin, pathname]);

  if (isAdmin) return null;
  return <>
    <div ref={progressBar} className="fx-progress" aria-hidden="true" style={{ transform: "scaleX(0)" }}/>
    <button
      className={`fx-top ${showTop ? "is-visible" : ""}`}
      onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
      aria-label="Back to top"
      tabIndex={showTop ? 0 : -1}
    ><ArrowUp size={18}/></button>
  </>;
}
