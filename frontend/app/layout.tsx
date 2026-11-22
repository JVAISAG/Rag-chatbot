import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Research Workspace",
  description: "A private space for your research collections.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
