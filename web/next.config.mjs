/** @type {import('next').NextConfig} */
const isStaticExport = process.env.NEXT_STATIC_EXPORT === "1";
// GitHub Pages serves the repo under /<repo>/ — only for build:pages
const pagesBase = process.env.NEXT_PAGES === "1" ? "/stock-lab" : "";

const nextConfig = {
  // allow a side-by-side verification build without disturbing the dev server
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // static export for Cloudflare Pages (npm run build:static) — API routes
  // are moved aside by scripts/build-static.mjs during that build
  ...(isStaticExport ? { output: "export" } : {}),
  ...(pagesBase ? { basePath: pagesBase, assetPrefix: pagesBase } : {}),
};

export default nextConfig;
