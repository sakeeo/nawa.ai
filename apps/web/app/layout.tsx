import type { Metadata } from "next";
import { Suspense } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "NAWA.AI",
  description: "Self-hosted Enterprise Intelligence & Automation Platform",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">
        <Suspense fallback={<p className="p-8 text-sm text-gray-500">Loading...</p>}>
          {children}
        </Suspense>
      </body>
    </html>
  );
}
