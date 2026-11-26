import { redirect } from 'next/navigation';

/**
 * /universities used to 404 — the institution list lives at
 * /institutions, so redirect there instead of leaving a dead route.
 */
export default function UniversitiesPage() {
  redirect('/institutions');
}
