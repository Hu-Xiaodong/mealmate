/// 与 `app_mini/src/api/types.ts` 对齐的 HTTP 数据模型。
class Author {
  const Author({required this.id, required this.nickname, this.avatarUrl});

  final String id;
  final String nickname;
  final String? avatarUrl;

  factory Author.fromJson(Map<String, dynamic> json) => Author(
    id: json['id'] as String? ?? '',
    nickname: json['nickname'] as String? ?? '饭友',
    avatarUrl: json['avatarUrl'] as String?,
  );
}

class PostCard {
  PostCard({
    required this.id,
    required this.title,
    required this.review,
    required this.source,
    this.coverImage,
    required this.images,
    required this.imageCount,
    this.author,
    this.publishedAt,
    required this.likeCount,
    required this.likedByMe,
    required this.savedByMe,
    required this.status,
    this.distanceMeters,
    this.avgPrice,
    this.tasteTags = const [],
    this.updatedAt,
  });

  final String id;
  final String title;
  final String review;
  final String source;
  final String? coverImage;
  final List<String> images;
  final int imageCount;
  final Author? author;
  final String? publishedAt;
  int likeCount;
  bool likedByMe;
  bool savedByMe;
  final String status;
  final int? distanceMeters;
  final int? avgPrice;
  final List<String> tasteTags;
  /// 草稿卡片才有值，用于“最近修改时间”排序展示。
  final String? updatedAt;

  bool get pendingReview => status != 'published';

  factory PostCard.fromJson(Map<String, dynamic> json) {
    final author = json['author'];
    final images = json['images'];
    final tasteTags = json['tasteTags'];
    return PostCard(
      id: json['id'] as String? ?? '',
      title: json['title'] as String? ?? '',
      review: json['review'] as String? ?? '',
      source: json['source'] as String? ?? 'self',
      coverImage: json['coverImage'] as String?,
      images: images is List
          ? images.map((item) => item as String).toList(growable: false)
          : const [],
      imageCount: json['imageCount'] as int? ?? 0,
      author: author is Map<String, dynamic> ? Author.fromJson(author) : null,
      publishedAt: json['publishedAt'] as String?,
      likeCount: json['likeCount'] as int? ?? 0,
      likedByMe: json['likedByMe'] as bool? ?? false,
      savedByMe: json['savedByMe'] as bool? ?? false,
      status: json['status'] as String? ?? 'published',
      distanceMeters: json['distanceMeters'] as int?,
      avgPrice: json['avgPrice'] as int?,
      tasteTags: tasteTags is List
          ? tasteTags.map((item) => item as String).toList(growable: false)
          : const [],
      updatedAt: json['updatedAt'] as String?,
    );
  }
}

class AuthorRecipe {
  const AuthorRecipe({required this.ingredients, required this.steps});

  final List<String> ingredients;
  final List<String> steps;

  factory AuthorRecipe.fromJson(Map<String, dynamic> json) {
    final ingredients = json['ingredients'];
    final steps = json['steps'];
    return AuthorRecipe(
      ingredients: ingredients is List
          ? ingredients.map((item) => item as String).toList(growable: false)
          : const [],
      steps: steps is List
          ? steps.map((item) => item as String).toList(growable: false)
          : const [],
    );
  }

  Map<String, dynamic> toJson() => {'ingredients': ingredients, 'steps': steps};
}

class Ingredient {
  const Ingredient({required this.name, required this.amount});

  final String name;
  final String amount;

  factory Ingredient.fromJson(Map<String, dynamic> json) => Ingredient(
    name: json['name'] as String? ?? '',
    amount: json['amount'] as String? ?? '',
  );
}

class Recipe {
  Recipe({
    required this.id,
    required this.title,
    required this.coverImage,
    required this.totalMinutes,
    required this.tools,
    required this.categories,
    required this.servings,
    required this.mainIngredients,
    required this.ingredients,
    required this.steps,
    this.preconditions,
    required this.contentOrigin,
    required this.validationStatus,
    required this.savedByMe,
  });

  final String id;
  final String title;
  final String coverImage;
  final int? totalMinutes;
  final List<String> tools;
  final List<String> categories;
  final int servings;
  final List<String> mainIngredients;
  final List<Ingredient> ingredients;
  final List<String> steps;
  final String? preconditions;
  final String contentOrigin;
  final String validationStatus;
  bool savedByMe;

  factory Recipe.fromJson(Map<String, dynamic> json) {
    final tools = json['tools'];
    final categories = json['categories'];
    final mainIngredients = json['mainIngredients'];
    final ingredients = json['ingredients'];
    final steps = json['steps'];
    return Recipe(
      id: json['id'] as String? ?? '',
      title: json['title'] as String? ?? '',
      coverImage: json['coverImage'] as String? ?? '',
      totalMinutes: (json['totalMinutes'] as num?)?.toInt(),
      tools: tools is List
          ? tools.map((item) => item as String).toList(growable: false)
          : const [],
      categories: categories is List
          ? categories.map((item) => item as String).toList(growable: false)
          : const [],
      servings: (json['servings'] as num?)?.toInt() ?? 1,
      mainIngredients: mainIngredients is List
          ? mainIngredients.map((item) => item as String).toList(growable: false)
          : const [],
      ingredients: ingredients is List
          ? ingredients
                .whereType<Map<String, dynamic>>()
                .map(Ingredient.fromJson)
                .toList(growable: false)
          : const [],
      steps: steps is List
          ? steps.map((item) => item as String).toList(growable: false)
          : const [],
      preconditions: json['preconditions'] as String?,
      contentOrigin: json['contentOrigin'] as String? ?? '',
      validationStatus: json['validationStatus'] as String? ?? '',
      savedByMe: json['savedByMe'] as bool? ?? false,
    );
  }
}

class PostDetail {
  PostDetail({
    required this.id,
    required this.title,
    required this.review,
    required this.source,
    this.coverImage,
    required this.images,
    required this.imageCount,
    this.author,
    this.publishedAt,
    required this.likeCount,
    required this.likedByMe,
    required this.savedByMe,
    required this.status,
    this.distanceMeters,
    this.authorRecipe,
    this.recipe,
    this.recipeOrigin,
    this.recipeLabel,
    this.takeawayStore,
    this.dineInAddress,
    this.coarseArea,
    this.avgPrice,
    this.tasteTags = const [],
    this.storeLocation,
  });

  final String id;
  final String title;
  final String review;
  final String source;
  final String? coverImage;
  final List<String> images;
  final int imageCount;
  final Author? author;
  final String? publishedAt;
  int likeCount;
  bool likedByMe;
  bool savedByMe;
  final String status;
  final int? distanceMeters;
  final AuthorRecipe? authorRecipe;
  final Recipe? recipe;
  final String? recipeOrigin;
  final String? recipeLabel;
  final String? takeawayStore;
  final String? dineInAddress;
  final String? coarseArea;
  final int? avgPrice;
  final List<String> tasteTags;
  final StoreLocation? storeLocation;

  factory PostDetail.fromJson(Map<String, dynamic> json) {
    final author = json['author'];
    final images = json['images'];
    final authorRecipe = json['authorRecipe'];
    final recipe = json['recipe'];
    final tasteTags = json['tasteTags'];
    final storeLocation = json['storeLocation'];
    return PostDetail(
      id: json['id'] as String? ?? '',
      title: json['title'] as String? ?? '',
      review: json['review'] as String? ?? '',
      source: json['source'] as String? ?? 'self',
      coverImage: json['coverImage'] as String?,
      images: images is List
          ? images.map((item) => item as String).toList(growable: false)
          : const [],
      imageCount: json['imageCount'] as int? ?? 0,
      author: author is Map<String, dynamic> ? Author.fromJson(author) : null,
      publishedAt: json['publishedAt'] as String?,
      likeCount: json['likeCount'] as int? ?? 0,
      likedByMe: json['likedByMe'] as bool? ?? false,
      savedByMe: json['savedByMe'] as bool? ?? false,
      status: json['status'] as String? ?? 'published',
      distanceMeters: json['distanceMeters'] as int?,
      authorRecipe: authorRecipe is Map<String, dynamic>
          ? AuthorRecipe.fromJson(authorRecipe)
          : null,
      recipe: recipe is Map<String, dynamic> ? Recipe.fromJson(recipe) : null,
      recipeOrigin: json['recipeOrigin'] as String?,
      recipeLabel: json['recipeLabel'] as String?,
      takeawayStore: json['takeawayStore'] as String?,
      dineInAddress: json['dineInAddress'] as String?,
      coarseArea: json['coarseArea'] as String?,
      avgPrice: json['avgPrice'] as int?,
      tasteTags: tasteTags is List
          ? tasteTags.map((item) => item as String).toList(growable: false)
          : const [],
      storeLocation: storeLocation is Map<String, dynamic>
          ? StoreLocation.fromJson(storeLocation)
          : null,
    );
  }
}

class RankItem {
  const RankItem({
    required this.post,
    required this.rank,
    required this.effectiveLikeCount,
    required this.mainIngredients,
    this.ingredientOrigin,
  });

  final PostCard post;
  final int rank;
  final int effectiveLikeCount;
  final List<String> mainIngredients;
  final String? ingredientOrigin;

  factory RankItem.fromJson(Map<String, dynamic> json) {
    final ingredients = json['mainIngredients'];
    return RankItem(
      post: PostCard.fromJson(json),
      rank: json['rank'] as int? ?? 0,
      effectiveLikeCount: json['effectiveLikeCount'] as int? ?? 0,
      mainIngredients: ingredients is List
          ? ingredients.map((item) => item as String).toList(growable: false)
          : const [],
      ingredientOrigin: json['ingredientOrigin'] as String?,
    );
  }
}

class FeedPage {
  const FeedPage({
    required this.filter,
    required this.businessDate,
    required this.items,
    this.nextCursor,
    required this.hasMore,
  });

  final String filter;
  final String businessDate;
  final List<PostCard> items;
  final String? nextCursor;
  final bool hasMore;

  factory FeedPage.fromJson(Map<String, dynamic> json) {
    final items = json['items'];
    return FeedPage(
      filter: json['filter'] as String? ?? 'all',
      businessDate: json['businessDate'] as String? ?? '',
      items: items is List
          ? items
                .whereType<Map<String, dynamic>>()
                .map(PostCard.fromJson)
                .toList(growable: false)
          : const [],
      nextCursor: json['nextCursor'] as String?,
      hasMore: json['hasMore'] as bool? ?? false,
    );
  }
}

class RankPage {
  const RankPage({
    required this.statDate,
    required this.timezone,
    required this.generatedAt,
    required this.items,
  });

  final String statDate;
  final String timezone;
  final String generatedAt;
  final List<RankItem> items;

  factory RankPage.fromJson(Map<String, dynamic> json) {
    final items = json['items'];
    return RankPage(
      statDate: json['statDate'] as String? ?? '',
      timezone: json['timezone'] as String? ?? '',
      generatedAt: json['generatedAt'] as String? ?? '',
      items: items is List
          ? items
                .whereType<Map<String, dynamic>>()
                .map(RankItem.fromJson)
                .toList(growable: false)
          : const [],
    );
  }
}

class RecipePage {
  const RecipePage({
    required this.items,
    this.nextCursor,
    required this.hasMore,
  });

  final List<Recipe> items;
  final String? nextCursor;
  final bool hasMore;

  factory RecipePage.fromJson(Map<String, dynamic> json) {
    final items = json['items'];
    return RecipePage(
      items: items is List
          ? items.whereType<Map<String, dynamic>>().map(Recipe.fromJson).toList(
              growable: false,
            )
          : const [],
      nextCursor: json['nextCursor'] as String?,
      hasMore: json['hasMore'] as bool? ?? false,
    );
  }
}

class Profile {
  const Profile({
    required this.accountId,
    required this.nickname,
    this.avatarUrl,
    required this.phoneMasked,
    required this.status,
  });

  final String accountId;
  final String nickname;
  final String? avatarUrl;
  final String phoneMasked;
  final String status;

  factory Profile.fromJson(Map<String, dynamic> json) => Profile(
    accountId: json['accountId'] as String? ?? '',
    nickname: json['nickname'] as String? ?? '饭友',
    avatarUrl: json['avatarUrl'] as String?,
    phoneMasked: json['phoneMasked'] as String? ?? '',
    status: json['status'] as String? ?? '',
  );

  Map<String, dynamic> toJson() => {
    'accountId': accountId,
    'nickname': nickname,
    'avatarUrl': avatarUrl,
    'phoneMasked': phoneMasked,
    'status': status,
  };
}

class LoginResult {
  const LoginResult({
    required this.accountId,
    required this.token,
    required this.tokenType,
    required this.expiresAt,
    required this.isNewAccount,
    required this.profile,
  });

  final String accountId;
  final String token;
  final String tokenType;
  final String expiresAt;
  final bool isNewAccount;
  final Profile profile;

  factory LoginResult.fromJson(Map<String, dynamic> json) {
    final profile = json['profile'];
    return LoginResult(
      accountId: json['accountId'] as String? ?? '',
      token: json['token'] as String? ?? '',
      tokenType: json['tokenType'] as String? ?? '',
      expiresAt: json['expiresAt'] as String? ?? '',
      isNewAccount: json['isNewAccount'] as bool? ?? false,
      profile: profile is Map<String, dynamic>
          ? Profile.fromJson(profile)
          : const Profile(
              accountId: '',
              nickname: '饭友',
              phoneMasked: '',
              status: '',
            ),
    );
  }
}

class SmsCodeResult {
  const SmsCodeResult({
    required this.challengeId,
    required this.expiresIn,
    required this.retryAfter,
    this.devCode,
  });

  final String challengeId;
  final int expiresIn;
  final int retryAfter;
  final String? devCode;

  factory SmsCodeResult.fromJson(Map<String, dynamic> json) => SmsCodeResult(
    challengeId: json['challengeId'] as String? ?? '',
    expiresIn: json['expiresIn'] as int? ?? 0,
    retryAfter: json['retryAfter'] as int? ?? 60,
    devCode: json['devCode'] as String?,
  );
}

class FavoriteItem {
  const FavoriteItem({
    required this.targetType,
    required this.targetId,
    required this.title,
    required this.summary,
    this.coverImage,
    required this.savedAt,
    required this.available,
  });

  final String targetType;
  final String targetId;
  final String title;
  final String summary;
  final String? coverImage;
  final String savedAt;
  final bool available;

  factory FavoriteItem.fromJson(Map<String, dynamic> json) => FavoriteItem(
    targetType: json['targetType'] as String? ?? 'post',
    targetId: json['targetId'] as String? ?? '',
    title: json['title'] as String? ?? '',
    summary: json['summary'] as String? ?? '',
    coverImage: json['coverImage'] as String?,
    savedAt: json['savedAt'] as String? ?? '',
    available: json['available'] as bool? ?? false,
  );
}

class FavoritePage {
  const FavoritePage({
    required this.items,
    this.nextCursor,
    required this.hasMore,
  });

  final List<FavoriteItem> items;
  final String? nextCursor;
  final bool hasMore;

  factory FavoritePage.fromJson(Map<String, dynamic> json) {
    final items = json['items'];
    return FavoritePage(
      items: items is List
          ? items
                .whereType<Map<String, dynamic>>()
                .map(FavoriteItem.fromJson)
                .toList(growable: false)
          : const [],
      nextCursor: json['nextCursor'] as String?,
      hasMore: json['hasMore'] as bool? ?? false,
    );
  }
}

class MyPostPage {
  const MyPostPage({required this.items, this.nextCursor, required this.hasMore});

  final List<PostCard> items;
  final String? nextCursor;
  final bool hasMore;

  factory MyPostPage.fromJson(Map<String, dynamic> json) {
    final items = json['items'];
    return MyPostPage(
      items: items is List
          ? items
                .whereType<Map<String, dynamic>>()
                .map(PostCard.fromJson)
                .toList(growable: false)
          : const [],
      nextCursor: json['nextCursor'] as String?,
      hasMore: json['hasMore'] as bool? ?? false,
    );
  }
}

class AIRecommendation {
  const AIRecommendation({
    required this.targetType,
    required this.targetId,
    required this.title,
    required this.summary,
    required this.coverImage,
    required this.reason,
  });

  final String targetType;
  final String targetId;
  final String title;
  final String summary;
  final String coverImage;
  final String reason;

  factory AIRecommendation.fromJson(Map<String, dynamic> json) =>
      AIRecommendation(
        targetType: json['targetType'] as String? ?? 'recipe',
        targetId: json['targetId'] as String? ?? '',
        title: json['title'] as String? ?? '',
        summary: json['summary'] as String? ?? '',
        coverImage: json['coverImage'] as String? ?? '',
        reason: json['reason'] as String? ?? '',
      );
}

class AIQuota {
  const AIQuota({
    required this.limit,
    required this.used,
    required this.remaining,
  });

  final int limit;
  final int used;
  final int remaining;

  factory AIQuota.fromJson(Map<String, dynamic> json) => AIQuota(
    limit: json['limit'] as int? ?? 0,
    used: json['used'] as int? ?? 0,
    remaining: json['remaining'] as int? ?? 0,
  );
}

class AIChatResult {
  const AIChatResult({
    required this.conversationId,
    required this.origin,
    required this.message,
    required this.recommendations,
    required this.quota,
  });

  final String conversationId;
  final String origin;
  final String message;
  final List<AIRecommendation> recommendations;
  final AIQuota quota;

  factory AIChatResult.fromJson(Map<String, dynamic> json) {
    final recommendations = json['recommendations'];
    final quota = json['quota'];
    return AIChatResult(
      conversationId: json['conversationId'] as String? ?? '',
      origin: json['origin'] as String? ?? '',
      message: json['message'] as String? ?? '',
      recommendations: recommendations is List
          ? recommendations
                .whereType<Map<String, dynamic>>()
                .map(AIRecommendation.fromJson)
                .toList(growable: false)
          : const [],
      quota: quota is Map<String, dynamic>
          ? AIQuota.fromJson(quota)
          : const AIQuota(limit: 0, used: 0, remaining: 0),
    );
  }
}

class PublishResult {
  const PublishResult({
    required this.postId,
    required this.status,
    this.publishedAt,
    required this.reviewRequired,
  });

  final String postId;
  final String status;
  final String? publishedAt;
  final bool reviewRequired;

  factory PublishResult.fromJson(Map<String, dynamic> json) => PublishResult(
    postId: json['postId'] as String? ?? '',
    status: json['status'] as String? ?? '',
    publishedAt: json['publishedAt'] as String?,
    reviewRequired: json['reviewRequired'] as bool? ?? false,
  );
}

class MediaAsset {
  const MediaAsset({required this.assetId, required this.url});

  final String assetId;
  final String url;

  factory MediaAsset.fromJson(Map<String, dynamic> json) => MediaAsset(
    assetId: json['assetId'] as String? ?? '',
    url: json['url'] as String? ?? '',
  );
}

class Coordinates {
  const Coordinates({required this.lat, required this.lng});

  final double lat;
  final double lng;
}

/// 店铺坐标：来自地图选点，比“公开大概位置”精度更高，用于详情页地图与导航。
class StoreLocation {
  const StoreLocation({required this.lat, required this.lng, this.poiId});

  final double lat;
  final double lng;
  final String? poiId;

  factory StoreLocation.fromJson(Map<String, dynamic> json) => StoreLocation(
    lat: (json['lat'] as num?)?.toDouble() ?? 0,
    lng: (json['lng'] as num?)?.toDouble() ?? 0,
    poiId: json['poiId'] as String?,
  );

  Map<String, dynamic> toJson() => {'lat': lat, 'lng': lng, 'poiId': poiId};
}

/// 地图搜索返回的地点（后端代理腾讯地点搜索后的统一结构）。
class Place {
  const Place({
    required this.id,
    required this.name,
    required this.address,
    required this.lat,
    required this.lng,
    this.distanceMeters,
  });

  final String id;
  final String name;
  final String address;
  final double lat;
  final double lng;
  final int? distanceMeters;

  factory Place.fromJson(Map<String, dynamic> json) => Place(
    id: json['id'] as String? ?? '',
    name: json['name'] as String? ?? '',
    address: json['address'] as String? ?? '',
    lat: (json['lat'] as num?)?.toDouble() ?? 0,
    lng: (json['lng'] as num?)?.toDouble() ?? 0,
    distanceMeters: json['distanceMeters'] as int?,
  );
}

/// 草稿里保存的“公开大概位置”，没有 publicConsent（编辑时由前端补 true）。
class SavedLocation {
  const SavedLocation({required this.lat, required this.lng, this.area});

  final double lat;
  final double lng;
  final String? area;

  factory SavedLocation.fromJson(Map<String, dynamic> json) => SavedLocation(
    lat: (json['lat'] as num?)?.toDouble() ?? 0,
    lng: (json['lng'] as num?)?.toDouble() ?? 0,
    area: json['area'] as String?,
  );
}

/// 草稿编辑数据：包含 imageAssetIds 才能在不换图的情况下继续保存。
class DraftDetail {
  const DraftDetail({
    required this.postId,
    required this.title,
    required this.review,
    this.source,
    required this.imageAssetIds,
    required this.images,
    this.authorRecipe,
    this.takeawayStore,
    this.dineInAddress,
    this.avgPrice,
    required this.tasteTags,
    this.location,
    this.storeLocation,
    this.updatedAt,
  });

  final String postId;
  final String title;
  final String review;
  final String? source;
  final List<String> imageAssetIds;
  final List<String> images;
  final AuthorRecipe? authorRecipe;
  final String? takeawayStore;
  final String? dineInAddress;
  final int? avgPrice;
  final List<String> tasteTags;
  final SavedLocation? location;
  final StoreLocation? storeLocation;
  final String? updatedAt;

  factory DraftDetail.fromJson(Map<String, dynamic> json) {
    final imageAssetIds = json['imageAssetIds'];
    final images = json['images'];
    final authorRecipe = json['authorRecipe'];
    final tasteTags = json['tasteTags'];
    final location = json['location'];
    final storeLocation = json['storeLocation'];
    return DraftDetail(
      postId: json['postId'] as String? ?? '',
      title: json['title'] as String? ?? '',
      review: json['review'] as String? ?? '',
      source: json['source'] as String?,
      imageAssetIds: imageAssetIds is List
          ? imageAssetIds.map((item) => item as String).toList(growable: false)
          : const [],
      images: images is List
          ? images.map((item) => item as String).toList(growable: false)
          : const [],
      authorRecipe: authorRecipe is Map<String, dynamic>
          ? AuthorRecipe.fromJson(authorRecipe)
          : null,
      takeawayStore: json['takeawayStore'] as String?,
      dineInAddress: json['dineInAddress'] as String?,
      avgPrice: json['avgPrice'] as int?,
      tasteTags: tasteTags is List
          ? tasteTags.map((item) => item as String).toList(growable: false)
          : const [],
      location: location is Map<String, dynamic>
          ? SavedLocation.fromJson(location)
          : null,
      storeLocation: storeLocation is Map<String, dynamic>
          ? StoreLocation.fromJson(storeLocation)
          : null,
      updatedAt: json['updatedAt'] as String?,
    );
  }
}

/// 草稿保存结果。
class DraftSaveResult {
  const DraftSaveResult({
    required this.postId,
    required this.status,
    this.updatedAt,
  });

  final String postId;
  final String status;
  final String? updatedAt;

  factory DraftSaveResult.fromJson(Map<String, dynamic> json) =>
      DraftSaveResult(
        postId: json['postId'] as String? ?? '',
        status: json['status'] as String? ?? 'draft',
        updatedAt: json['updatedAt'] as String?,
      );
}

/// 删除结果（软删除，只改状态）。
class DeletePostResult {
  const DeletePostResult({
    required this.postId,
    required this.status,
    this.deletedAt,
  });

  final String postId;
  final String status;
  final String? deletedAt;

  factory DeletePostResult.fromJson(Map<String, dynamic> json) =>
      DeletePostResult(
        postId: json['postId'] as String? ?? '',
        status: json['status'] as String? ?? 'deleted',
        deletedAt: json['deletedAt'] as String?,
      );
}
