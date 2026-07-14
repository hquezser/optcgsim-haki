import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OPTCGSim Tracker — Live",
  description: "Tracker temps réel pour OPTCGSim",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="fr" className="h-full antialiased">
      <body className="min-h-full bg-slate-950 text-slate-200">{children}</body>
    </html>
  );
}
