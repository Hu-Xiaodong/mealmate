import { ApiError } from "../api/client";

export const SOURCE_LABEL: Record<string, string> = {
  self: "自己做",
  takeaway: "外卖",
  dine_in: "到店",
};

export const TOOL_LABEL: Record<string, string> = {
  wok: "炒锅",
  pot: "炖锅",
  microwave: "微波炉",
  rice_cooker: "电饭煲",
  steamer: "蒸锅",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABEL[source] || "其他";
}

export function toolLabels(codes: string[]): string[] {
  return codes.map((code) => TOOL_LABEL[code] || code);
}

export function timeLabel(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return `${hour}:${minute}`;
}

export function distanceLabel(meters?: number | null): string {
  if (meters === undefined || meters === null) return "";
  if (meters <= 30) return "就在附近";
  if (meters < 1000) return `${meters} 米`;
  return `${(meters / 1000).toFixed(1)} 公里`;
}

export function dateLabel(date: string): string {
  const [, month, day] = date.split("-");
  if (!month || !day) return "";
  return `${Number(month)}月${Number(day)}日`;
}

/** 带日期的时间，用于展示草稿的最后更新时间。 */
export function dateTimeLabel(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const month = date.getMonth() + 1;
  const day = date.getDate();
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return `${month}月${day}日 ${hour}:${minute}`;
}

export function showError(error: unknown, fallback = "操作失败，请稍后再试"): void {
  const message =
    error instanceof ApiError
      ? error.message
      : error instanceof Error && error.message
        ? error.message
        : fallback;
  uni.showToast({ title: message, icon: "none", duration: 2400 });
}
