// Curated news & policy link-outs for the homepage (Day 3, 2026-11-25).
// Every item was verified on its official page or feed on 2026-11-25:
// NUS items come from the live NUS Newsroom undergraduate RSS
// (https://news.nus.edu.sg/tagfeed/en-sg/tags/undergraduate); the British
// Council, UCL and NTU items are the verified stories in
// ~/workspace/homepage_content_sources.md. Titles are the sources' own
// headlines (shown in English, like evidence excerpts); the one-line
// summaries are localised via the news.* / policy.* locale keys. Nothing
// is copied from the articles — title + link only. Dates are shown only
// where the source states one.
export interface NewsItem {
  id: string;
  title: string;
  summaryKey: string;
  source: string;
  date?: string;
  url: string;
}

export const NEWS_ITEMS: NewsItem[] = [
  {
    id: 'nus-awards',
    title: 'NUS Achievement Awards 2026 celebrates student excellence beyond the classroom',
    summaryKey: 'news.nusAwards',
    source: 'NUS Newsroom',
    date: '2026-11-11',
    url: 'https://news.nus.edu.sg/nus-achievement-awards-2026-celebrates-student-excellence-beyond-the-classroom/',
  },
  {
    id: 'nus-rag',
    title: 'NUS students celebrate tradition to uplift communities through creativity and service at NUSSU RAG & Flag Day 2025',
    summaryKey: 'news.nusRag',
    source: 'NUS Newsroom',
    date: '2025-08-08',
    url: 'https://news.nus.edu.sg/nus-students-celebrate-tradition-to-uplift-communities-through-creativity-and-service-at-nussu-rag--flag-day-2025/',
  },
  {
    id: 'nus-ctpclc',
    title: 'CTPCLC Symposium 2025: Building a sense of home and belonging through community action',
    summaryKey: 'news.nusCtpclc',
    source: 'NUS Newsroom',
    date: '2025-10-14',
    url: 'https://news.nus.edu.sg/nus-chua-thian-poh-community-leadership-centre-ctpclc-symposium-2025/',
  },
  {
    id: 'bc-liyuan',
    title: 'Liyuan Liu — Nottingham Trent University',
    summaryKey: 'news.bcLiyuan',
    source: 'British Council — Study UK',
    url: 'https://study-uk.britishcouncil.org/blog/studying-in-the-uk-helped-me-feel-at-home',
  },
  {
    id: 'bc-mariam',
    title: 'Mariam — University of Edinburgh',
    summaryKey: 'news.bcMariam',
    source: 'British Council — Study UK',
    url: 'https://study-uk.britishcouncil.org/blog/great-scholar-from-environmental-sciences-to-ethical-finance-and-meeting-uk-royalty-international-student-uk',
  },
  {
    id: 'bc-sumaiya',
    title: 'Sumaiya — Newcastle University',
    summaryKey: 'news.bcSumaiya',
    source: 'British Council — Study UK',
    url: 'https://study-uk.britishcouncil.org/blog/women-in-stem-fully-funded-masters-uk-newcastle-university-international-student-sustainable-development-environmental-engineering',
  },
  {
    id: 'bc-arjun',
    title: 'Arjun — Cranfield University',
    summaryKey: 'news.bcArjun',
    source: 'British Council — Study UK',
    url: 'https://study-uk.britishcouncil.org/blog/finding-a-uk-scholarship',
  },
  {
    id: 'ucl-london',
    title: 'Moving to London as an international student',
    summaryKey: 'news.uclLondon',
    source: 'UCL News',
    date: '2025-11',
    url: 'https://www.ucl.ac.uk/news/2025/nov/moving-london-international-student',
  },
  {
    id: 'ucl-greece',
    title: 'From Greece to London: My UCL Adventure',
    summaryKey: 'news.uclGreece',
    source: 'UCL Arts & Humanities blog',
    date: '2025-02',
    url: 'https://blogs.ucl.ac.uk/arts-hums/2025/02/',
  },
  {
    id: 'ntu-alumni',
    title: 'NTU Alumni Stories and News',
    summaryKey: 'news.ntuAlumni',
    source: 'NTU Alumni',
    url: 'https://www.ntu.edu.sg/alumni/alumni-stories-news',
  },
  {
    id: 'imperial-feeds',
    title: 'Imperial College London — News feeds',
    summaryKey: 'news.imperialFeeds',
    source: 'Imperial News',
    url: 'https://www.imperial.ac.uk/news/articles/feeds/',
  },
];

export const POLICY_ITEMS: NewsItem[] = [
  {
    id: 'policy-ucas',
    title: 'UCAS key dates — 2027 entry',
    summaryKey: 'policy.ucas',
    source: 'UCAS',
    url: 'https://www.ucas.com/applying/applying-to-university/dates-and-deadlines-for-uni-applications',
  },
  {
    id: 'policy-visa',
    title: 'UK student visas',
    summaryKey: 'policy.visa',
    source: 'GOV.UK',
    url: 'https://www.gov.uk/entering-staying-uk/student-visas',
  },
  {
    id: 'policy-pass',
    title: "Singapore Student's Pass",
    summaryKey: 'policy.pass',
    source: 'ICA Singapore',
    url: 'https://www.ica.gov.sg',
  },
];
