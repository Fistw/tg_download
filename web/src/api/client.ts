import axios from 'axios';
import type {
  DashboardStats,
  DownloadItem,
  UploadItem,
  RecoveryItem,
  ChatInfo,
  DedupeTask,
  DedupeMediaListResponse,
  CreateDedupeTaskRequest,
  DownloadMediaRequest,
} from '../types';

const api = axios.create({
  baseURL: '/api',
  withCredentials: true, // 允许携带 Cookie
});

// 添加响应拦截器，处理 401
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // 如果是 401，清除本地状态
      localStorage.removeItem('isAuthenticated');
      // 触发登录状态变化
      window.dispatchEvent(new CustomEvent('authRequired'));
    }
    console.error('API Error:', error);
    return Promise.reject(error);
  }
);

export const apiClient = {
  // 认证相关
  async login(username: string, password: string): Promise<{ success: boolean; message: string }> {
    const response = await api.post('/login', { username, password });
    if (response.data.success) {
      localStorage.setItem('isAuthenticated', 'true');
    }
    return response.data;
  },

  async logout(): Promise<void> {
    await api.post('/logout');
    localStorage.removeItem('isAuthenticated');
  },

  isAuthenticated(): boolean {
    return localStorage.getItem('isAuthenticated') === 'true';
  },

  // 仪表板相关
  async getDashboardStats(): Promise<DashboardStats> {
    const response = await api.get('/dashboard/stats');
    return response.data;
  },

  async getDownloads(): Promise<DownloadItem[]> {
    const response = await api.get('/downloads');
    return response.data;
  },

  async getUploads(): Promise<UploadItem[]> {
    const response = await api.get('/uploads');
    return response.data;
  },

  async getRecoveries(): Promise<RecoveryItem[]> {
    const response = await api.get('/health/recoveries');
    return response.data;
  },

  // 去重相关 API
  async getChats(): Promise<ChatInfo[]> {
    const response = await api.get('/dedupe/chats');
    return response.data;
  },

  async getDedupeTasks(): Promise<DedupeTask[]> {
    const response = await api.get('/dedupe/tasks');
    return response.data;
  },

  async createDedupeTask(data: CreateDedupeTaskRequest): Promise<DedupeTask> {
    const response = await api.post('/dedupe/tasks', data);
    return response.data;
  },

  async getDedupeTask(taskId: number): Promise<DedupeTask> {
    const response = await api.get(`/dedupe/tasks/${taskId}`);
    return response.data;
  },

  async startDedupeTask(taskId: number): Promise<void> {
    await api.post(`/dedupe/tasks/${taskId}/start`);
  },

  async pauseDedupeTask(taskId: number): Promise<void> {
    await api.post(`/dedupe/tasks/${taskId}/pause`);
  },

  async resumeDedupeTask(taskId: number): Promise<void> {
    await api.post(`/dedupe/tasks/${taskId}/resume`);
  },

  async getDedupeMedia(
    taskId: number,
    params?: {
      page?: number;
      limit?: number;
      search?: string;
      filter_type?: string;
      min_duration?: number;
      max_duration?: number;
    }
  ): Promise<DedupeMediaListResponse> {
    const response = await api.get(`/dedupe/tasks/${taskId}/media`, { params });
    return response.data;
  },

  async downloadMedia(taskId: number, data: DownloadMediaRequest): Promise<{ downloaded_count: number }> {
    const response = await api.post(`/dedupe/tasks/${taskId}/download`, data);
    return response.data;
  },

  async deleteDedupeTask(taskId: number): Promise<void> {
    await api.delete(`/dedupe/tasks/${taskId}`);
  },

  async restartDedupeTask(taskId: number): Promise<void> {
    await api.post(`/dedupe/tasks/${taskId}/restart`);
  },
};
