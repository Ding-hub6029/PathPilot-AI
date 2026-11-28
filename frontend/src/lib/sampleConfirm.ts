import { Profile, emptyProfile, sampleMasters, sampleUndergrad } from './types';

/**
 * Round 31, G2 — "Try a sample profile" used to wipe the user's data
 * with one click. Both call sites (the homepage's trySample and the
 * wizard's loadSample) called setProfile(sample) unconditionally, and
 * setProfile replaces the WHOLE profile — every filled wizard field
 * and all 8 preference-chat answers (prefClimate / prefCountries /
 * prefEnvironment / prefCity / prefAfterGrad / prefSalary /
 * prefPressure / prefTeaching) went back to empty, with no warning.
 * The tester had to re-enter everything.
 *
 * hasProfileData decides whether that overwrite needs a confirmation
 * dialog. It is true when the profile holds anything the user typed
 * or the pref chat recorded, and false in exactly two no-data cases:
 *   - the profile is empty (nothing filled yet), and
 *   - the profile is still exactly one of the two samples (a sample
 *     just loaded holds no user data, so loading another sample over
 *     it stays one-click; any edit after loading breaks the exact
 *     match and counts as user data).
 * Two fields never count on their own: `sample` (the synthetic
 * marker) and `targetProgramIds` (a derived list the wizard finish
 * step writes from the evaluated matches — never typed in).
 */

// Keys that never count as user-entered data on their own (see above).
const IGNORED_KEYS: (keyof Profile)[] = ['sample', 'targetProgramIds'];

function fieldEquals(a: unknown, b: unknown): boolean {
  if (Array.isArray(a) || Array.isArray(b)) {
    return JSON.stringify(a ?? []) === JSON.stringify(b ?? []);
  }
  return a === b;
}

function profilesEqualOn(a: Profile, b: Profile, keys: (keyof Profile)[]): boolean {
  return keys.every((k) => fieldEquals(a[k], b[k]));
}

export function hasProfileData(profile: Profile): boolean {
  const allKeys = Object.keys(emptyProfile) as (keyof Profile)[];
  if (profile.sample) {
    // A freshly loaded sample holds no user data — but only while it
    // is still exactly that sample.
    const sampleKeys = [...allKeys, 'sample', 'targetProgramIds'] as (keyof Profile)[];
    if (profilesEqualOn(profile, sampleUndergrad, sampleKeys)
      || profilesEqualOn(profile, sampleMasters, sampleKeys)) {
      return false;
    }
  }
  const userKeys = allKeys.filter((k) => !IGNORED_KEYS.includes(k));
  return !profilesEqualOn(profile, emptyProfile, userKeys);
}
