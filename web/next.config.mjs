/** @type {import('next').NextConfig} */
const nextConfig = {
  // allow a side-by-side verification build without disturbing the dev server
  distDir: process.env.NEXT_DIST_DIR || ".next",
};

export default nextConfig;
