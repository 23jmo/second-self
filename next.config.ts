import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        // Proxy all /api/* requests to FastAPI EXCEPT /auth/* (handled by Auth0 middleware)
        source: "/api/:path((?!auth).*)",
        destination: "http://localhost:8000/:path*",
      },
    ];
  },
};

export default nextConfig;
