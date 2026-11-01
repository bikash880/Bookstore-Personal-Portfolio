export const THEME_KEY = "site-theme";

// Runs in <head> before first paint. The forest-green ("dark") look is the site's default;
// a visitor's saved choice always wins, so a light preference never flashes dark.
export const themeBootScript = `(function(){try{var t=localStorage.getItem("${THEME_KEY}");if(t!=="light"&&t!=="dark"){t="dark"}document.documentElement.setAttribute("data-theme",t)}catch(e){document.documentElement.setAttribute("data-theme","dark")}})();`;
