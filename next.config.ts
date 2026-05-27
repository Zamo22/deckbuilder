import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // In dev, proxy /api/* to the FastAPI dev server on :8000.
  // In production on Vercel, /api/* is handled by Python serverless
  // functions (configured via vercel.json) so this rewrite is a no-op.
  async rewrites() {
    if (process.env.NODE_ENV !== "development") return [];
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
