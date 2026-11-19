import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { setToken } from "../api/client";
import type { LoginResult, Profile } from "../api/types";

const TOKEN_KEY = "mealmate_token";
const PROFILE_KEY = "mealmate_profile";

export const useSessionStore = defineStore("session", () => {
  const token = ref<string>((uni.getStorageSync(TOKEN_KEY) as string) || "");
  const profile = ref<Profile | null>(
    (uni.getStorageSync(PROFILE_KEY) as Profile | "") || null,
  );
  const isLoggedIn = computed(() => Boolean(token.value));

  function apply(result: LoginResult) {
    token.value = result.token;
    profile.value = result.profile;
    setToken(result.token);
    uni.setStorageSync(PROFILE_KEY, result.profile);
  }

  function clear() {
    token.value = "";
    profile.value = null;
    setToken("");
    uni.removeStorageSync(PROFILE_KEY);
  }

  return { token, profile, isLoggedIn, apply, clear };
});
