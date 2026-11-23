const dateTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

export function formatDateTime(value?: string | null): string {
  if (!value) {
    return '-'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return dateTimeFormatter.format(date).replace(/\//g, '-')
}

export type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'

export const POST_STATUS_META: Record<
  string,
  { label: string; type: TagType; hint: string }
> = {
  pending_review: {
    label: '待审核',
    type: 'warning',
    hint: '内容尚未公开，通过后会立即进入首页与热榜。',
  },
  published: {
    label: '已公开',
    type: 'success',
    hint: '内容正在公开列表中展示。',
  },
  rejected: {
    label: '已拒绝',
    type: 'danger',
    hint: '作者可以在“我的发布”看到拒绝原因。',
  },
  unpublished: {
    label: '已下架',
    type: 'info',
    hint: '内容已从公开列表移除，但数据仍然保留。',
  },
}

export const SOURCE_LABELS: Record<string, string> = {
  self: '自己做',
  takeaway: '外卖',
  dine_in: '到店',
}

export const USER_STATUS_META: Record<
  string,
  { label: string; type: TagType }
> = {
  active: { label: '正常', type: 'success' },
  disabled: { label: '已封禁', type: 'danger' },
  system: { label: '系统账号', type: 'info' },
}

export const ACTION_LABELS: Record<string, string> = {
  'post.approve': '审核通过',
  'post.reject': '审核拒绝',
  'post.unpublish': '下架内容',
  'post.delete': '删除内容',
  'user.ban': '封禁用户',
  'user.unban': '解封用户',
}

export const ACTION_OPTIONS = Object.entries(ACTION_LABELS).map(
  ([value, label]) => ({ value, label }),
)
