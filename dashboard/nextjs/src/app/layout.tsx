import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'TUYUL FX WOLF 15-LAYER SYSTEM',
  description: 'Professional Forex Trading System Dashboard',
  icons: {
    icon: '/favicon.ico',
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-wolf-darker antialiased">
        {children}
      </body>
    </html>
  );
}
