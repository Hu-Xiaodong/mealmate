import { API_BASE } from "../config";
import type {
  AIChatPayload,
  AIChatResult,
  CreatePostPayload,
  FavoritePage,
  FeedPage,
  LoginResult,
  MyPostPage,
  PostDetail,
  PublishResult,
  RankPage,
  Recipe,
  RecipeCategory,
  RecipePage,
  TargetType,
} from "./types";

const TOKEN_KEY = "mealmate_token";
const DEVICE_KEY = "mealmate_device_id";

export class ApiError extends Error {
  code: string;
  status: number;
  data: unknown;

  constructor(code: string, message: string, status: number, data: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.data = data;
  }
}

interface Envelope<T> {
  requestId: string;
  code: number;
  message: string;
  data: T;
}

export function token(): string {
  return (uni.getStorageSync(TOKEN_KEY) as string) || "";
}

export function setToken(value: string): void {
  if (value) uni.setStorageSync(TOKEN_KEY, value);
  else uni.removeStorageSync(TOKEN_KEY);
}

export function deviceId(): string {
  let value = (uni.getStorageSync(DEVICE_KEY) as string) || "";
  if (!value) {
    value = `dev-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    uni.setStorageSync(DEVICE_KEY, value);
  }
  return value;
}

function rawRequest(options: UniApp.RequestOptions): Promise<UniApp.RequestSuccessCallbackResult> {
  return new Promise((resolve, reject) => {
    uni.request({
      ...options,
      success: resolve,
      fail: (error) => reject(new Error(error.errMsg || "网络连接失败")),
    });
  });
}

async function request<T>(
  path: string,
  options: {
    method?: "GET" | "POST" | "PUT";
    data?: unknown;
    auth?: boolean;
    headers?: Record<string, string>;
  } = {},
): Promise<T> {
  const header: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  const current = token();
  if (options.auth !== false && current) header.Authorization = `Bearer ${current}`;
  if (!current) header["X-Device-Id"] = deviceId();

  const response = await rawRequest({
    url: `${API_BASE}${path}`,
    method: options.method || "GET",
    data: options.data,
    header,
    timeout: 15000,
  });

  let body = response.data as Envelope<T> | string;
  if (typeof body === "string") {
    try {
      body = JSON.parse(body) as Envelope<T>;
    } catch {
      throw new ApiError("BAD_RESPONSE", "服务返回了无法解析的内容", response.statusCode);
    }
  }
  if (response.statusCode >= 400 || body.code !== 0) {
    throw new ApiError(body.code ?? response.statusCode, body.message || "请求失败", response.statusCode, body.data);
  }
  return body.data;
}

function query(params: Record<string, string | number | undefined | null>): string {
  const parts = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

export const api = {
  sendSmsCode(phone: string) {
    return request<{ challengeId: string; expiresIn: number; retryAfter: number; devCode?: string }>(
      "/api/v1/auth/sms-codes",
      { method: "POST", data: { phone, purpose: "login" }, auth: false },
    );
  },

  login(payload: { challengeId: string; code: string; agreementAccepted: boolean; deviceRef?: string }) {
    return request<LoginResult>("/api/v1/auth/login", {
      method: "POST",
      data: payload,
      auth: false,
    });
  },

  logout() {
    return request<{ revoked: boolean }>("/api/v1/auth/logout", { method: "POST" });
  },

  feed(params: {
    filter: "all" | "near";
    cursor?: string | null;
    limit?: number;
    lat?: number;
    lng?: number;
    radius?: number;
  }) {
    return request<FeedPage>(`/api/v1/feed${query(params)}`);
  },

  rank() {
    return request<RankPage>("/api/v1/rank/today");
  },

  recipes(params: { category: RecipeCategory; cursor?: string | null; limit?: number }) {
    return request<RecipePage>(`/api/v1/recipes${query(params)}`);
  },

  recipe(id: string) {
    return request<Recipe>(`/api/v1/recipes/${encodeURIComponent(id)}`);
  },

  post(id: string) {
    return request<PostDetail>(`/api/v1/posts/${encodeURIComponent(id)}`);
  },

  setLike(postId: string, liked: boolean) {
    return request<{ postId: string; liked: boolean; likeCount: number }>(
      `/api/v1/posts/${encodeURIComponent(postId)}/like`,
      { method: "PUT", data: { liked } },
    );
  },

  setFavorite(targetType: TargetType, targetId: string, saved: boolean) {
    return request<{ saved: boolean; savedAt: string | null }>("/api/v1/favorites", {
      method: "PUT",
      data: { targetType, targetId, saved },
    });
  },

  myPosts(cursor?: string | null, limit = 20) {
    return request<MyPostPage>(`/api/v1/me/posts${query({ cursor, limit })}`);
  },

  myFavorites(cursor?: string | null, limit = 20) {
    return request<FavoritePage>(`/api/v1/me/favorites${query({ cursor, limit })}`);
  },

  createPost(payload: CreatePostPayload, idempotencyKey: string) {
    return request<PublishResult>("/api/v1/posts", {
      method: "POST",
      data: payload,
      auth: true,
      headers: { "Idempotency-Key": idempotencyKey },
    });
  },

  aiChat(payload: AIChatPayload) {
    return request<AIChatResult>("/api/v1/ai/chat", { method: "POST", data: payload });
  },
};

export function uploadImage(filePath: string): Promise<{ assetId: string; url: string }> {
  return new Promise((resolve, reject) => {
    const current = token();
    if (!current) {
      reject(new ApiError("UNAUTHENTICATED", "请先登录后再上传图片", 401));
      return;
    }
    uni.uploadFile({
      url: `${API_BASE}/api/v1/media`,
      filePath,
      name: "file",
      header: { Authorization: `Bearer ${current}` },
      success: (result) => {
        try {
          const body = JSON.parse(result.data) as Envelope<{ assetId: string; url: string }>;
          if (result.statusCode >= 400 || body.code !== 0) {
            reject(new ApiError(body.code, body.message || "上传失败", result.statusCode, body.data));
            return;
          }
          resolve(body.data);
        } catch {
          reject(new ApiError("BAD_RESPONSE", "上传结果无法解析", result.statusCode));
        }
      },
      fail: () => reject(new ApiError("NETWORK_ERROR", "图片上传失败，请检查网络", 0)),
    });
  });
}
