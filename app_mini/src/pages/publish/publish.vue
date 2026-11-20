<script setup lang="ts">
import { onLoad, onShow } from "@dcloudio/uni-app";
import { computed, ref } from "vue";

import { ApiError, api, mapStaticUrl, uploadImage } from "../../api/client";
import type {
  CreatePostPayload,
  DraftPayload,
  PlaceItem,
  Source,
  StoreLocation,
} from "../../api/types";
import AppHeader from "../../components/AppHeader.vue";
import EmptyState from "../../components/EmptyState.vue";
import { resolveMedia } from "../../config";
import { useSessionStore } from "../../stores/session";
import { distanceLabel, showError } from "../../utils/format";
import { requireLogin } from "../../utils/gate";

interface PickedImage {
  assetId: string;
  preview: string;
}

const TASTE_TAGS = [
  "清淡",
  "重口下饭",
  "微辣",
  "特辣",
  "酸甜",
  "咸鲜",
  "油炸",
  "烧烤",
  "汤羹",
  "面食",
];

const session = useSessionStore();

const images = ref<PickedImage[]>([]);
const uploading = ref(0);
const title = ref("");
const review = ref("");
const source = ref<Source>("self");
const store = ref("");
const address = ref("");
const avgPrice = ref("");
const tasteTags = ref<string[]>([]);
const recipeOpen = ref(false);
const ingredientText = ref("");
const stepText = ref("");
const locationOpen = ref(false);
const area = ref("");
const coords = ref<{ lat: number; lng: number } | null>(null);
const submitting = ref(false);
const redirected = ref(false);
const idempotencyKey = ref(makeKey());

const draftId = ref("");
const draftLoading = ref(false);
const savingDraft = ref(false);

const mapsEnabled = ref(false);
const keyword = ref("");
const places = ref<PlaceItem[]>([]);
const searching = ref(false);
const storeLocation = ref<StoreLocation | null>(null);
const mapPreviewFailed = ref(false);

const SOURCES: { value: Source; label: string }[] = [
  { value: "self", label: "自己做" },
  { value: "takeaway", label: "外卖" },
  { value: "dine_in", label: "到店" },
];

const canSubmit = computed(
  () =>
    session.isLoggedIn &&
    !submitting.value &&
    !draftLoading.value &&
    uploading.value === 0 &&
    images.value.length > 0,
);

const mapPreviewUrl = computed(() => {
  const picked = storeLocation.value;
  if (!picked) return "";
  return mapStaticUrl({ lat: picked.lat, lng: picked.lng, zoom: 16, width: 640, height: 320 });
});

const placeName = computed(() => {
  if (!storeLocation.value) return "";
  if (source.value === "takeaway") return store.value.trim();
  if (source.value === "dine_in") return address.value.trim();
  return "";
});

function makeKey(): string {
  return `pub-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function toast(message: string) {
  uni.showToast({ title: message, icon: "none" });
}

onLoad((options) => {
  void loadMapConfig();
  const id = options?.id;
  if (id) {
    draftId.value = id;
    void loadDraft(id);
  }
});

onShow(() => {
  if (!session.isLoggedIn && !redirected.value) {
    redirected.value = true;
    requireLogin();
  }
});

async function loadMapConfig() {
  try {
    const config = await api.mapConfig();
    mapsEnabled.value = Boolean(config.enabled);
  } catch {
    // 配置读取失败时退回手动填写，不阻塞发布。
    mapsEnabled.value = false;
  }
}

async function loadDraft(id: string) {
  draftLoading.value = true;
  try {
    const draft = await api.draft(id);
    title.value = draft.title || "";
    review.value = draft.review || "";
    source.value = draft.source || "self";
    store.value = draft.takeawayStore || "";
    address.value = draft.dineInAddress || "";
    avgPrice.value =
      draft.avgPrice === null || draft.avgPrice === undefined ? "" : String(draft.avgPrice);
    tasteTags.value = draft.tasteTags || [];

    const ingredients = draft.authorRecipe?.ingredients || [];
    const steps = draft.authorRecipe?.steps || [];
    ingredientText.value = ingredients.join("\n");
    stepText.value = steps.join("\n");
    recipeOpen.value = ingredients.length > 0 || steps.length > 0;

    const urls = draft.images || [];
    images.value = (draft.imageAssetIds || []).map((assetId, index) => ({
      assetId,
      preview: resolveMedia(urls[index] || ""),
    }));

    if (draft.location) {
      coords.value = { lat: draft.location.lat, lng: draft.location.lng };
      area.value = draft.location.area || "";
      locationOpen.value = true;
    }
    storeLocation.value = draft.storeLocation || null;
    mapPreviewFailed.value = false;
  } catch (error) {
    showError(error, "草稿加载失败");
  } finally {
    draftLoading.value = false;
  }
}

function goLogin() {
  uni.navigateTo({ url: "/pages/login/login" });
}

function pickImages() {
  const remain = 9 - images.value.length;
  if (remain <= 0) {
    toast("最多上传 9 张图片");
    return;
  }
  uni.chooseImage({
    count: remain,
    sizeType: ["compressed"],
    sourceType: ["album", "camera"],
    success: (result) => {
      const paths = result.tempFilePaths as string[];
      for (const path of paths) void uploadOne(path);
    },
    fail: () => {
      // 用户取消选择时不打扰。
    },
  });
}

async function uploadOne(path: string) {
  uploading.value += 1;
  try {
    const asset = await uploadImage(path);
    images.value.push({ assetId: asset.assetId, preview: path });
  } catch (error) {
    showError(error, "图片上传失败");
  } finally {
    uploading.value -= 1;
  }
}

function removeImage(index: number) {
  images.value.splice(index, 1);
}

function toggleLocation() {
  if (locationOpen.value) {
    locationOpen.value = false;
    return;
  }
  if (coords.value) {
    locationOpen.value = true;
    return;
  }
  uni.getLocation({
    type: "gcj02",
    success: (result) => {
      coords.value = { lat: result.latitude, lng: result.longitude };
      locationOpen.value = true;
    },
    fail: () => {
      toast("未获取到位置，这条饭帖不会出现在附近");
    },
  });
}

function onPriceInput(event: { detail: { value: string } }) {
  const digits = String(event.detail.value || "")
    .replace(/\D/g, "")
    .slice(0, 4);
  avgPrice.value = digits;
  return digits;
}

function toggleTag(tag: string) {
  const index = tasteTags.value.indexOf(tag);
  if (index >= 0) {
    tasteTags.value.splice(index, 1);
    return;
  }
  if (tasteTags.value.length >= 3) {
    toast("最多选择 3 个口味标签");
    return;
  }
  tasteTags.value.push(tag);
}

function parseLines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function parsedPrice(): number | null {
  const text = avgPrice.value.trim();
  if (!text) return null;
  return Number(text);
}

async function searchPlaces() {
  const text = keyword.value.trim();
  if (!text) {
    toast("先输入店铺关键词");
    return;
  }
  if (searching.value) return;
  searching.value = true;
  try {
    const page = await api.searchPlaces({
      keyword: text,
      lat: locationOpen.value && coords.value ? coords.value.lat : undefined,
      lng: locationOpen.value && coords.value ? coords.value.lng : undefined,
      limit: 10,
    });
    places.value = page.items || [];
    if (!places.value.length) toast("没有找到相关店铺");
  } catch (error) {
    if (error instanceof ApiError && error.status === 503) {
      toast("地图暂不可用，可手动填写地址");
    } else {
      showError(error, "搜索店铺失败");
    }
  } finally {
    searching.value = false;
  }
}

function selectPlace(place: PlaceItem) {
  storeLocation.value = { lat: place.lat, lng: place.lng, poiId: place.id };
  mapPreviewFailed.value = false;
  if (source.value === "takeaway") {
    store.value = place.name;
  } else if (source.value === "dine_in") {
    address.value = `${place.name} ${place.address}`.trim();
  }
  places.value = [];
}

function reselectPlace() {
  storeLocation.value = null;
  places.value = [];
}

function clearPlace() {
  storeLocation.value = null;
  places.value = [];
  keyword.value = "";
}

function buildLocation() {
  return locationOpen.value && coords.value
    ? {
        lat: coords.value.lat,
        lng: coords.value.lng,
        area: area.value.trim() || null,
        publicConsent: true,
      }
    : null;
}

function buildAuthorRecipe() {
  const ingredients = parseLines(ingredientText.value);
  const steps = parseLines(stepText.value);
  return recipeOpen.value && ingredients.length && steps.length ? { ingredients, steps } : null;
}

function buildStoreLocation(): StoreLocation | null {
  return source.value === "self" ? null : storeLocation.value;
}

async function saveDraft() {
  if (!session.isLoggedIn) {
    goLogin();
    return;
  }
  if (savingDraft.value || submitting.value) return;
  if (uploading.value > 0) {
    toast("图片还在上传，请稍候");
    return;
  }

  const payload: DraftPayload = {
    title: title.value.trim(),
    review: review.value.trim(),
    source: source.value,
    imageAssetIds: images.value.map((item) => item.assetId),
    authorRecipe: buildAuthorRecipe(),
    takeawayStore: source.value === "takeaway" ? store.value.trim() || null : null,
    dineInAddress: source.value === "dine_in" ? address.value.trim() || null : null,
    location: buildLocation(),
    avgPrice: parsedPrice(),
    tasteTags: tasteTags.value,
    storeLocation: buildStoreLocation(),
  };

  savingDraft.value = true;
  try {
    const result = draftId.value
      ? await api.updateDraft(draftId.value, payload)
      : await api.createDraft(payload);
    draftId.value = result.postId;
    toast("草稿已保存");
  } catch (error) {
    showError(error, "草稿保存失败");
  } finally {
    savingDraft.value = false;
  }
}

async function submit() {
  if (!session.isLoggedIn) {
    goLogin();
    return;
  }
  if (submitting.value || draftLoading.value) return;
  if (uploading.value > 0) {
    toast("图片还在上传，请稍候");
    return;
  }
  const name = title.value.trim();
  if (!name) {
    toast("给这顿饭起个名字");
    return;
  }
  const text = review.value.trim();
  if (!text) {
    toast("写一句真实的评价");
    return;
  }
  if (!images.value.length) {
    toast("至少上传 1 张图片");
    return;
  }
  if (source.value === "takeaway" && !store.value.trim()) {
    toast("外卖来源需要填写店家名称");
    return;
  }
  if (source.value === "dine_in" && !address.value.trim()) {
    toast("到店来源需要填写店铺地址");
    return;
  }
  if (recipeOpen.value) {
    const ingredients = parseLines(ingredientText.value);
    const steps = parseLines(stepText.value);
    if (!ingredients.length || !steps.length) {
      toast("作者做法需要食材和步骤一起填写");
      return;
    }
  }

  const payload: CreatePostPayload = {
    title: name,
    review: text,
    source: source.value,
    imageAssetIds: images.value.map((item) => item.assetId),
    authorRecipe: buildAuthorRecipe(),
    takeawayStore: source.value === "takeaway" ? store.value.trim() : null,
    dineInAddress: source.value === "dine_in" ? address.value.trim() : null,
    avgPrice: parsedPrice(),
    tasteTags: tasteTags.value,
    storeLocation: buildStoreLocation(),
    location: buildLocation(),
  };

  submitting.value = true;
  try {
    const result = draftId.value
      ? await api.publishDraft(draftId.value, payload)
      : await api.createPost(payload, idempotencyKey.value);
    idempotencyKey.value = makeKey();
    if (result.reviewRequired) {
      toast("已提交审核");
      setTimeout(() => {
        uni.navigateBack({ fail: () => uni.switchTab({ url: "/pages/home/home" }) });
      }, 900);
    } else {
      toast("发布成功");
      uni.redirectTo({ url: `/pages/post/detail?id=${result.postId}` });
    }
  } catch (error) {
    showError(error);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <view class="page">
    <AppHeader
      title="发布今天的饭"
      :subtitle="draftId ? '继续编辑未完成的草稿' : '真实的一餐，比精致的摆拍更有用'"
      back
    />

    <EmptyState
      v-if="!session.isLoggedIn"
      title="登录后才能发布"
      description="登录后可以上传图片、记录评价，也能管理自己的发布。"
      action-text="手机号登录"
      @action="goLogin"
    />

    <view v-else class="sheet">
      <view v-if="draftLoading" class="hint-card">
        <text class="hint-text">草稿加载中…</text>
      </view>

      <view class="section card">
        <text class="section-title">这一餐的照片</text>
        <text class="section-hint">1–9 张，单张不超过 5MB。第一张会作为封面。</text>
        <view class="grid">
          <view v-for="(image, index) in images" :key="image.assetId" class="tile">
            <image class="tile-image" :src="image.preview" mode="aspectFill" />
            <view class="remove" @tap.stop="removeImage(index)">
              <text class="remove-text">×</text>
            </view>
            <text v-if="index === 0" class="cover-tag">封面</text>
          </view>

          <view
            v-if="images.length < 9"
            class="tile add"
            :class="{ busy: uploading > 0 }"
            @tap="pickImages"
          >
            <text class="plus">＋</text>
            <text class="add-text">{{ uploading > 0 ? "上传中…" : "添加图片" }}</text>
          </view>
        </view>
      </view>

      <view class="section card">
        <view class="field">
          <view class="label-row">
            <text class="label">菜名</text>
            <text class="counter">{{ title.length }}/24</text>
          </view>
          <input
            v-model="title"
            class="input"
            :maxlength="24"
            placeholder="例如：番茄鸡蛋盖饭"
            placeholder-class="ph"
          />
        </view>

        <view class="field">
          <view class="label-row">
            <text class="label">评价</text>
            <text class="counter">{{ review.length }}/200</text>
          </view>
          <textarea
            v-model="review"
            class="textarea"
            :maxlength="200"
            placeholder="味道、分量、踩过的坑，都可以写下来"
            placeholder-class="ph"
          />
        </view>

        <view class="field">
          <text class="label">来源</text>
          <view class="seg">
            <view
              v-for="item in SOURCES"
              :key="item.value"
              class="seg-item"
              :class="{ active: source === item.value }"
              @tap="source = item.value"
            >
              <text>{{ item.label }}</text>
            </view>
          </view>
        </view>

        <view v-if="source === 'takeaway'" class="field">
          <text class="label">店家名称</text>
          <input
            v-model="store"
            class="input"
            :maxlength="80"
            placeholder="例如：街角便当"
            placeholder-class="ph"
          />
        </view>

        <view v-if="source === 'dine_in'" class="field">
          <text class="label">店铺地址</text>
          <input
            v-model="address"
            class="input"
            :maxlength="160"
            placeholder="例如：演示路 12 号 · 老友粉店"
            placeholder-class="ph"
          />
        </view>
      </view>

      <view class="section card">
        <view class="field">
          <view class="label-row">
            <text class="label">人均价格（元）</text>
            <text class="counter">可选</text>
          </view>
          <input
            :value="avgPrice"
            class="input"
            type="number"
            :maxlength="4"
            placeholder="例如：28"
            placeholder-class="ph"
            @input="onPriceInput"
          />
        </view>

        <view class="field">
          <view class="label-row">
            <text class="label">口味标签</text>
            <text class="counter">{{ tasteTags.length }}/3</text>
          </view>
          <view class="chips">
            <view
              v-for="tag in TASTE_TAGS"
              :key="tag"
              class="chip"
              :class="{ on: tasteTags.includes(tag) }"
              @tap="toggleTag(tag)"
            >
              <text>{{ tag }}</text>
            </view>
          </view>
        </view>
      </view>

      <view v-if="mapsEnabled && source !== 'self'" class="section card">
        <text class="section-title">在地图上选店铺</text>
        <text class="section-hint">选中后会保存店铺坐标，详情页可以查看地图并一键导航。</text>

        <view class="search-row">
          <input
            v-model="keyword"
            class="input search-input"
            :maxlength="40"
            confirm-type="search"
            placeholder="搜索店铺，例如：老友粉店"
            placeholder-class="ph"
            @confirm="searchPlaces"
          />
          <view class="search-btn" :class="{ busy: searching }" @tap="searchPlaces">
            <text class="search-btn-text">{{ searching ? "搜索中…" : "搜索" }}</text>
          </view>
        </view>

        <view v-if="places.length" class="place-list">
          <view v-for="item in places" :key="item.id" class="place-item" @tap="selectPlace(item)">
            <view class="place-info">
              <text class="place-name">{{ item.name }}</text>
              <text class="place-address">{{ item.address }}</text>
            </view>
            <text v-if="item.distanceMeters !== null" class="place-distance">
              {{ distanceLabel(item.distanceMeters) }}
            </text>
          </view>
        </view>

        <view v-if="storeLocation" class="map-preview">
          <image
            v-if="!mapPreviewFailed"
            class="map-image"
            :src="mapPreviewUrl"
            mode="aspectFill"
            @error="mapPreviewFailed = true"
          />
          <view v-else class="map-fallback">
            <text class="map-fallback-text">地图暂不可用</text>
          </view>
          <view class="map-foot">
            <text class="map-name">{{ placeName || "已选店铺" }}</text>
            <view class="map-actions">
              <view class="map-btn" @tap="reselectPlace"><text class="map-btn-text">重新选择</text></view>
              <view class="map-btn" @tap="clearPlace"><text class="map-btn-text">清除</text></view>
            </view>
          </view>
        </view>
      </view>

      <view class="section card">
        <view class="switch-row" @tap="recipeOpen = !recipeOpen">
          <view class="switch-texts">
            <text class="section-title">补充我的做法</text>
            <text class="section-hint">可选。你写的食材和步骤会优先展示给其他饭友。</text>
          </view>
          <text class="chevron">{{ recipeOpen ? "▾" : "▸" }}</text>
        </view>

        <view v-if="recipeOpen" class="recipe-body">
          <view class="field">
            <text class="label">食材（每行一项）</text>
            <textarea
              v-model="ingredientText"
              class="textarea small"
              placeholder="豆角 200 克&#10;鲜面条 150 克&#10;蒜 2 瓣"
              placeholder-class="ph"
            />
          </view>
          <view class="field">
            <text class="label">步骤（每行一步）</text>
            <textarea
              v-model="stepText"
              class="textarea small"
              placeholder="豆角掰段炒香&#10;加水铺面焖 12 分钟&#10;拌匀收汁"
              placeholder-class="ph"
            />
          </view>
        </view>
      </view>

      <view class="section card">
        <view class="switch-row" @tap="toggleLocation">
          <view class="switch-texts">
            <text class="section-title">公开大概位置</text>
            <text class="section-hint">开启后会出现在「附近 3 公里」，只保留百米级精度。</text>
          </view>
          <view class="switch" :class="{ on: locationOpen }">
            <view class="knob" :class="{ on: locationOpen }"></view>
          </view>
        </view>
        <view v-if="locationOpen" class="field">
          <text class="label">位置描述（可选）</text>
          <input
            v-model="area"
            class="input"
            :maxlength="80"
            placeholder="例如：徐汇区某商圈"
            placeholder-class="ph"
          />
        </view>
      </view>

      <view class="actions">
        <view class="draft-btn" :class="{ disabled: savingDraft }" @tap="saveDraft">
          <text class="draft-btn-text">{{ savingDraft ? "保存中…" : "存草稿" }}</text>
        </view>
        <view class="submit" :class="{ disabled: !canSubmit }" @tap="submit">
          <text class="submit-text">{{ submitting ? "发布中…" : draftId ? "发布草稿" : "发布" }}</text>
        </view>
      </view>
      <text class="footnote">发布后会先进入审核，审核通过后出现在首页与热榜。</text>
    </view>
  </view>
</template>

<style>
.page {
  padding: 0 16px 40px;
}

.sheet {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.hint-card {
  padding: 12px 16px;
  border-radius: var(--radius-lg);
  background: var(--c-peach);
}

.hint-text {
  font-size: 12px;
  color: var(--c-primary-deep);
}

.card {
  background: var(--c-card);
  border-radius: var(--radius-lg);
  box-shadow: 0 6px 18px rgba(36, 36, 36, 0.05);
}

.section {
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--c-text);
}

.section-hint {
  font-size: 12px;
  color: var(--c-muted);
  line-height: 1.55;
}

.grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.tile {
  position: relative;
  width: 30%;
  height: 96px;
  border-radius: 12px;
  overflow: hidden;
  background: var(--c-bg);
}

.tile-image {
  width: 100%;
  height: 100%;
}

.remove {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 20px;
  height: 20px;
  border-radius: 10px;
  background: rgba(36, 36, 36, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
}

.remove-text {
  color: #ffffff;
  font-size: 14px;
  line-height: 1;
}

.cover-tag {
  position: absolute;
  left: 6px;
  bottom: 6px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(204, 70, 44, 0.9);
  color: #ffffff;
  font-size: 10px;
}

.tile.add {
  border: 1px dashed rgba(204, 70, 44, 0.4);
  background: var(--c-peach);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.tile.add.busy {
  opacity: 0.7;
}

.plus {
  font-size: 22px;
  color: var(--c-primary);
  line-height: 1;
}

.add-text {
  font-size: 11px;
  color: var(--c-primary-deep);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.label {
  font-size: 13px;
  color: var(--c-muted);
}

.counter {
  font-size: 11px;
  color: var(--c-faint);
}

.input {
  height: 44px;
  padding: 0 14px;
  border-radius: 12px;
  background: var(--c-bg);
  font-size: 15px;
  color: var(--c-text);
}

.textarea {
  width: 100%;
  height: 96px;
  padding: 12px 14px;
  border-radius: 12px;
  background: var(--c-bg);
  font-size: 14px;
  line-height: 1.6;
  color: var(--c-text);
  box-sizing: border-box;
}

.textarea.small {
  height: 110px;
}

.ph {
  color: var(--c-faint);
  font-size: 13px;
}

.seg {
  display: flex;
  padding: 4px;
  border-radius: 12px;
  background: var(--c-bg);
}

.seg-item {
  flex: 1;
  padding: 9px 0;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: var(--c-muted);
}

.seg-item.active {
  background: var(--c-card);
  color: var(--c-primary-deep);
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(36, 36, 36, 0.06);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chip {
  padding: 7px 14px;
  border-radius: 999px;
  background: var(--c-bg);
  font-size: 12px;
  color: var(--c-muted);
  border: 1px solid transparent;
}

.chip.on {
  background: var(--c-peach);
  color: var(--c-primary-deep);
  border-color: rgba(204, 70, 44, 0.4);
  font-weight: 600;
}

.search-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.search-input {
  flex: 1;
}

.search-btn {
  flex-shrink: 0;
  padding: 0 18px;
  height: 44px;
  border-radius: 12px;
  background: var(--c-primary);
  display: flex;
  align-items: center;
  justify-content: center;
}

.search-btn.busy {
  opacity: 0.65;
}

.search-btn-text {
  font-size: 13px;
  font-weight: 600;
  color: #ffffff;
}

.place-list {
  display: flex;
  flex-direction: column;
  border-radius: 12px;
  background: var(--c-bg);
  overflow: hidden;
}

.place-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--c-line);
}

.place-item:last-child {
  border-bottom: none;
}

.place-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.place-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--c-text);
}

.place-address {
  font-size: 12px;
  color: var(--c-muted);
  line-height: 1.5;
}

.place-distance {
  font-size: 11px;
  color: var(--c-primary-deep);
  flex-shrink: 0;
}

.map-preview {
  border-radius: 12px;
  overflow: hidden;
  background: var(--c-bg);
}

.map-image {
  width: 100%;
  height: 160px;
  background: var(--c-peach);
}

.map-fallback {
  height: 160px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--c-peach);
}

.map-fallback-text {
  font-size: 12px;
  color: var(--c-primary-deep);
}

.map-foot {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
}

.map-name {
  flex: 1;
  font-size: 12px;
  color: var(--c-text);
}

.map-actions {
  display: flex;
  gap: 8px;
}

.map-btn {
  padding: 5px 12px;
  border-radius: 999px;
  background: var(--c-card);
  border: 1px solid var(--c-line);
}

.map-btn-text {
  font-size: 11px;
  color: var(--c-muted);
}

.switch-row {
  display: flex;
  align-items: center;
  gap: 14px;
}

.switch-texts {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.chevron {
  font-size: 14px;
  color: var(--c-faint);
}

.recipe-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-top: 4px;
}

.switch {
  width: 44px;
  height: 26px;
  border-radius: 13px;
  background: var(--c-line);
  padding: 3px;
  display: flex;
  flex-shrink: 0;
  transition: background 0.2s;
}

.switch.on {
  background: var(--c-primary);
}

.knob {
  width: 20px;
  height: 20px;
  border-radius: 10px;
  background: #ffffff;
  transition: transform 0.2s;
}

.knob.on {
  transform: translateX(18px);
}

.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 4px;
}

.draft-btn {
  padding: 14px 22px;
  border-radius: 999px;
  background: var(--c-peach);
  display: flex;
  align-items: center;
  justify-content: center;
}

.draft-btn.disabled {
  opacity: 0.6;
}

.draft-btn-text {
  font-size: 14px;
  font-weight: 600;
  color: var(--c-primary-deep);
}

.submit {
  flex: 1;
  padding: 14px 0;
  border-radius: 999px;
  background: var(--c-primary);
  box-shadow: 0 10px 20px rgba(204, 70, 44, 0.22);
  display: flex;
  align-items: center;
  justify-content: center;
}

.submit.disabled {
  opacity: 0.55;
}

.submit-text {
  font-size: 15px;
  font-weight: 600;
  color: #ffffff;
}

.footnote {
  font-size: 12px;
  color: var(--c-faint);
  text-align: center;
  line-height: 1.6;
}
</style>
