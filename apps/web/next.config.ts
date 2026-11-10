import type { NextConfig } from "next";

const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // gzip in Next buffers the chat answer (text/event-stream) and defeats token streaming.
  compress: false,
  async rewrites() {
    // Same-origin proxy: the session cookie stays HttpOnly and no CORS is needed.
    return [{ source: "/api/v1/:path*", destination: `${apiUrl}/api/v1/:path*` }];
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
