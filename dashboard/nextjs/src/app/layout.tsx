import type { Metadata } from "next";
import QueryProvider from "@/components/providers/QueryProvider";
import ToastViewport from "@/components/feedback/ToastViewport";
import "./globals.css";

export const metadata: Metadata = {
  title: "TUYUL FX Terminal",
  description: "Constitution-first trading observability terminal",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <QueryProvider>
          {children}
          <ToastViewport />
        </QueryProvider>
      </body>
    </html>
  );
}

