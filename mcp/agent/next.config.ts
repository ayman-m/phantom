import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'standalone',
  // Operator-facing path aliases. Keep the canonical UI page at the
  // shorter URL but also accept the API-resource name so users who
  // remember "/api/agent/agent-definitions" don't 404 when they type
  // /agent-definitions in the browser.
  async redirects() {
    return [
      {
        source: '/agent-definitions',
        destination: '/agents',
        permanent: false,
      },
      {
        source: '/agent-definitions/:id',
        destination: '/agents/:id',
        permanent: false,
      },
    ];
  },
};

export default nextConfig;
