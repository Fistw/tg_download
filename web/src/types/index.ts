export interface DownloadItem {
  filename: string;
  file_size_bytes: number;
  speed_kb_s: number;
  status: 'downloading' | 'completed' | 'failed';
  created_at: string;
}

export interface UploadItem {
  filename: string;
  file_size_bytes: number;
  speed_kb_s: number;
  status: 'uploading' | 'completed' | 'failed';
  created_at: string;
}

export interface DownloadStats {
  total: number;
  active: number;
  completed: number;
  avg_speed_kb_s: number;
}

export interface UploadStats {
  total: number;
  active: number;
  completed: number;
  avg_speed_kb_s: number;
}

export interface SystemStats {
  memory_percent: number;
  cpu_percent: number;
}

export interface HealthCheck {
  total_checks_24h: number;
  failed_checks_24h: number;
  last_success: string | null;
}

export interface RecoveryItem {
  action_taken: string;
  reason: string;
  created_at: string;
}

export interface DashboardStats {
  downloads: DownloadStats;
  uploads: UploadStats;
  system: SystemStats;
  health_check: HealthCheck;
}

// 去重相关类型
export interface ChatInfo {
  id: number;
  title: string;
  type: string;
}

export interface DedupeTask {
  id: number;
  chat_id: number;
  chat_title: string;
  status: 'pending' | 'scanning' | 'paused' | 'completed' | 'failed';
  start_message_id: number | null;
  last_scanned_message_id: number | null;
  total_messages: number | null;
  processed_messages: number;
  unique_media: number;
  duplicate_count: number;
  progress: number;
  created_at: string;
  updated_at: string;
}

export interface DedupeMedia {
  id: number;
  file_id: string;
  file_size: number;
  duration: number | null;
  width: number | null;
  height: number | null;
  occurrence_count: number;
  first_seen_message_id: number;
  first_seen_date: string;
  is_original: boolean;
  downloaded: boolean;
  has_thumbnail: boolean;
}

export interface DedupeMediaListResponse {
  items: DedupeMedia[];
  pagination: {
    page: number;
    limit: number;
    total: number;
    total_pages: number;
  };
}

export interface CreateDedupeTaskRequest {
  chat_id: number;
  chat_title?: string;
  start_message_id?: number;
  total_messages?: number;
}

export interface DownloadMediaRequest {
  file_id?: string;
  download_all?: boolean;
  output_dir?: string;
}

// 两层去重相关类型
export interface DedupeLevel1Group {
  group_id: string;
  primary_media_id: number;
  primary_file_id: string;
  media_ids: number[];
  media_list: DedupeMedia[];
}

export interface DedupeLevel2Group {
  group_id: string;
  primary_level1_group_id: string;
  level1_group_ids: string[];
  level1_groups: DedupeLevel1Group[];
  similarity_score?: number;
  hamming_distance?: number;
}

export interface TwoLevelDedupeSummary {
  task_id: number;
  level1_groups: DedupeLevel1Group[];
  level1_count: number;
  level2_groups: DedupeLevel2Group[];
  level2_count: number;
}

export interface RunTwoLevelDedupeRequest {
  similarity_threshold?: number;
}

export interface RunLevel1DedupeResponse {
  success: boolean;
  message: string;
  level1_count: number;
}

export interface RunLevel2DedupeResponse {
  success: boolean;
  message: string;
  level2_count: number;
}

export interface RunTwoLevelDedupeResponse {
  success: boolean;
  message: string;
  summary: TwoLevelDedupeSummary;
}
