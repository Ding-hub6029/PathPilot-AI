import { Profile } from './types';

/**
 * Round 31 G3 — the synthetic-sample marker follows the profile's
 * provenance, never stale state.
 *
 * The "Synthetic sample — not a real student" banner renders wherever
 * `profile.sample` is true (wizard, /results, /report). The flag is
 * set only by the two sample literals (`sampleUndergrad` /
 * `sampleMasters` in types.ts), but before this fix nothing ever
 * cleared it: `updateProfile` merged patches over the previous
 * profile, and the wizard's profile import spread the OLD profile
 * first (`{ ...profile, ...p }`), so a loaded sample kept
 * `sample: true` after the user replaced it with their own Gaokao
 * profile or edited any field — the banner then contradicted the
 * profile on screen.
 */

/**
 * Apply a user edit to the profile. Any edit clears the
 * synthetic-sample marker: the banner must only show while the
 * synthetic sample IS the active profile. No caller passes `sample`
 * in a patch — loading a sample goes through `setProfile` with the
 * sample objects instead, so this never clears a freshly loaded
 * sample.
 */
export function applyProfilePatch(prev: Profile, patch: Partial<Profile>): Profile {
  return { ...prev, ...patch, sample: false };
}

/**
 * Merge an imported profile file over the current profile. The banner
 * follows the imported file's own flag, never the profile being
 * replaced: an imported file with no `sample` field (a user's own
 * exported Gaokao profile) clears the banner, while re-importing an
 * exported sample file (`sample: true`) keeps it.
 */
export function mergeImportedProfile(prev: Profile, imported: Profile): Profile {
  return { ...prev, ...imported, sample: imported.sample === true };
}
