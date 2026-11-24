/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    // Day 2: the backend base is env-driven so the preview deployment can
    // point at a hosted FastAPI URL; locally it defaults to :8000.
    const apiBase = process.env.API_BASE_URL || 'http://localhost:8000';
    return [{ source: '/api/:path*', destination: `${apiBase}/api/v1/:path*` }];
  },
};
module.exports = nextConfig;
