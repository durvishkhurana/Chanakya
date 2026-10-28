import "./globals.css";

export const metadata = {
  title: "Chanakya | Let’s talk business",
  description:
    "Meet Chanakya, an independent AI voice advisor for Paytm payment products.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
