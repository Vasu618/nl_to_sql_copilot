import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NL-to-SQL Analytics Copilot",
  description:
    "Ask plain-English questions about an e-commerce database. Get validated SQL, executed results, charts, and a plain-English answer — with a self-correction loop and anti-overclaiming safety checks.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
