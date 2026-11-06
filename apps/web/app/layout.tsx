import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NAWA.AI",
  description: "Self-hosted Enterprise Intelligence & Automation Platform",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
