import type { Metadata } from 'next';
import { Space_Grotesk } from 'next/font/google';
import './globals.css';
import { AppProvider } from '../lib/store';
import Header from '../components/Header';
import { CompassPet } from '../components/CompassPet';
import { RouteTransition } from '../components/RouteTransition';

/* Display face (restyle 2026-11-28): Space Grotesk — a slightly
   geometric sans, deliberately NOT Inter — for display headings only.
   Latin-only, so CJK/Arabic fall back to the system stack via the
   font-family fallbacks in globals.css. next/font self-hosts it at
   build time, so there is no runtime font request. */
const displayFont = Space_Grotesk({
  subsets: ['latin'],
  weight: ['500', '700'],
  variable: '--font-display',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'PathPilot AI — Evidence-based university selection',
  description: 'Check the minimum requirements for real programmes from universities worldwide, with the official source for every rule.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" dir="ltr" className={displayFont.variable}>
      <body className="min-h-screen">
        <AppProvider>
          <Header />
          {/* tabIndex -1 so RouteTransition can move keyboard focus here
              on route change (preventScroll — scroll restoration intact). */}
          <main tabIndex={-1} className="outline-none">
            <RouteTransition>{children}</RouteTransition>
          </main>
          <CompassPet />
          <footer className="mx-auto max-w-6xl px-4 pb-10 pt-6 text-center text-sm text-navy/70">
            PathPilot AI — Global AI Builder&apos;s Challenge 2026 · Day 1
          </footer>
        </AppProvider>
      </body>
    </html>
  );
}
