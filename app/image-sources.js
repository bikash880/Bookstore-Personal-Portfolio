// Builds a srcset for Unsplash images so small screens download a narrower copy of the same
// photo. Other hosts are returned untouched (an empty object spreads to nothing).
const UNSPLASH_HOST = "images.unsplash.com";
const WIDTHS = [400, 600, 800, 1200];

export function responsiveSrcSet(url) {
  if (typeof url !== "string") return {};
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return {};
  }
  const original = Number(parsed.searchParams.get("w"));
  if (parsed.hostname !== UNSPLASH_HOST || !Number.isFinite(original) || original <= 0) return {};
  const candidates = WIDTHS.filter(width => width < original);
  if (!candidates.length) return {};
  const srcSet = [...candidates, original].map(width => {
    parsed.searchParams.set("w", String(width));
    return `${parsed.toString()} ${width}w`;
  }).join(", ");
  return { srcSet };
}
