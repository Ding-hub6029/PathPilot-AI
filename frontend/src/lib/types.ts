export type Track = 'undergraduate' | 'taught_masters';
export type RuleStatus = 'MET' | 'NOT_MET' | 'UNKNOWN' | 'NOT_APPLICABLE';

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

export const DATA_VERSION = 'v2';
export const RULES_VERSION = 'rules-v2-2026-11-25';

export const emptyProfile: Profile = {
  track: '',
  targetProgramIds: [],
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
