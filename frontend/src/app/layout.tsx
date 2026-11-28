import type { Metadata } from 'next';
import { Fraunces } from 'next/font/google';
import './globals.css';
import { AppProvider } from '../lib/store';
import Header from '../components/Header';
import { CompassPet } from '../components/CompassPet';
import { RouteTransition } from '../components/RouteTransition';

/* Display face (Restyle 2, aureon 2026-11-28): Fraunces — a
   high-contrast Didone-style serif — for display headings only.
   Latin-only, so CJK/Arabic fall back to the system stack via the
   font-family fallbacks in globals.css. next/font self-hosts it at
   build time, so there is no runtime font request. No oblique /
   italic anywhere on display type (Round 30 F4: synthetic slant
   breaks Arabic joining) — the variable font is loaded upright
   only, and globals.css pins font-style: normal on display classes. */
const displayFont = Fraunces({
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
          <footer className="bg-navy pb-10 pt-8 text-center text-sm text-white/75">
            <div className="mx-auto max-w-6xl px-4">
              PathPilot AI — Global AI Builder&apos;s Challenge 2026 · Day 1
            </div>
          </footer>
        </AppProvider>
      </body>
    </html>
  );
}
