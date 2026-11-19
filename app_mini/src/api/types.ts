export type Source = "self" | "takeaway" | "dine_in";
export type TargetType = "post" | "recipe";
export type RecipeCategory = "recommended" | "quick" | "one_pot" | "few";

export interface Author {
  id: string;
  nickname: string;
  avatarUrl: string | null;
}

export interface PostCard {
  id: string;
  title: string;
  review: string;
  source: Source;
  coverImage: string | null;
  images: string[];
  imageCount: number;
  author: Author | null;
  publishedAt: string | null;
  likeCount: number;
  likedByMe: boolean;
  savedByMe: boolean;
  status: string;
  distanceMeters?: number;
}

export interface AuthorRecipe {
  ingredients: string[];
  steps: string[];
}

export interface Ingredient {
  name: string;
  amount: string;
}

export interface Recipe {
  id: string;
  title: string;
  coverImage: string;
  totalMinutes: number;
  tools: string[];
  categories: string[];
  servings: number;
  mainIngredients: string[];
  ingredients: Ingredient[];
  steps: string[];
  preconditions: string | null;
  contentOrigin: string;
  validationStatus: string;
  savedByMe: boolean;
}

export interface PostDetail extends PostCard {
  authorRecipe: AuthorRecipe | null;
  recipe: Recipe | null;
  recipeOrigin: "author" | "platform_reference" | null;
  recipeLabel: string | null;
  takeawayStore: string | null;
  dineInAddress: string | null;
  coarseArea: string | null;
}

export interface RankItem extends PostCard {
  rank: number;
  effectiveLikeCount: number;
  mainIngredients: string[];
  ingredientOrigin: "author" | "platform_reference" | null;
}

export interface FeedPage {
  filter: "all" | "near";
  businessDate: string;
  items: PostCard[];
  nextCursor: string | null;
  hasMore: boolean;
}

export interface RankPage {
  statDate: string;
  timezone: string;
  generatedAt: string;
  items: RankItem[];
}

export interface RecipePage {
  items: Recipe[];
  nextCursor: string | null;
  hasMore: boolean;
}

export interface Profile {
  accountId: string;
  nickname: string;
  avatarUrl: string | null;
  phoneMasked: string;
  status: string;
}

export interface LoginResult {
  accountId: string;
  token: string;
  tokenType: string;
  expiresAt: string;
  isNewAccount: boolean;
  profile: Profile;
}

export interface FavoriteItem {
  targetType: TargetType;
  targetId: string;
  title: string;
  summary: string;
  coverImage: string | null;
  savedAt: string;
  available: boolean;
}

export interface FavoritePage {
  items: FavoriteItem[];
  nextCursor: string | null;
  hasMore: boolean;
}

export interface MyPostPage {
  items: PostCard[];
  nextCursor: string | null;
  hasMore: boolean;
}

export interface AIConstraints {
  maxMinutes?: number;
  tools?: string[];
  ingredients?: string[];
  avoid?: string[];
}

export interface AIChatPayload {
  contextType?: "home" | "post" | "recipe_list";
  contextId?: string;
  message: string;
  constraints?: AIConstraints;
}

export interface AIRecommendation {
  targetType: "recipe";
  targetId: string;
  title: string;
  summary: string;
  coverImage: string;
  reason: string;
}

export interface AIChatResult {
  conversationId: string;
  origin: string;
  message: string;
  recommendations: AIRecommendation[];
  quota: { limit: number; used: number; remaining: number };
}

export interface CreatePostPayload {
  title: string;
  review: string;
  source: Source;
  imageAssetIds: string[];
  authorRecipe?: AuthorRecipe | null;
  takeawayStore?: string | null;
  dineInAddress?: string | null;
  location?: {
    lat: number;
    lng: number;
    area?: string | null;
    publicConsent: boolean;
  } | null;
}

export interface PublishResult {
  postId: string;
  status: string;
  publishedAt: string | null;
  reviewRequired: boolean;
}
