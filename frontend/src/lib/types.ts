export type Track = 'undergraduate' | 'taught_masters';
export type RuleStatus = 'MET' | 'NOT_MET' | 'UNKNOWN' | 'NOT_APPLICABLE';
// Country / curriculum branch (fix 2026-11-25): the wizard asks this
// first; only the branch's own qualification fields are shown.
export type Curriculum = 'cn_gaokao' | 'uk_alevel' | 'ib' | 'usa' | 'sg_alevel' | 'other';
// Field / direction the applicant wants to study (wizard step 3, fix
// 2026-11-25): asked before any programme is shown; recommendations are
// filtered by it. Round 6: the expansion catalogue adds matchable
// programmes in business, engineering, science, medicine, humanities
// and arts too — see lib/fields.ts for the field -> expansion slug map.
export type FieldId = 'business' | 'computing' | 'engineering' | 'science' | 'medicine' | 'humanities' | 'arts';

export interface Source {
  id: string;
  url: string;
  label: string;
  excerpt: string;
  verifiedDate: string;
  // Optional intake applicability, e.g. "September 2026". Shown in the
  // evidence drawer when present; the programme intake label is used
  // as the fallback so the drawer never invents an intake.
  appliesTo?: string;
}

export interface FeeItem { label: string; amount: number; currency: string; period: string; }

export interface Program {
  id: string;
  institution: string;
  institutionId: string;
  officialName: string;
  /** Presentation-layer display names per locale (degree part only). Never overwrites officialName; missing locales fall back to it. */
  nameLocalized?: Record<string, string>;
  country: string;
  /** City as published (e.g. 'London', 'Singapore'). Used only for the
   * results-page city filter and preference hints — never invented. */
  city?: string;
  degreeLevel: Track | 'foundation' | 'joint_honours';
  /** Expansion field slug (e.g. 'computer-science'); v2 programmes
   * carry subject 'Computer Science' instead. */
  field?: string;
  subject: string;
  intakeYear: number;
  intakeLabel: string;
  duration: string;
  feeItems: FeeItem[];
  ucasCode?: string;
  status: string;
  datasetVersion: string;
  sources: Source[];
  /** Round 6: v2 programmes are always matchable; expansion programmes
   * converted by expansionToProgram carry their stored flag. */
  matchable?: boolean;
  /** Round 9 (R5): verified language of instruction, only where an
   * official page states it (ETH/EPFL/UZH bachelor's). Absent
   * everywhere else — the UI renders nothing for it. Carried through
   * by expansionToProgram; v2 programmes never have it. */
  languageOfInstruction?: LanguageOfInstruction | null;
}

export interface Profile {
  track: Track | '';
  targetProgramIds: string[];
  // Country / curriculum branch (fix 2026-11-25, wizard step 1).
  curriculum?: Curriculum;
  // Field / direction (fix 2026-11-25, wizard step 3): the applicant's
  // chosen direction; recommendations are filtered by it.
  field?: FieldId;
  // Gaokao (China): score out of gaokaoTotal (usually 750).
  gaokaoScore?: number | '';
  gaokaoTotal?: number | '';
  gaokaoMaths?: number | '';
  // USA: SAT total (400-1600), ACT composite (1-36), AP grades "5,5,5,4,4".
  satTotal?: number | '';
  actComposite?: number | '';
  apGrades?: string;
  alevels?: string;
  mathsGrade?: string;
  // Day 2 (FR01): IB route (alternative to A-levels for undergraduates).
  ibTotal?: number | '';
  ibHlMaths?: number | '';
  ibHlTotal?: number | '';
  // Day 2 (FR01): GCSE English + Maths (UCL requires grade C/4 or above).
  gcseEnglish?: string;
  gcseMaths?: string;
  // Day 2 (FR01): residency for fees — 'uk' = home fees, 'overseas' =
  // international fees (UK programmes); 'sg_*' = Singapore tuition bands
  // (citizen / PR / international with MOE grant, ASEAN or other /
  // international without grant). Unset means the overseas fee is assumed
  // for UK programmes; Singapore UG fees stay UNKNOWN without a band.
  residency?: 'uk' | 'overseas' | 'sg_citizen' | 'sg_pr' | 'sg_intl_asean' | 'sg_intl_other' | 'sg_intl_nogrant';
  // Day 2 (FR01): intended intake year, language test date, graduation
  // status, and IT industry experience (masters route).
  intakeYear?: number | '';
  testDate?: string;
  graduationStatus?: string;
  itExperienceYears?: number | '';
  // Day 2 (v2 programmes): degree class is a stated threshold for Imperial
  // MSc (First-Class) and UCL MSc (upper second-class); A-level Maths grade
  // is required for UCL MSc and for non-STEM Imperial MSc applicants.
  degreeClass?: 'first' | 'upper_second' | 'lower_second' | 'third' | 'other';
  mastersMathsGrade?: string;
  degree?: string;
  ieltsOverall?: number | '';
  ieltsListening?: number | '';
  ieltsReading?: number | '';
  ieltsWriting?: number | '';
  ieltsSpeaking?: number | '';
  // TOEFL iBT total, kept separate from the IELTS fields: a user may enter
  // BOTH IELTS and TOEFL; the backend must never hide or discard one.
  toefl?: number | '';
  greTotal?: number | '';
  greAw?: number | '';
  gmat?: number | '';
  budget?: number | '';
  budgetCurrency?: string;
  sample?: boolean;
  // AI preferences (wizard step 7, 2026-11-25): the user's own tastes,
  // asked so the agent can get to know them. NEVER eligibility inputs —
  // the matching engine never reads them; they only drive preference
  // hints and filters on the results page. Every one is optional.
  // Climate: 'warm' | 'cool' | 'four_seasons' | 'mild' | free text.
  prefClimate?: string;
  // Countries the user especially wants (ISO codes, chip multi-select).
  prefCountries?: string[];
  // Free-text other countries/regions not covered by the chips.
  prefCountriesNote?: string;
  // Environment: 'big_city' | 'small_city' | 'campus' | 'quiet_town' | free text.
  prefEnvironment?: string;
  // City the user has in mind (free text, e.g. 'London').
  prefCity?: string;
  // Where to build a life after graduation: 'stay' | 'return_home' |
  // 'hometown' | 'undecided' | free text.
  prefAfterGrad?: string;
  // Expected salary after graduation (amount + currency). No official
  // graduate-salary data exists to compare against — the results page
  // says so honestly and never ranks or scores by it.
  prefSalary?: number | '';
  prefSalaryCurrency?: string;
  // Academic pressure tolerance: 'low' | 'medium' | 'high' | free text.
  prefPressure?: string;
  // Preferred way to learn: 'lecture' | 'seminar' | 'hands_on' | free text.
  prefTeaching?: string;
}

export interface RuleResult {
  ruleId: string;
  status: RuleStatus;
  observed: string;
  expected: string;
  evidenceIds: string[];
  reasonCode: string;
  unknownReason?: string;
  // Structured values (fix 2026-11-25): the numbers/dicts the English
  // `observed` / `expected` strings were formatted from, so the UI can
  // render them in the current locale. `reasonKey` names the UNKNOWN
  // cause (e.g. 'gaokao-no-equivalence'); absent for other statuses.
  observedRaw?: unknown;
  thresholdRaw?: Record<string, unknown> | null;
  reasonKey?: string;
}

export interface MatchResult {
  programId: string;
  eligibilitySummary: string;
  ruleResults: RuleResult[];
  trackMismatch?: boolean;
  /** Climate preference signal (round 6): 'fit' | 'neutral' | 'conflict'.
   * Present only when the profile carries a climate preference and the
   * programme's city resolves in the climate table. Never a rule status;
   * used only to order results and show an honest note. */
  preferenceFit?: 'fit' | 'neutral' | 'conflict';
}

export interface MatchResponse {
  evaluationId: string;
  results: MatchResult[];
  rulesVersion: string;
  sourceManifestHash: string;
  live: boolean;
  /** Ids the caller asked for that could not be resolved (unknown or
   * display-only programmes). Present only when non-empty; the rest
   * of the batch still evaluates (round 9, R11). */
  skippedProgramIds?: string[];
}

// --- Rankings (Day 3, spec Ch9 FR15/FR16) ----------------------------------
// World university ranks, top 100 institutions per provider (QS 2027,
// THE 2027, ARWU 2026). rank_display is reproduced exactly as published
// ('=8' = tied at 8th); a band such as '101-150' is kept verbatim, never
// converted to a number. No combined or averaged rank across providers
// exists anywhere (BR15). ielts_reference is a compiled reference from
// user-supplied ranking-table images only — never an official programme
// requirement and never used by the eligibility engine.
export interface RankingProvider {
  id: string;
  name: string;
  short_name: string;
  edition_label: string;
  published_at: string;
  entry_url: string;
  methodology_url: string | null;
  rights_status: string;
  rights_note: string;
  attribution: string | null;
  source_data_url: string | null;
}

export interface RankingInstitution {
  id: string;
  official_name: string;
  /** Verified Chinese display name (user-supplied ranking-table images, or the institution's official site). Absent when unverified — the UI falls back to official_name. */
  name_zh?: string | null;
  country: string;
  country_name: string;
  /** Compiled IELTS reference (user-supplied table images); null outside the THE top 100. */
  ielts_reference?: string | null;
  ielts_reference_source?: string | null;
  /** Verified official website; only for the institutions whose programmes PathPilot covers. */
  official_website?: string | null;
  /** Provider profile-page links, only for providers that rank this institution. */
  provider_profiles?: { qs?: string; the?: string; arwu?: string };
}

export interface RankingEntry {
  provider: string;
  institution_id: string;
  edition_label: string;
  ranking_type: string;
  rank_display: string | null;
  rank_kind: 'single' | 'tie' | 'band' | null;
  score: number | null;
  source_url: string;
  retrieved_at: string;
  verification_status: 'verified' | 'unavailable';
  rights_status: string;
  unavailable_reason: string | null;
}

// --- Expansion programmes (Day 3 programme expansion) --------------------
// Mirror of data/expansions/expansion.json, generated by
// tools/generate_frontend_mirrors.py. Requirements are verbatim from the
// official programme pages; a missing fee/deadline stays null. Round 6:
// programmes with >=1 evaluable rule (fee / language / academic) and a
// wizard track are matchable=true and are evaluated by the generic
// evaluator (backend + offline mirror in lib/api.ts); the rest stay
// display-only.
export type ClimateClass = 'warm' | 'cool' | 'four_seasons' | 'mild';
export interface ExpansionRequirement {
  id: string;
  category: string; // 'academic' | 'language' | 'test' | 'fee' | 'other'
  description: string;
  /** Structured threshold from the official page, or null when the
   * requirement states no structured threshold. */
  threshold?: Record<string, unknown> | null;
  sourceIds: string[];
}
export interface ExpansionSource {
  id: string;
  url: string;
  title: string;
  retrievedAt: string;
}
/** Round 9 (R5): verified language of instruction for one programme.
 * Only ever set where an official page states the teaching language;
 * `language` is the English name (German / French / English), `note`
 * is the official statement in its original language, `sourceUrl`
 * is the official page it came from. Mirrored verbatim from
 * data/expansions/expansion.json by tools/generate_frontend_mirrors.py. */
export interface LanguageOfInstruction {
  language: string;
  note?: string | null;
  sourceUrl: string;
}
export interface ExpansionFee {
  amount: number | null;
  amountMin: number | null;
  amountMax: number | null;
  currency: string;
  period: string;
  residency: string | null;
  notes: string | null;
  academicYear: string | null;
  applicationFee: { amount: number; currency: string } | null;
}
export interface ExpansionProgram {
  id: string;
  institutionId: string;
  institution: string;
  country: string;
  /** City as published on the official programme page (all 881 have one). */
  city: string;
  /** Round 6: true only for UG/TM programmes with >=1 evaluable rule. */
  matchable: boolean;
  // v2 levels plus the expansion-only levels (foundation / joint_honours).
  // Kept separate from Track so the wizard / matching flow still accepts
  // only undergraduate | taught_masters.
  degreeLevel: Track | 'foundation' | 'joint_honours';
  officialName: string;
  nameLocalized?: Record<string, string>;
  field: string;
  duration: string;
  durationMonths: number | null;
  intakeYear: number;
  start: string;
  studyMode: string;
  fees: ExpansionFee;
  applicationDeadline: string | null;
  applicationStatus: string; // 'open' | 'closed' | 'unknown'
  /** Round 9 (R5): verified language of instruction, only where an
   * official page states it — never guessed. Absent for the other
   * ~886 programmes; the UI renders nothing for it. */
  languageOfInstruction?: LanguageOfInstruction | null;
  requirements: ExpansionRequirement[];
  sources: ExpansionSource[];
}

// --- Success cases (Day 3, social-source offer stories) --------------------
// Netizen-shared offer stories, NOT officially verified admission outcomes.
// Missing fields stay null; the UI renders nothing for them.
export interface CaseOffer {
  institution: string;
  programme: string | null;
  level: string; // 'undergraduate' | 'taught_masters'
  intake: string | null;
  note: string | null; // offer-specific note; null when there is none
}

export interface SuccessCase {
  id: string;
  platform: string;
  sourceUrl: string;
  sourceRef: string | null; // listing locator, e.g. "survey p. 490" (GradCafe)
  postedDate: string | null;
  authorDisplay: string | null;
  undergradInstitution: string | null;
  undergradMajor: string | null;
  gpa: string | null;
  languageScores: string | null;
  keyExperience: string | null; // experience shared for the applicant as a whole
  // One card per applicant (Round 8 dedupe): every offer this applicant
  // shared. Single-offer cards have exactly one entry.
  offers: CaseOffer[];
  label: string; // always "网友分享，未经官方核实" in the data
  collectedDate: string;
}

// --- School reviews (Day 3, netizen-shared school reviews) -------------
// Mirrored from data/expansions/school_reviews.json by
// tools/generate_frontend_mirrors.py (frontend/src/lib/reviews.ts).
// Netizen-shared impressions, NOT officially verified. Missing fields
// stay null; the UI renders nothing for them. No rating / stars exist
// in this data — the UI never shows any. `quote` is the verbatim
// English original from the source page; `quoteZh` is the collector's
// own Chinese translation, for reference only.
export interface SchoolReview {
  id: string;
  institutionId?: string | null;
  institution: string;
  programme?: string | null;
  /** 'undergraduate' | 'taught_masters' | null. */
  level?: string | null;
  authorDisplay?: string | null;
  /** Platform the review was collected from ('Shiksha', 'StudentCrowd'). */
  source?: string | null;
  sourceUrl?: string | null;
  postedDate?: string | null;
  /** Verbatim English quote from the source page. */
  quote: string;
  quoteLang?: string | null;
  /** Collector's Chinese translation of the quote, reference only. */
  quoteZh?: string | null;
  label?: string | null; // "网友分享，未经官方核实" when present
  collectedDate?: string | null;
}

export const DATA_VERSION = 'v2';
export const RULES_VERSION = 'rules-v2-2026-11-25';

export const emptyProfile: Profile = {
  track: '',
  targetProgramIds: [],
  curriculum: undefined,
  field: undefined,
  gaokaoScore: '',
  gaokaoTotal: '',
  gaokaoMaths: '',
  satTotal: '',
  actComposite: '',
  apGrades: '',
  alevels: '',
  mathsGrade: '',
  ibTotal: '',
  ibHlMaths: '',
  ibHlTotal: '',
  gcseEnglish: '',
  gcseMaths: '',
  residency: undefined,
  intakeYear: '',
  testDate: '',
  graduationStatus: '',
  itExperienceYears: '',
  degreeClass: undefined,
  mastersMathsGrade: '',
  degree: '',
  ieltsOverall: '',
  ieltsListening: '',
  ieltsReading: '',
  ieltsWriting: '',
  ieltsSpeaking: '',
  toefl: '',
  greTotal: '',
  greAw: '',
  gmat: '',
  budget: '',
  budgetCurrency: 'GBP',
  prefClimate: '',
  prefCountries: [],
  prefCountriesNote: '',
  prefEnvironment: '',
  prefCity: '',
  prefAfterGrad: '',
  prefSalary: '',
  prefSalaryCurrency: 'GBP',
  prefPressure: '',
  prefTeaching: '',
};

export const sampleUndergrad: Profile = {
  ...emptyProfile,
  track: 'undergraduate',
  targetProgramIds: ['ucl-cs-bsc-2026'],
  curriculum: 'uk_alevel',
  field: 'computing',
  alevels: 'A*A*A',
  mathsGrade: 'A*',
  gcseEnglish: 'A',
  gcseMaths: 'A*',
  residency: 'overseas',
  intakeYear: 2026,
  ieltsOverall: 7.0, ieltsListening: 6.5, ieltsReading: 6.5, ieltsWriting: 6.0, ieltsSpeaking: 6.5,
  budget: 50000, budgetCurrency: 'GBP',
  sample: true,
};

export const sampleMasters: Profile = {
  ...emptyProfile,
  track: 'taught_masters',
  targetProgramIds: ['nus-mcomp-cs'],
  field: 'computing',
  degree: "Bachelor's in Computing (Honours)",
  graduationStatus: 'graduated',
  itExperienceYears: 2,
  intakeYear: 2027,
  ieltsOverall: 6.5,
  greTotal: 325, greAw: 4.0,
  budget: 70000, budgetCurrency: 'SGD',
  sample: true,
};
