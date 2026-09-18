export interface ContactInfo {
  name?: string | null;
  email?: string | null;
  phone?: string | null;
  location?: string | null;
  linkedin?: string | null;
  github?: string | null;
  website?: string | null;
}

export interface ExperienceEntry {
  title: string;
  company: string;
  location?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  bullets: string[];
}

export interface EducationEntry {
  degree: string;
  institution: string;
  start_date?: string | null;
  end_date?: string | null;
  details: string[];
}

export interface ProjectEntry {
  name: string;
  description: string;
  technologies: string[];
}

export interface ResumeProfile {
  contact: ContactInfo;
  summary: string;
  hard_skills: string[];
  soft_skills: string[];
  experience: ExperienceEntry[];
  education: EducationEntry[];
  projects: ProjectEntry[];
  certifications: unknown[];
  languages: string[];
  years_experience?: number | null;
  target_titles: string[];
}

export interface JobListing {
  external_id: string;
  source: string;
  title: string;
  company: string;
  location: string;
  description: string;
  url: string;
  salary?: string | null;
  employment_type?: string | null;
  posted_at?: string | null;
}

export interface JobImprovementAction {
  area: string;
  advice: string;
  original: string;
  rewritten: string;
  priority: string;
}

export interface JobImprovement {
  summary: string;
  actions: JobImprovementAction[];
}

export interface MatchScore {
  job_key: string;
  fit_score: number;
  lexical_score: number;
  llm_score?: number | null;
  matched_skills: string[];
  missing_skills: string[];
  overqualified?: boolean;
  reasoning: string;
  improvement?: JobImprovement | null;
}

export interface JobMatch {
  listing: JobListing;
  score: MatchScore;
  rank?: number | null;
}

export interface RewriteSuggestion {
  section: string;
  original: string;
  rewritten: string;
  rationale: string;
  priority: string;
}

export interface SectionReview {
  section: string;
  strengths: string[];
  issues: string[];
  suggestions: RewriteSuggestion[];
}

export interface MissingKeyword {
  keyword: string;
  appears_in_targets: number;
  importance: string;
}

export interface PriorityAction {
  priority: string;
  action: string;
}

export interface ResumeImprovementReport {
  overall_ats_score?: number;
  summary: string;
  sections: SectionReview[];
  missing_keywords: MissingKeyword[];
  priority_actions: PriorityAction[];
  target_titles: string[];
}

export interface UsageRecord {
  model?: string;
  kind?: string;
  input_tokens?: number;
  output_tokens?: number;
}

export interface TranscriptMessage {
  role: string;
  content?: string;
  final?: boolean;
  name?: string;
}

export interface MatchResult {
  profile?: ResumeProfile | null;
  jobs_retrieved?: number;
  matches: JobMatch[];
  improvement?: ResumeImprovementReport | null;
  warnings: string[];
  usage?: UsageRecord[];
  total_cost_usd?: number;
  agent_transcript?: TranscriptMessage[];
}

export interface ResumeAnalysis {
  profile: ResumeProfile;
  warnings: string[];
  usage?: UsageRecord[];
}

export interface SearchResult {
  jobs_retrieved: number;
  listings: JobListing[];
  warnings: string[];
}

export interface UploadResult {
  upload_id: string;
  filename: string;
  extension: string;
  text: string;
}

export interface PdfWordBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  oy: number;
  text: string;
  size: number;
  font: string;
}

export interface PdfPageBoxes {
  page: number;
  width: number;
  height: number;
  words: PdfWordBox[];
}

export interface PdfPositionsResult {
  upload_id: string;
  extension: string;
  editable: boolean;
  pages: PdfPageBoxes[];
}

export interface HealthStatus {
  status: string;
  provider?: string;
  model?: string;
  sources?: string[];
  cost_limit_usd?: number | null;
}

export interface MatchRequest {
  resume_text: string;
  query: string;
  location: string;
  remote_only: boolean;
  limit: number;
  llm_top_n: number;
  min_score: number;
  improve: boolean;
}