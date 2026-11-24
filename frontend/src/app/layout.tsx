import type { Metadata } from 'next';
import './globals.css';
import { AppProvider } from '../lib/store';
import Header from '../components/Header';

export const metadata: Metadata = {
  title: 'PathPilot AI — Evidence-based university selection',
  description: 'Check the minimum requirements for real UK and Singapore programmes, with the official source for every rule.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" dir="ltr">
      <body className="min-h-screen">
        <AppProvider>
          <Header />
          <main>{children}</main>
          <footer className="mx-auto max-w-6xl px-4 pb-10 pt-6 text-center text-sm text-navy/70">
            PathPilot AI — Global AI Builder&apos;s Challenge 2026 · Day 1
          </footer>
        </AppProvider>
      </body>
    </html>
  );
}
