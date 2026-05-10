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
