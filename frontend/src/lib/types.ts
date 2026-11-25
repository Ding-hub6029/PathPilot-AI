export type Track = 'undergraduate' | 'taught_masters';
export type RuleStatus = 'MET' | 'NOT_MET' | 'UNKNOWN' | 'NOT_APPLICABLE';
// Country / curriculum branch (fix 2026-11-25): the wizard asks this
// first; only the branch's own qualification fields are shown.
export type Curriculum = 'cn_gaokao' | 'uk_alevel' | 'ib' | 'usa' | 'sg_alevel' | 'other';

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
  country: string;
  degreeLevel: Track;
  subject: string;
  intakeYear: number;
  intakeLabel: string;
  duration: string;
  feeItems: FeeItem[];
  ucasCode?: string;
  status: string;
  datasetVersion: string;
  sources: Source[];
}

export interface Profile {
  track: Track | '';
  targetProgramIds: string[];
  // Country / curriculum branch (fix 2026-11-25, wizard step 1).
  curriculum?: Curriculum;
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
}

export interface MatchResponse {
  evaluationId: string;
  results: MatchResult[];
  rulesVersion: string;
  sourceManifestHash: string;
  live: boolean;
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

export const DATA_VERSION = 'v2';
export const RULES_VERSION = 'rules-v2-2026-11-25';

export const emptyProfile: Profile = {
  track: '',
  targetProgramIds: [],
  curriculum: undefined,
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
};

export const sampleUndergrad: Profile = {
  ...emptyProfile,
  track: 'undergraduate',
  targetProgramIds: ['ucl-cs-bsc-2026'],
  curriculum: 'uk_alevel',
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
  degree: "Bachelor's in Computing (Honours)",
  graduationStatus: 'graduated',
  itExperienceYears: 2,
  intakeYear: 2027,
  ieltsOverall: 6.5,
  greTotal: 325, greAw: 4.0,
  budget: 70000, budgetCurrency: 'SGD',
  sample: true,
};
