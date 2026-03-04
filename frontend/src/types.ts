export interface ChangeItem {
  id: number;
  section: string;
  title: string;
  category: 'NEW' | 'MODIFIED' | 'REMOVED' | 'STRUCTURAL';
  description: string;
  old_text?: string | null;
  new_text?: string | null;
  impact: string;
  impact_level: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
  manifest_item?: string | null;
  verification_status?: string | null;
  verification_conclusion?: string | null;
  verification_keywords?: string[];
  old_page?: number | null;
  new_page?: number | null;
}

export interface AnalysisResult {
  job_id: string;
  status: 'completed' | 'failed' | 'processing';
  created_at: string;
  old_label: string;
  new_label: string;
  total_changes: number;
  by_category: Record<string, number>;
  by_impact: Record<string, number>;
  changes: ChangeItem[];
  old_pages?: number;
  new_pages?: number;
  manifest?: {
    detected: boolean;
    source?: string;
    revised?: string[];
    added?: string[];
    deleted?: string[];
  } | null;
}

export interface ProgressEvent {
  stage: string;
  percent: number;
  message: string;
  turn?: number;
  max_turns?: number;
  tokens?: number;
  elapsed?: number;
  timestamp?: string;
  changes_found?: number;
  candidates_found?: number;
}
