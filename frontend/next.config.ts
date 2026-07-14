import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Export statique : le build produit un dossier out/ servi par FastAPI.
  // En dev, on utilise next dev (port 3000) qui consomme l'API FastAPI (port 8765).
  output: "export",
  // Les images sont servies par l'API FastAPI, pas besoin d'optimisation.
  images: { unoptimized: true },
};

export default nextConfig;
