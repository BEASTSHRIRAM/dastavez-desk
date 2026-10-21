import type { NextConfig } from "next";

// The app is client-driven (token auth, microphone, WebGL), so it does not use Cache Components.
const nextConfig: NextConfig = {
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
