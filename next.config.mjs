 /** @type {import('next').NextConfig} */
 const apiServerUrl = (process.env.API_SERVER_URL || "").replace(/\/+$/, "");

 const nextConfig = {
   allowedDevOrigins: ["127.0.0.1"],
   experimental: {
     // Admin backup restores upload ZIP files up to 200 MB through the /api proxy.
     proxyClientMaxBodySize: "200mb"
   },
   images: {
     remotePatterns: [{ protocol: "https", hostname: "images.unsplash.com" }]
   },
   async rewrites() {
     if (!apiServerUrl) return [];
     return [{
       source: "/api/:path*",
       destination: `${apiServerUrl}/api/:path*`
     }];
   }
 };

export default nextConfig;
  