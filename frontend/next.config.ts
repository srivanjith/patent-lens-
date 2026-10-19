import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          {
            key: "Cross-Origin-Opener-Policy",
            value: "same-origin-allow-popups",
          },
        ],
      },
    ];
  },
  async rewrites() {
    // BACKEND_URL is a server-side-only env var set in Vercel project settings.
    // It must be the full URL of the deployed backend (e.g. https://patent-backend.vercel.app).
    // NEXT_PUBLIC_API_BASE_URL is used as a fallback (also set in Vercel env settings).
    const backendUrl = (process.env.BACKEND_URL || "").trim();
    const publicUrl = (process.env.NEXT_PUBLIC_API_BASE_URL || process.env.NEXT_PUBLIC_API_URL || "").trim();

    // Prefer BACKEND_URL (server-side, never exposed to client). Fall back to public URL.
    let rawUrl = backendUrl || publicUrl;

    // Skip rewriting if nothing useful is set or it points to localhost (local dev uses direct calls)
    if (
      !rawUrl ||
      rawUrl === "/api" ||
      rawUrl === "api" ||
      rawUrl.includes("localhost") ||
      rawUrl.includes("127.0.0.1")
    ) {
      return [];
    }

    let targetUrl = rawUrl;
    if (!targetUrl.startsWith("http://") && !targetUrl.startsWith("https://")) {
      targetUrl = `https://${targetUrl}`;
    }
    // Ensure the target ends with /api
    targetUrl = targetUrl.endsWith("/api")
      ? targetUrl
      : `${targetUrl.replace(/\/$/, "")}/api`;

    return [
      {
        source: "/api/:path*",
        destination: `${targetUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
