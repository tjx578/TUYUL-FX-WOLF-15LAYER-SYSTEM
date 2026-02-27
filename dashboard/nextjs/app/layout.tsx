export const metadata = {
  title: "TUYUL FX Dashboard",
  description: "Account, risk, ledger, and monitoring dashboard",
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