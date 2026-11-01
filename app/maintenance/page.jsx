import MaintenanceScreen from "./maintenance-screen";

export const metadata = {
  title: "🛠️ Server is down — back soon",
  robots: { index: false, follow: false }
};

async function fetchStatus() {
  const apiUrl = (process.env.API_SERVER_URL || process.env.NEXT_PUBLIC_API_URL || "").replace(/\/+$/, "");
  if (!apiUrl) return null;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2000);
  try {
    const response = await fetch(`${apiUrl}/api/site/status`, { signal: controller.signal, cache: "no-store" });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

export default async function MaintenancePage() {
  return <MaintenanceScreen initial={await fetchStatus()}/>;
}
