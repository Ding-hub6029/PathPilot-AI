import { Program, DATA_VERSION } from './types';
import { displayProgramInstitutionName } from './rankings';

// The Day-1 dataset (2 programmes) plus the 6 Day-2 programmes from
// ~/workspace/day2_courses.json (researched 2026-11-24 from official
// university pages only; verified 2026-11-25). No fees or thresholds
// invented. Source URLs are the official programme pages. Re-check the live
// pages before relying on any figure for a decision.
//
// The programme list is normally loaded from GET /api/v1/programs (see
// fetchPrograms in lib/api.ts + usePrograms in lib/usePrograms.ts); this
// list is the offline fallback for the same ids.
export const PROGRAMS: Program[] = [
  {
    id: 'ucl-cs-bsc-2026',
    institution: 'University College London',
    institutionId: 'ucl',
    officialName: 'Computer Science BSc',
    nameLocalized: {'zh-CN': '计算机科学理学学士', 'es': 'Grado en Ciencias de la Computación', 'fr': 'Licence en informatique', 'pt-BR': 'Bacharelado em Ciência da Computação', 'ar': 'بكالوريوس علوم الحاسوب'},
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
      { id: 'ucl-china-entry', url: 'https://www.ucl.ac.uk/study/international/region/east-asia/china', label: 'UCL — Information for students from China', excerpt: 'The minimum entry requirements for undergraduate courses at UCL are ABB at A-Level or 36 points for the International Baccalaureate (IB). Successful completion of one year of a Bachelor\'s Degree at a Chinese university recognised by UCL, with a weighted average mark of 90%, will also be considered as an alternative to A-Levels or the IB.', verifiedDate: '2026-11-24' },
    ],
  },
  {
    id: 'nus-mcomp-cs',
    institution: 'National University of Singapore',
    institutionId: 'nus',
    officialName: 'Master of Computing (Computer Science specialisation)',
    nameLocalized: {'zh-CN': '计算机硕士（计算机科学方向）', 'es': 'Máster en Informática (especialización en Ciencias de la Computación)', 'fr': 'Master en informatique (spécialisation en informatique)', 'pt-BR': 'Mestrado em Computação (especialização em Ciência da Computação)', 'ar': 'ماجستير في الحوسبة (تخصص علوم الحاسوب)'},
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
  {
    id: 'imperial-comp-beng-2027',
    institution: 'Imperial College London',
    institutionId: 'imperial',
    officialName: 'Computing BEng',
    nameLocalized: {'zh-CN': '计算机工程学士', 'es': 'Grado en Ingeniería Informática', 'fr': 'Licence en ingénierie informatique', 'pt-BR': 'Bacharelado em Engenharia da Computação', 'ar': 'بكالوريوس هندسة الحاسوب'},
    country: 'GB',
    degreeLevel: 'undergraduate',
    subject: 'Computer Science',
    intakeYear: 2027,
    intakeLabel: 'October 2027',
    duration: '3 years',
    feeItems: [{ label: 'Overseas tuition fee 2027', amount: 47800, currency: 'GBP', period: 'per year' }, { label: 'UK tuition fee 2027', amount: 10050, currency: 'GBP', period: 'per year' }],
    ucasCode: 'G400',
    status: 'active',
    datasetVersion: DATA_VERSION,
    sources: [
      { id: 'imperial-beng-entry', url: 'https://www.imperial.ac.uk/study/courses/undergraduate/computing-beng/', label: 'Imperial — Computing BEng (entry requirements)', excerpt: 'Our minimum entry standard is A*A*A to A*AAA overall, to include: A* in Mathematics; A*A in two further subjects or AAA in three further subjects', verifiedDate: '2026-11-25' },
      { id: 'imperial-beng-fees', url: 'https://www.imperial.ac.uk/study/courses/undergraduate/computing-beng/', label: 'Imperial — Computing BEng (fees)', excerpt: 'Home fee £10,050 per year; Overseas fee £47,800 per year', verifiedDate: '2026-11-25' },
      { id: 'imperial-beng-english', url: 'https://www.imperial.ac.uk/study/apply/english-language/', label: 'Imperial — English language requirements (Standard)', excerpt: 'IELTS – Academic: 6.5 overall (minimum 6.0 in all elements) [Standard]; TOEFL (iBT): 92 overall (minimum 20 in all elements) [Standard]; 4.5 (minimum 4.5 in all elements) [new 1-6 scale]', verifiedDate: '2026-11-25' },
      { id: 'imperial-accepted-qualifications', url: 'https://www.imperial.ac.uk/study/apply/undergraduate/process/entry-requirements/accepted-qualifications/', label: 'Imperial — Accepted qualifications (all countries)', excerpt: 'USA | Advanced Placement | Minimum of five AP tests with grades 5,5,5,4,4. Alternatively, a minimum of three AP tests with grades 5,5,4 together with an acceptable school leaving qualification (such as the US High School Diploma) and either 1460 in SAT or 31 in ACT.', verifiedDate: '2026-11-24' },
    ],
  },
  {
    id: 'imperial-msc-computing-2027',
    institution: 'Imperial College London',
    institutionId: 'imperial',
    officialName: 'Computing MSc',
    nameLocalized: {'zh-CN': '计算机理学硕士', 'es': 'Máster en Informática', 'fr': 'Master en informatique', 'pt-BR': 'Mestrado em Computação', 'ar': 'ماجستير في الحاسوب'},
    country: 'GB',
    degreeLevel: 'taught_masters',
    subject: 'Computer Science',
    intakeYear: 2027,
    intakeLabel: 'October 2027',
    duration: '1 year (1 calendar year)',
    feeItems: [{ label: 'Overseas tuition fee 2027', amount: 48300, currency: 'GBP', period: 'per year' }, { label: 'UK tuition fee 2027', amount: 25850, currency: 'GBP', period: 'per year' }],
    status: 'active',
    datasetVersion: DATA_VERSION,
    sources: [
      { id: 'imperial-msc-entry', url: 'https://www.imperial.ac.uk/study/courses/postgraduate-taught/computing/', label: 'Imperial — Computing MSc (entry requirements)', excerpt: 'First-Class degree in a subject without substantial Computing content.', verifiedDate: '2026-11-25' },
      { id: 'imperial-msc-fees', url: 'https://www.imperial.ac.uk/study/courses/postgraduate-taught/computing/', label: 'Imperial — Computing MSc (fees)', excerpt: 'Home fee £25,850; Overseas fee £48,300', verifiedDate: '2026-11-25' },
      { id: 'imperial-msc-english', url: 'https://www.imperial.ac.uk/study/apply/english-language/', label: 'Imperial — English language requirements (Higher, PG)', excerpt: 'IELTS – Academic: 7.0 overall (minimum 6.5 in all elements) [Higher]; TOEFL (iBT): 100 overall (minimum 22 in all elements) [Higher]; 5.0 (minimum 5.0 in all elements) [new 1-6 scale]', verifiedDate: '2026-11-25' },
    ],
  },
  {
    id: 'ucl-cs-msc-2027',
    institution: 'University College London',
    institutionId: 'ucl',
    officialName: 'Computer Science MSc',
    nameLocalized: {'zh-CN': '计算机科学理学硕士', 'es': 'Máster en Ciencias de la Computación', 'fr': 'Master en informatique', 'pt-BR': 'Mestrado em Ciência da Computação', 'ar': 'ماجستير علوم الحاسوب'},
    country: 'GB',
    degreeLevel: 'taught_masters',
    subject: 'Computer Science',
    intakeYear: 2027,
    intakeLabel: 'September 2027',
    duration: '1 calendar year',
    feeItems: [{ label: 'Overseas tuition fee 2027', amount: 44400, currency: 'GBP', period: 'per year' }, { label: 'UK tuition fee 2027', amount: 21500, currency: 'GBP', period: 'per year' }],
    status: 'active',
    datasetVersion: DATA_VERSION,
    sources: [
      { id: 'ucl-msc-entry', url: 'https://www.ucl.ac.uk/prospective-students/graduate/taught-degrees/computer-science-msc', label: 'UCL — Computer Science MSc (entry requirements)', excerpt: 'A minimum of an upper second-class UK Bachelor\'s degree (or international qualification of an equivalent standard) in a subject other than computer science or information technology.', verifiedDate: '2026-11-25' },
      { id: 'ucl-msc-fees', url: 'https://www.ucl.ac.uk/prospective-students/graduate/taught-degrees/computer-science-msc', label: 'UCL — Computer Science MSc (fees)', excerpt: 'UK students: £21,500 per year; International: £44,400 per year', verifiedDate: '2026-11-25' },
      { id: 'ucl-msc-english', url: 'https://www.ucl.ac.uk/study/prospective-students/graduate/how-apply/english-language-requirements', label: 'UCL — Graduate English language requirements', excerpt: 'The course page fetched does not state which UCL English language level applies to this programme (no \'Level 2\' or other level text found on the page).', verifiedDate: '2026-11-25' },
    ],
  },
  {
    id: 'nus-bcomp-cs-2027',
    institution: 'National University of Singapore',
    institutionId: 'nus',
    officialName: 'Bachelor of Computing (Computer Science)',
    nameLocalized: {'zh-CN': '计算机学士（计算机科学）', 'es': 'Grado en Informática (Ciencias de la Computación)', 'fr': 'Licence en informatique (sciences informatiques)', 'pt-BR': 'Bacharelado em Computação (Ciência da Computação)', 'ar': 'بكالوريوس في الحوسبة (علوم الحاسوب)'},
    country: 'SG',
    degreeLevel: 'undergraduate',
    subject: 'Computer Science',
    intakeYear: 2027,
    intakeLabel: 'August 2027, AY2027/2028 Semester 1',
    duration: '4 years (Bachelor\'s with Honours, 160 units)',
    feeItems: [{ label: 'Tuition fee (Singapore Citizen, AY2026/27)', amount: 8300, currency: 'SGD', period: 'per year' }, { label: 'Tuition fee (international, with grant, other)', amount: 21400, currency: 'SGD', period: 'per year' }],
    status: 'active',
    datasetVersion: DATA_VERSION,
    sources: [
      { id: 'nus-bcomp-entry', url: 'https://www.comp.nus.edu.sg/programmes/ug/cs/', label: 'NUS — Bachelor of Computing (CS)', excerpt: 'Common Computer Science Programmes AAA/A AAA/A (10th and 90th percentile, AY2025/2026)', verifiedDate: '2026-11-25' },
      { id: 'nus-bcomp-fees', url: 'https://www.nus.edu.sg/registrar/docs/info/administrative-policies-procedures/ugtuitioncurrent.pdf?shortlink=c3555dc2&', label: 'NUS — Undergraduate tuition fees (AY2026/27)', excerpt: 'Computing 8,300 11,600 18,050 21,400 39,700', verifiedDate: '2026-11-25' },
      { id: 'nus-bcomp-english', url: 'https://www.nus.edu.sg/oam/docs/default-source/international-qualifications/english-test-scores.pdf', label: 'NUS — English language requirements', excerpt: 'IELTS 6.5 overall with 6.5 in Reading and Writing components; TOEFL 92-93', verifiedDate: '2026-11-25' },
    ],
  },
  {
    id: 'ntu-bcomp-cs-2027',
    institution: 'Nanyang Technological University',
    institutionId: 'ntu',
    officialName: 'Bachelor of Computing (Hons) in Computer Science',
    nameLocalized: {'zh-CN': '计算机学士（荣誉，计算机科学）', 'es': 'Grado con Honores en Informática (Ciencias de la Computación)', 'fr': 'Licence avec mention en informatique (sciences informatiques)', 'pt-BR': 'Bacharelado com Honras em Computação (Ciência da Computação)', 'ar': 'بكالوريوس مع مرتبة الشرف في الحوسبة (علوم الحاسوب)'},
    country: 'SG',
    degreeLevel: 'undergraduate',
    subject: 'Computer Science',
    intakeYear: 2027,
    intakeLabel: 'AY2027/28',
    duration: '4 years, direct honours',
    feeItems: [{ label: 'Tuition fee (Singapore Citizen, AY2026/27)', amount: 8300, currency: 'SGD', period: 'per year' }, { label: 'Tuition fee (international, with grant, other)', amount: 21400, currency: 'SGD', period: 'per year' }],
    status: 'active',
    datasetVersion: DATA_VERSION,
    sources: [
      { id: 'ntu-bcomp-entry', url: 'https://www.ntu.edu.sg/computing/admissions/undergraduate-programmes/detail/bachelor-of-computing-in-computer-science', label: 'NTU — Bachelor of Computing (CS)', excerpt: 'Computer Science AAB/C AAA/A (10th and 90th percentile); Computer Science 3.78 3.98 (polytechnic GPA, 10th and 90th percentile); Computer Science 487 places taken up in AY2025-26', verifiedDate: '2026-11-25' },
      { id: 'ntu-bcomp-fees', url: 'https://www.ntu.edu.sg/admissions/undergraduate/fees-and-funding/tuition-fees', label: 'NTU — Undergraduate tuition fees (AY2026/27)', excerpt: 'All Programmes (except for those listed below) $ 8,300 $ 11,600 $ 18,050 $ 21,400 $ 40,600 $ 36,350 (AY2026/2027: SC / SPR / ASEAN IS / all other IS subsidised / non-subsidised lab-based / non-subsidised non-lab-based)', verifiedDate: '2026-11-25' },
      { id: 'ntu-bcomp-english', url: 'https://www.ntu.edu.sg/admissions/undergraduate/admissions/general-admission-requirements/international-qualifications/other-international-qualifications', label: 'NTU — English language requirements', excerpt: 'IELTS Academic; IELTS UKAI Academic: Overall score - 6.5, Writing - 6.5, Speaking - 6.5; TOEFL / TOEFL iBT Home Edition: Total Score - 90 or 4.5, Writing - 25 or 4.5, Verbal/Speaking - 25 or 4.5', verifiedDate: '2026-11-25' },
    ],
  },
  {
    id: 'ntu-msai-2027',
    institution: 'Nanyang Technological University',
    institutionId: 'ntu',
    officialName: 'Master of Science in Artificial Intelligence (MSAI)',
    nameLocalized: {'zh-CN': '人工智能理学硕士', 'es': 'Máster en Ciencias de la Inteligencia Artificial', 'fr': 'Master en sciences de l’intelligence artificielle', 'pt-BR': 'Mestrado em Ciências da Inteligência Artificial', 'ar': 'ماجستير العلوم في الذكاء الاصطناعي'},
    country: 'SG',
    degreeLevel: 'taught_masters',
    subject: 'Computer Science',
    intakeYear: 2027,
    intakeLabel: 'AY2027/28',
    duration: '1 year full-time (2 years part-time); 30 Academic Units; minimum/maximum candidature full-time 12/30 months',
    feeItems: [{ label: 'Total tuition incl. 9% GST', amount: 65748.8, currency: 'SGD', period: 'total' }],
    status: 'active',
    datasetVersion: DATA_VERSION,
    sources: [
      { id: 'ntu-msai-entry', url: 'https://www.ntu.edu.sg/engineering/coe-programmes/graduate/coe-programme-detail/master-of-science-in-artificial-intelligence', label: 'NTU — MSc in Artificial Intelligence (admissions)', excerpt: 'A) A good honours degree in computer science, computer engineering or a related discipline with solid mathematical training or B) A good bachelor\'s degree in computer science, computer engineering or a related discipline', verifiedDate: '2026-11-25' },
      { id: 'ntu-msai-fees', url: 'https://www.ntu.edu.sg/engineering/coe-programmes/graduate/coe-programme-detail/master-of-science-in-artificial-intelligence', label: 'NTU — MSc in Artificial Intelligence (fees)', excerpt: 'Tuition Fees S$65,748.80; All fees shown are inclusive of 9% prevailing GST; Deposit Fees S$5,000; There is an application fee of S$50.', verifiedDate: '2026-11-25' },
      { id: 'ntu-msai-english', url: 'https://www.ntu.edu.sg/engineering/coe-programmes/graduate/coe-programme-detail/master-of-science-in-artificial-intelligence', label: 'NTU — MSc in Artificial Intelligence (English)', excerpt: 'English language proficiency – TOEFL (iBT ≥ 100/ ≥5.0) / IELTS (≥ 6.5) OR certification of English as medium of instruction (MOI).', verifiedDate: '2026-11-25' },
    ],
  },
];

/**
 * Localised programme display names (presentation layer only).
 * The degree part comes from Program.nameLocalized; the institution part
 * reuses displayProgramInstitutionName() from lib/rankings.ts so the
 * institution follows the same locale rule (zh-CN shows name_zh, other
 * locales show the English official name). officialName is never
 * overwritten; a locale without a nameLocalized entry falls back to it.
 */

export function displayProgramName(program: Program, locale: string): string {
  return program.nameLocalized?.[locale] ?? program.officialName;
}

export function displayProgramTitle(program: Program, locale: string): string {
  return `${displayProgramInstitutionName(program.institution, locale)} — ${displayProgramName(program, locale)}`;
}
