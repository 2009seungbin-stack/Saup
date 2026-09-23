const backend = process.env.API_INTERNAL_URL || 'http://127.0.0.1:8000';
const config = {
  poweredByHeader: false,
  async rewrites() { return [{ source: '/api/:path*', destination: `${backend}/:path*` }]; },
  async headers() {
    return [{ source: '/:path*', headers: [
      { key: 'X-Content-Type-Options', value: 'nosniff' },
      { key: 'X-Frame-Options', value: 'DENY' },
      { key: 'Referrer-Policy', value: 'no-referrer' },
      { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' }
    ] }];
  }
};
export default config;
