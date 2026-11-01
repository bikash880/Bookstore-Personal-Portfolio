"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { THEME_KEY } from "./theme-script";

function applyTheme(next) {
  document.documentElement.setAttribute("data-theme", next);
  try { window.localStorage.setItem(THEME_KEY, next); } catch { /* private mode: the choice lasts for this visit */ }
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState(null);

  useEffect(() => {
    setTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light");
  }, []);

  function toggle(event) {
    const next = theme === "dark" ? "light" : "dark";
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const root = document.documentElement;
    if (reduced) {
      applyTheme(next);
      setTheme(next);
      return;
    }
    if (document.startViewTransition) {
      // Circular reveal growing out of the button.
      const box = event.currentTarget.getBoundingClientRect();
      const x = box.left + box.width / 2;
      const y = box.top + box.height / 2;
      const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
      const transition = document.startViewTransition(() => {
        applyTheme(next);
        setTheme(next);
      });
      transition.ready.then(() => {
        root.animate(
          { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
          { duration: 650, easing: "cubic-bezier(.2,.7,.2,1)", pseudoElement: "::view-transition-new(root)" }
        );
      }).catch(() => {});
      return;
    }
    root.classList.add("theme-fading");
    applyTheme(next);
    setTheme(next);
    window.setTimeout(() => root.classList.remove("theme-fading"), 600);
  }

  const dark = theme === "dark";
  return <button
    type="button"
    className={`pf-icon-button theme-toggle ${dark ? "is-dark" : ""}`}
    onClick={toggle}
    aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
    title={dark ? "Light mode" : "Dark mode"}
    aria-pressed={dark}
  >
    <Sun size={17} className="theme-icon theme-icon-sun"/>
    <Moon size={16} className="theme-icon theme-icon-moon"/>
  </button>;
}
