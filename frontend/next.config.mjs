const workspaceApi = (process.env.WORKSPACE_API_URL ?? "http://127.0.0.1:8001").replace(/\/$/, "");

/** @type {import('next').NextConfig} */
const nextConfig = {
  poweredByHeader: false,
  devIndicators: false,
  async rewrites() {
    return [{ source: "/api/v2/:path*", destination: `${workspaceApi}/api/v2/:path*` }];
  },
};

export default nextConfig;
