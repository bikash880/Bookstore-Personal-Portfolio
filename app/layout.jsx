import { Fraunces, Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import InteractiveEffects from "./interactive-effects";
import { themeBootScript } from "./theme-script";

// Self-hosted at build time and preloaded, replacing a render-blocking Google Fonts @import.
// Axes match the previous request: Fraunces optical size + weight, Plus Jakarta Sans weight.
const serifFont = Fraunces({
  subsets: ["latin", "latin-ext"],
  style: ["normal", "italic"],
  axes: ["opsz"],
  display: "swap",
  variable: "--font-serif"
});
const sansFont = Plus_Jakarta_Sans({
  subsets: ["latin", "latin-ext"],
  display: "swap",
  variable: "--font-sans"
});

export const dynamic = "force-dynamic";

const defaultName = "Binod Kumar Mahato";
const defaultTitle = `${defaultName} — Preserving Heritage, Sharing Stories`;
const defaultDescription = `Discover published works and the author profile of ${defaultName}.`;
const metadataCacheTtl = 60_000;
const metadataFailureCacheTtl = 60_000;
const maximumMetadataFailureCacheTtl = 15 * 60_000;
// While maintenance mode is on, re-check often so real titles return soon after it ends.
const maintenanceCacheTtl = 5_000;
let cachedContent = null;
let cacheExpiresAt = 0;
let contentRequest = null;

function getRetryAfterMs(response) {
  const retryAfter = response.headers.get("retry-after");
  if (!retryAfter) return null;

  const retryAfterSeconds = Number(retryAfter);
  const requestedDelay = Number.isFinite(retryAfterSeconds)
    ? retryAfterSeconds * 1000
    : Date.parse(retryAfter) - Date.now();
  return Number.isFinite(requestedDelay) && requestedDelay > 0
    ? Math.min(requestedDelay, maximumMetadataFailureCacheTtl)
    : null;
}

function retryDelay(response, attempt) {
  const requestedDelay = getRetryAfterMs(response) ?? 200 * (2 ** attempt);
  return Math.min(Math.max(0, requestedDelay), 750);
}

async function requestPortfolioContent() {
  const apiUrl = (
    process.env.API_SERVER_URL
    || process.env.NEXT_PUBLIC_API_URL
  ).replace(/\/+$/, "");
  if (!apiUrl) {
    console.warn("Portfolio metadata is using defaults because API_SERVER_URL or NEXT_PUBLIC_API_URL is not configured.");
    return { content: [], successful: false };
  }
  let lastError;
  let retryAfterMs = null;

  for (let attempt = 0; attempt < 3; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 2000);
    try {
      const response = await fetch(`${apiUrl}/api/content`, {
        signal: controller.signal,
        next: { revalidate: 60 }
      });
      if (response.ok) {
        const result = await response.json();
        return { content: result.content || [], successful: true };
      }

      lastError = new Error(`Portfolio metadata request failed (${response.status}).`);
      if (response.status === 503) {
        const body = await response.json().catch(() => ({}));
        // Maintenance is an expected state, not an outage: no retries and no warning.
        if (body.maintenance) return { content: [], successful: false, maintenance: true };
      }
      if (response.status === 429) {
        retryAfterMs = getRetryAfterMs(response);
        break;
      }
      if (response.status < 500) break;
      if (attempt < 2) await new Promise(resolve => setTimeout(resolve, retryDelay(response, attempt)));
    } catch (error) {
      lastError = error;
      if (attempt < 2) await new Promise(resolve => setTimeout(resolve, 200 * (2 ** attempt)));
    } finally {
      clearTimeout(timeout);
    }
  }

  console.warn("Using default portfolio metadata because site content could not be loaded:", lastError);
  return { content: [], successful: false, retryAfterMs };
}

async function getPortfolioContent() {
  if (cachedContent && Date.now() < cacheExpiresAt) return cachedContent;
  if (!contentRequest) {
    contentRequest = requestPortfolioContent().then(result => {
      cachedContent = result.content;
      cacheExpiresAt = Date.now() + (
        result.successful
          ? metadataCacheTtl
          : result.maintenance
            ? maintenanceCacheTtl
            : Math.max(metadataFailureCacheTtl, result.retryAfterMs ?? 0)
      );
      return result.content;
    }).finally(() => {
      contentRequest = null;
    });
  }
  return contentRequest;
}

export async function generateMetadata() {
  try {
    const content = await getPortfolioContent();
    const settings = content.find(item => item.key === "site-settings")?.value || {};
    const profile = content.find(item => item.key === "author-profile")?.value || {};
    const authorName = typeof profile.name === "string" ? profile.name : defaultName;
    const title = settings.seoTitle || settings.siteTitle || `${authorName} — Preserving Heritage, Sharing Stories`;
    const description = settings.seoDescription || `Discover published works and the author profile of ${authorName}.`;
    const images = typeof settings.ogImage === "string" && settings.ogImage.startsWith("https://")
      ? [settings.ogImage]
      : [];
    return {
      title,
      description,
      openGraph: { title, description, type: "website", images },
      twitter: { card: images.length ? "summary_large_image" : "summary", title, description, images }
    };
  } catch (error) {
    console.warn("Could not load portfolio SEO settings; using defaults:", error);
    return {
      title: defaultTitle,
      description: defaultDescription,
      openGraph: { title: defaultTitle, description: defaultDescription, type: "website" }
    };
  }
}

export default function RootLayout({ children }) {
  return (
    <html lang="en" data-scroll-behavior="smooth" data-theme="dark" className={`${serifFont.variable} ${sansFont.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootScript }}/>
      </head>
      <body>{children}<InteractiveEffects/></body>
    </html>
  );
}
