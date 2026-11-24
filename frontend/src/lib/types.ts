export type Track = 'undergraduate' | 'taught_masters';
export type RuleStatus = 'MET' | 'NOT_MET' | 'UNKNOWN' | 'NOT_APPLICABLE';

export interface Source {
  id: string;
  url: string;
  label: string;
  excerpt: string;
  verifiedDate: string;
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
  degree?: string;
  ieltsOverall?: number | '';
  ieltsListening?: number | '';
  ieltsReading?: number | '';
  ieltsWriting?: number | '';
  ieltsSpeaking?: number | '';
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

export const DATA_VERSION = 'v1';
export const RULES_VERSION = 'rules-v1-2026-11-24';

export const emptyProfile: Profile = {
  track: '',
  targetProgramIds: [],
  alevels: '',
  mathsGrade: '',
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
  ieltsOverall: 7.0, ieltsListening: 6.5, ieltsReading: 6.5, ieltsWriting: 6.0, ieltsSpeaking: 6.5,
  budget: 50000, budgetCurrency: 'GBP',
  sample: true,
};

export const sampleMasters: Profile = {
  ...emptyProfile,
  track: 'taught_masters',
  targetProgramIds: ['nus-mcomp-cs'],
  degree: "Bachelor's in Computing (Honours)",
  ieltsOverall: 6.5,
  greTotal: 325, greAw: 4.0,
  budget: 70000, budgetCurrency: 'SGD',
  sample: true,
};
