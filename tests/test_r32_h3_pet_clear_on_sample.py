"""Round 32 H3 — pet old conversation does not clear on profile replace
(re-test 28, 2026-11-28 18:44-18:55, gateway down whole run).

Tester sequence: with a pet conversation already open ("Undergraduate",
"Switzerland" choice bubbles), load a sample profile from the homepage.
The profile card then showed the sample's preferences (missing), but
the pet kept the OLD bubbles — the sample-load path never reset the
pet's conversation.

Root cause: the Round 23 W2 / Round 29 E6 clear-data reset works
through ``dataClearNonce`` — ``clearData`` bumps it (store.tsx) and
CompassPet watches it and resets messages / answers / step, devil
off, re-greets. Loading a sample goes through ``setProfile`` instead
(homepage ``page.tsx:55`` ``loadSample``, wizard ``wizard/page.tsx:263``
``applySample``), and ``setProfile`` never bumped any nonce — so the
pet never heard about the replace. Same for an own-file import
(``wizard/page.tsx:283``), which also goes through ``setProfile``.

Fix (frontend-only, no copy / data / route / i18n change): ``setProfile``
bumps a new ``profileReplaceNonce`` in the store, and CompassPet gains
a second reset effect watching it — same reset body as the clear-data
effect (messages / answers / step cleared, devil off, shared verdict
reset, re-greet + fresh probe while open), its own ref seeded at
mount. The reset therefore fires on the actual load, after the
Round 31 G2 confirm dialog: the dialogs only call ``loadSample`` /
``applySample`` from ``onConfirm``; opening the dialog only sets the
pending flag and calls no ``setProfile``.

Why a SEPARATE nonce, not the existing ``dataClearNonce``: the wizard
also subscribes to ``dataClearNonce`` and resets its step to 0. The
wizard sample load sets step 7 in the same handler
(``applySample``: ``setProfile({ ...s }); setStep(7);``) — a
``dataClearNonce`` bump there would let the wizard's post-commit
effect overwrite step 7 with 0. ``profileReplaceNonce`` is watched
only by CompassPet, so the wizard step survives. It is also a
separate EFFECT, not a second dep on the clear-data effect: the
Round 23 W2 / Round 25 W3 / Round 30 F3 pins slice the clear effect
by its ``}, [dataClearNonce]);`` close, and merging the deps would
break all three. ``updateProfile`` (patch edits) bumps neither nonce,
so an edit mid-chat keeps the conversation; ``clearData`` does not
bump the new nonce either (it uses ``setProfileState`` directly and
already bumps ``dataClearNonce``), so a clear still resets exactly
once.

PrefChat needs no change here: its stored snapshot is restored only
when its fingerprint matches the CURRENT profile
(``parsePrefChatState`` in lib/chat.ts returns null on mismatch), so
a stale pref-chat blob can never resurrect under the sample — unlike
the pet, whose conversation is in-memory only and has no such guard.

Run from the project root:
    .venv/bin/pytest tests/test_r32_h3_pet_clear_on_sample.py -q -p no:cacheprovider
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"
STORE = FE / "src" / "lib" / "store.tsx"
PET = FE / "src" / "components" / "CompassPet.tsx"
HOME = FE / "src" / "app" / "page.tsx"
WIZARD = FE / "src" / "app" / "wizard" / "page.tsx"
PREFCHAT = FE / "src" / "components" / "PrefChat.tsx"

# ---------------------------------------------------------------------------
# The reset-effect decision logic, simulated against the real source.
#
# CompassPet cannot be mounted in this harness (no DOM), so the
# simulation replays the effect's ref guard — seeded at mount, fires
# only on a bump since mount — over nonce sequences, while the source
# pins below assert the guard, the refs and the reset body are the
# real code in CompassPet.tsx, not a reimplementation here. The
# simulation reads the two nonce names and the reset setters out of
# the real effect source, so a rename / dropped setter breaks it.
# ---------------------------------------------------------------------------

_NODE_HARNESS = r"""
const fs = require('fs');
const pet = fs.readFileSync(PET, 'utf8');
const store = fs.readFileSync(STORE, 'utf8');
let fail = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fail++; console.log('FAIL ' + name + ': got ' + JSON.stringify(got) + ' want ' + JSON.stringify(want)); }
  else console.log('ok ' + name);
}

// The replace effect as written in the real source: its own ref
// seeded at mount, fires only on a bump since mount. The clear-data
// effect above it is byte-identical to before (same
// `}, [dataClearNonce]);` close), so the Round 23 W2 / Round 25 W3 /
// Round 30 F3 pins that slice it keep working.
const replaceAt = pet.indexOf('Round 32, H3');
const replaceEnd = pet.indexOf('}, [profileReplaceNonce]);', replaceAt);
const replaceEffect = pet.slice(replaceAt, replaceEnd);
check('replace effect block found', replaceAt !== -1 && replaceEnd !== -1, true);
check('replace effect guards on its own ref',
  /const replaceNonceRef = useRef\(profileReplaceNonce\);/.test(pet)
  && /if \(profileReplaceNonce === replaceNonceRef\.current\) return;/.test(replaceEffect), true);
check('clear-data effect close unchanged',
  pet.includes('}, [dataClearNonce]);'), true);
for (const line of ['setMessages([]);', 'setAnswers({});', 'setStep(0);',
                    'setDevilMode(false);', 'resetAiVerdict();', 'setWaking(false);',
                    'greet();', 'runProbe({ minChecking: true });']) {
  check('replace effect reset body contains ' + line, replaceEffect.includes(line), true);
}
// The store is the only place that may bump the replace nonce, and it
// does so exactly in setProfile (wholesale replace), never in a patch
// edit or in clearData.
check('store bumps replace nonce in setProfile',
  /const setProfile = \(p: Profile\) => \{ setProfileState\(p\); setProfileReplaceNonce\(\(n\) => n \+ 1\); \};/.test(store), true);
check('store does NOT bump replace nonce in updateProfile',
  !/applyProfilePatch[\s\S]{0,200}setProfileReplaceNonce/.test(store), true);
check('store does NOT bump replace nonce in clearData',
  !/const clearData = \(\) => \{[\s\S]{0,1200}setProfileReplaceNonce/.test(store), true);

// --- Replay the ref guards over nonce sequences ------------------------
// Two effects, two refs, both seeded at mount; either firing resets
// the conversation. Pet state: a prior conversation (the re-test's
// "Undergraduate" / "Switzerland" bubbles) + devil on, as it stands
// before the load.
function mount() {
  return { clearRef: 0, replaceRef: 0,
           messages: ['Undergraduate', 'Switzerland'], answers: { degree: 'ug' },
           step: 2, devil: true, resets: 0 };
}
function effectTick(s, dataClearNonce, profileReplaceNonce, open) {
  let fired = false;
  if (dataClearNonce !== s.clearRef) { s.clearRef = dataClearNonce; fired = true; }
  if (profileReplaceNonce !== s.replaceRef) { s.replaceRef = profileReplaceNonce; fired = true; }
  if (!fired) return false;
  s.messages = []; s.answers = {}; s.step = 0; s.devil = false; s.resets++;
  if (open) s.messages = ['<re-greeted against the new profile>'];
  return true;
}

// (a) The defect, re-test 28: sample load with a prior conversation.
let s = mount();
check('sample load bumps replace nonce -> reset fires',
  effectTick(s, 0, 1, true), true);
check('sample load clears the old bubbles', s.messages,
  ['<re-greeted against the new profile>']);
check('sample load clears answers/step/devil',
  [s.answers, s.step, s.devil], [{}, 0, false]);
check('sample load resets exactly once', s.resets, 1);

// (b) No spurious reset: a re-render with unchanged nonces does nothing.
check('unchanged nonces -> no reset', effectTick(s, 0, 1, true), false);
check('no spurious reset counted', s.resets, 1);

// (c) A patch edit (updateProfile) bumps NEITHER nonce -> no reset.
s = mount();
check('patch edit -> no reset', effectTick(s, 0, 0, true), false);
check('patch edit keeps the conversation', s.messages,
  ['Undergraduate', 'Switzerland']);

// (d) The clear-data path still works, unchanged (Round 23 W2 / E6).
s = mount();
check('clear-data bumps clear nonce -> reset fires',
  effectTick(s, 1, 0, true), true);
check('clear-data clears the old bubbles', s.messages,
  ['<re-greeted against the new profile>']);
check('clear-data resets exactly once', s.resets, 1);

// (e) Panel closed: reset still clears, re-greet waits for the next open
// (the [open] effect greets when messages are empty).
s = mount();
check('sample load while closed -> reset fires', effectTick(s, 0, 1, false), true);
check('sample load while closed -> messages empty, no greet yet', s.messages, []);

// (f) A second sample load (UG then PG) resets again, not just the first.
s = mount();
effectTick(s, 0, 1, true);
s.messages = ['Masters', 'Singapore'];
check('second sample load -> reset fires again', effectTick(s, 0, 2, true), true);
check('second sample load resets exactly twice', s.resets, 2);

console.log(fail ? 'HARNESS FAILURES: ' + fail : 'HARNESS OK');
process.exit(fail ? 1 : 0);
"""


def test_r32_h3_pet_clear_on_sample_harness(tmp_path):
    """The nonce sequences from re-test 28, replayed against the real
    CompassPet reset effect + the real store bump: sample load resets
    (and re-greets when open), patch edits do not, clear-data still
    does, a closed panel resets without greeting early."""
    harness = tmp_path / "r32_h3_harness.js"
    harness.write_text(
        _NODE_HARNESS
        .replace("PET", repr(str(PET)))
        .replace("STORE", repr(str(STORE))),
        encoding="utf-8")
    node = subprocess.run(
        ["node", str(harness)],
        capture_output=True, text=True, timeout=120)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "FAIL" not in node.stdout
    assert "HARNESS OK" in node.stdout


def test_r32_h3_store_exposes_replace_nonce():
    """The new nonce is part of the store contract: declared on
    AppState, held in state, exposed in the context value and in the
    useMemo deps, so subscribers actually re-render on a bump."""
    src = STORE.read_text(encoding="utf-8")
    assert "profileReplaceNonce: number;" in src
    assert "const [profileReplaceNonce, setProfileReplaceNonce] = useState(0);" in src
    assert "dataClearNonce, profileReplaceNonce, hydrated, checklist, toggleChecklistItem, refreshChecklist" in src
    assert "[locale, profile, bannerClearNonce, dataClearNonce, profileReplaceNonce, hydrated, checklist]" in src


def test_r32_h3_pet_subscribes_to_replace_nonce():
    """CompassPet reads the new nonce from useApp and watches it in
    its own Round 32 H3 effect — a separate effect from the
    clear-data one, whose `}, [dataClearNonce]);` close is left
    byte-identical so the Round 23 W2 / Round 25 W3 / Round 30 F3
    pins that slice it keep passing."""
    src = PET.read_text(encoding="utf-8")
    assert "profile, dataClearNonce, profileReplaceNonce, updateProfile, refreshChecklist" in src
    assert "const replaceNonceRef = useRef(profileReplaceNonce);" in src
    assert "}, [profileReplaceNonce]);" in src
    assert "}, [dataClearNonce]);" in src
    # The H3 effect is a second effect, not a second dep on the clear
    # effect: the clear effect's dep list stays exactly [dataClearNonce].
    assert "}, [dataClearNonce, profileReplaceNonce]);" not in src


def test_r32_h3_wizard_step_not_reset_by_sample_load():
    """The reason for a separate nonce: the wizard's step reset
    subscribes to dataClearNonce only. If it also watched
    profileReplaceNonce, the wizard sample load's own setStep(7)
    would be overwritten with 0 by the post-commit effect."""
    wizard = WIZARD.read_text(encoding="utf-8")
    assert "profileReplaceNonce" not in wizard
    assert "setProfile({ ...s });" in wizard
    assert "setStep(7);" in wizard
    # The wizard's own clear effect still watches dataClearNonce.
    assert "}, [dataClearNonce]);" in wizard


def test_r32_h3_reset_fires_on_actual_load_not_dialog_open():
    """Round 31 G2 gating preserved: opening the confirm dialog only
    sets the pending flag; the profile (and therefore the pet reset)
    only changes on Confirm, which calls loadSample / applySample."""
    home = HOME.read_text(encoding="utf-8")
    wizard = WIZARD.read_text(encoding="utf-8")
    assert "if (hasProfileData(profile)) { setPendingSample(which); return; }" in home
    assert "onConfirm={() => { const which = pendingSample; setPendingSample(null); if (which) loadSample(which); }}" in home
    assert "if (hasProfileData(profile)) { setPendingSample(true); return; }" in wizard
    assert "onConfirm={() => { setPendingSample(false); applySample(); }}" in wizard
    # Both load paths still go through setProfile (the bump site).
    assert "setProfile(which === 'ug' ? sampleUndergrad : sampleMasters);" in home
    assert "setProfile({ ...s });" in wizard
    assert "setProfile(mergeImportedProfile(profile, p));" in wizard


def test_r32_h3_clear_data_path_unchanged():
    """clearData still bumps dataClearNonce (and only that nonce),
    still empties the profile and still wipes pp-profile — the
    Round 23 W2 / Round 29 E6 path is untouched by this fix."""
    src = STORE.read_text(encoding="utf-8")
    assert "setDataClearNonce((n) => n + 1);" in src
    assert "setProfileState(emptyProfile);" in src
    clear_body = src[src.index("const clearData = () => {"):src.index("const t = (key: string)")]
    assert "setProfileReplaceNonce" not in clear_body
    assert "localStorage.removeItem('pp-profile')" in clear_body


def test_r32_h3_no_other_subscriber_touches_replace_nonce():
    """Only CompassPet subscribes to the new nonce. PrefChat needs
    no change: its snapshot restores only on a fingerprint match
    with the current profile (lib/chat.ts parsePrefChatState), so a
    stale blob is discarded on replace by construction."""
    for path in (FE / "src").rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        if "profileReplaceNonce" in text:
            assert path in (STORE, PET), path
    assert "parsePrefChatState" in PREFCHAT.read_text(encoding="utf-8")
