import { Program, DATA_VERSION } from './types';

// The only two programmes in the Day-1 dataset. Facts as supplied in the
// task brief; no fees or thresholds invented. Source URLs are the official
// programme pages. Verified date = date this dataset was compiled
// (2026-11-24); re-check the live pages before relying on it for a decision.
export const PROGRAMS: Program[] = [
  {
    id: 'ucl-cs-bsc-2026',
    institution: 'University College London',
    institutionId: 'ucl',
    officialName: 'Computer Science BSc',
    country: 'GB',
    degreeLevel: 'undergraduate',
    subject: 'Computer Science',
    intakeYear: 2026,
    intakeLabel: 'September 2026',
    duration: '3 years full-time',
    feeItems: [{ label: 'Overseas tuition fee 2026/27', amount: 46700, currency: 'GBP', period: 'per year' }],
    ucasCode: 'G400',
    status: 'active',
    datasetVersion: DATA_VERSION,
    sources: [
      { id: 'ucl-cs-entry', url: 'https://www.ucl.ac.uk/prospective-students/undergraduate/degrees/computer-science-bsc-2026', label: 'UCL — Computer Science BSc (entry requirements)', excerpt: 'Grades A*A*A. A* in either Mathematics or Further Mathematics required. GCSEs: English Language and Mathematics at grade C or 4.', verifiedDate: '2026-11-24' },
      { id: 'ucl-cs-fees', url: 'https://www.ucl.ac.uk/prospective-students/undergraduate/degrees/computer-science-bsc-2026', label: 'UCL — Computer Science BSc (fees)', excerpt: 'Overseas tuition fees (2026/27): £46,700. UK tuition fees (2026/27): £9,790. Duration: 3 academic years. Programme starts September 2026.', verifiedDate: '2026-11-24' },
      { id: 'ucl-cs-english', url: 'https://www.ucl.ac.uk/prospective-students/study-abroad-at-ucl/how-apply/english-language-requirements/', label: 'UCL — English language requirements (Level 1)', excerpt: 'Level 1: IELTS Academic overall score of 6.5 and a minimum of 6.0 in each component. The English language level for this programme is Level 1.', verifiedDate: '2026-11-24' },
      { id: 'ucas-g400', url: 'https://www.ucl.ac.uk/prospective-students/undergraduate/degrees/computer-science-bsc-2026', label: 'UCL — Computer Science BSc (UCAS code)', excerpt: 'UCAS course code G400. Application deadline 14 Jan 2026.', verifiedDate: '2026-11-24' },
    ],
  },
  {
    id: 'nus-mcomp-cs',
    institution: 'National University of Singapore',
    institutionId: 'nus',
    officialName: 'Master of Computing (Computer Science specialisation)',
    country: 'SG',
    degreeLevel: 'taught_masters',
    subject: 'Computer Science',
    intakeYear: 2027,
    intakeLabel: 'August 2027 (AY2027/2028)',
    duration: 'Up to 40 units',
    feeItems: [{ label: 'Total tuition incl. 9% GST (up to 40 units)', amount: 69215, currency: 'SGD', period: 'total' }],
    status: 'active',
    datasetVersion: DATA_VERSION,
    sources: [
      { id: 'nus-mcomp-admissions', url: 'https://www.comp.nus.edu.sg/programmes/pg/misc/admissions/', label: 'NUS School of Computing — MComp admissions', excerpt: 'A good honours degree in computing; or a good honours degree in a related discipline with 2 years IT industry experience. Minimum TOEFL iBT 90; minimum IELTS 6.0.', verifiedDate: '2026-11-24' },
      { id: 'nus-mcomp-gre', url: 'https://www.comp.nus.edu.sg/programmes/pg/misc/admissions/', label: 'NUS School of Computing — MComp admissions (GRE/GMAT)', excerpt: 'Minimum GRE score of 320 (verbal & quantitative) and 3.5 (analytical), or a GMAT score of 650 and above.', verifiedDate: '2026-11-24' },
      { id: 'nus-mcomp-fees', url: 'https://www.comp.nus.edu.sg/programmes/pg/mcs/scholarships/', label: 'NUS School of Computing — MComp (fees)', excerpt: 'The Master of Computing (with Specialisations) tuition fees for new students: S$69,215 (including prevailing GST 9%). The above stated tuition fees allow students to enroll up to 40 Units. Semester 1, AY2027/2028 (August 2027 Intake) onwards.', verifiedDate: '2026-11-24' },
    ],
  },
];
