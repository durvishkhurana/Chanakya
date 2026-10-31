/** @type {import('next').NextConfig} */
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const nextConfig = {
  // Same-origin proxy for REST calls, so the backend's CORS policy stays unchanged. On the laptop WebSockets connect
  // directly; on a phone through the tunnel they come through this proxy too.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
  // The phone link (Cloudflare quick tunnel) serves the dev server from a trycloudflare.com host.
  allowedDevOrigins: ["*.trycloudflare.com"],
};

export default nextConfig;
