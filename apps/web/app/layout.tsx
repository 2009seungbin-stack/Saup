import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {title: 'Saup · 운영 콘솔', description: 'Consignment commerce operations', robots: {index: false, follow: false}};
export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="ko"><body>{children}</body></html>;
}
