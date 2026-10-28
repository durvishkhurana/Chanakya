import "./globals.css";

export const metadata = {
  title: "Chanakya | AI teammate for merchant sales and service",
  description:
    "Chanakya calls merchants in their own language, hears the worry they do not say, plans its next move and checks the job is really done. An independent hackathon project.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
