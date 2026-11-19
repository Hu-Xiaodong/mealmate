<script setup lang="ts">
import { onLaunch } from "@dcloudio/uni-app";

onLaunch(() => {
  // 会话由 Pinia 从本地存储恢复，无需额外引导。
});
</script>

<style>
page {
  --c-primary: #cc462c;
  --c-primary-deep: #b33226;
  --c-peach: #fff0eb;
  --c-text: #242424;
  --c-muted: #666666;
  --c-faint: #999999;
  --c-line: #ececee;
  --c-bg: #f6f7f8;
  --c-card: #ffffff;
  --c-success: #3d7d52;
  --radius-lg: 20px;
  --radius-md: 14px;
  --radius-sm: 10px;
  background: var(--c-bg);
  color: var(--c-text);
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue",
    "Microsoft YaHei", sans-serif;
  font-size: 15px;
  line-height: 1.5;
}

view,
text,
image,
scroll-view {
  box-sizing: border-box;
}

image {
  display: block;
}

.safe-bottom {
  padding-bottom: calc(12px + env(safe-area-inset-bottom));
}
</style>
