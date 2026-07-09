import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Backend FastAPI runs on :8000 in dev. This rewrite lets the frontend
  // call /api/... as same-origin, sidestepping CORS in the browser.
  // (The backend also has CORS allow-listed for localhost:3000 as a fallback.)
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/:path*",
      },
    ];
  },
};

export default nextConfig;
