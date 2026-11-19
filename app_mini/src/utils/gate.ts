import { useSessionStore } from "../stores/session";

type PendingAction = () => void | Promise<void>;

let pending: PendingAction | null = null;

/**
 * 登录拦截：未登录时跳转登录页并记住原操作，登录成功后继续执行。
 * 返回 true 表示已登录且操作可以立即执行。
 */
export function requireLogin(action?: PendingAction): boolean {
  const session = useSessionStore();
  if (session.isLoggedIn) {
    if (action) void action();
    return true;
  }
  pending = action || null;
  uni.navigateTo({ url: "/pages/login/login" });
  return false;
}

export async function resumePending(): Promise<void> {
  const action = pending;
  pending = null;
  if (!action) return;
  try {
    await action();
  } catch {
    // 续做失败由具体页面提示，这里只保证不阻断返回。
  }
}

export function hasPending(): boolean {
  return pending !== null;
}
