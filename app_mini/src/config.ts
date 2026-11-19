/** 接口地址。H5 本地开发直连 8000；小程序发布前改成已备案的 HTTPS 域名。 */
export const API_BASE = (import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000").replace(
  /\/+$/,
  "",
);

/** 后端返回的 /media/xxx 需要补全域名，外链图片原样返回。 */
export function resolveMedia(path?: string | null): string {
  if (!path) return "";
  if (path.startsWith("http://") || path.startsWith("https://") || path.startsWith("data:")) {
    return path;
  }
  return `${API_BASE}${path.startsWith("/") ? "" : "/"}${path}`;
}
