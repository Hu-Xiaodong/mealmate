import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';

/// 接口根地址，可通过 `--dart-define=API_BASE=...` 覆盖。
const String kApiBase = String.fromEnvironment(
  'API_BASE',
  defaultValue: 'http://127.0.0.1:8000',
);

/// 统一错误：服务端 `{requestId, code, message, data}` 中 code != 0 时抛出。
class ApiException implements Exception {
  const ApiException(this.code, this.message, this.status, [this.data]);

  final Object? code;
  final String message;
  final int status;
  final Object? data;

  @override
  String toString() => message;
}

final ApiClient apiClient = ApiClient();

/// 后端返回 `/media/...` 时补全域名，外链图片原样返回。
String resolveMedia(String? path) {
  if (path == null || path.isEmpty) return '';
  if (path.startsWith('http://') ||
      path.startsWith('https://') ||
      path.startsWith('data:')) {
    return path;
  }
  return '${apiClient.baseUrl}${path.startsWith('/') ? '' : '/'}$path';
}

class ApiClient {
  ApiClient({String baseUrl = kApiBase, http.Client? httpClient})
    : baseUrl = baseUrl.replaceAll(RegExp(r'/+$'), ''),
      _http = httpClient ?? http.Client();

  final String baseUrl;
  final http.Client _http;

  String? token;
  String deviceId = '';

  static const Duration _timeout = Duration(seconds: 15);

  Map<String, String> _headers({bool auth = true}) {
    final headers = <String, String>{'Content-Type': 'application/json'};
    final current = token;
    if (auth && current != null && current.isNotEmpty) {
      headers['Authorization'] = 'Bearer $current';
    }
    if (current == null || current.isEmpty) {
      headers['X-Device-Id'] = deviceId;
    }
    return headers;
  }

  Future<http.Response> _send(Future<http.Response> Function() run) async {
    try {
      return await run().timeout(_timeout);
    } on TimeoutException {
      throw const ApiException('TIMEOUT', '请求超时，请稍后重试', 0);
    } on http.ClientException {
      throw const ApiException('NETWORK_ERROR', '网络连接失败，请检查网络', 0);
    }
  }

  Map<String, dynamic> _decodeEnvelope(http.Response response) {
    Object? decoded;
    try {
      decoded = jsonDecode(utf8.decode(response.bodyBytes));
    } on FormatException {
      throw ApiException(
        'BAD_RESPONSE',
        '服务返回了无法解析的内容',
        response.statusCode,
      );
    }
    if (decoded is! Map<String, dynamic>) {
      throw ApiException('BAD_RESPONSE', '服务返回了无法解析的内容', response.statusCode);
    }
    final code = decoded['code'];
    if (response.statusCode >= 400 || code != 0) {
      throw ApiException(
        code ?? response.statusCode,
        decoded['message'] as String? ?? '请求失败',
        response.statusCode,
        decoded['data'],
      );
    }
    final data = decoded['data'];
    if (data is Map<String, dynamic>) return data;
    return const {};
  }

  Future<Map<String, dynamic>> _request(
    String path, {
    String method = 'GET',
    Object? body,
    bool auth = true,
    Map<String, String>? headers,
    bool expectMap = true,
  }) async {
    final uri = Uri.parse('$baseUrl$path');
    Future<http.Response> run() {
      final requestHeaders = {..._headers(auth: auth), ...?headers};
      switch (method) {
        case 'POST':
          return _http.post(
            uri,
            headers: requestHeaders,
            body: body == null ? null : jsonEncode(body),
          );
        case 'PUT':
          return _http.put(
            uri,
            headers: requestHeaders,
            body: body == null ? null : jsonEncode(body),
          );
        case 'DELETE':
          return _http.delete(uri, headers: requestHeaders);
        default:
          return _http.get(uri, headers: requestHeaders);
      }
    }

    final response = await _send(run);
    if (!expectMap) {
      // 仅用于确认 data 为 null 的成功响应。
      final decoded = jsonDecode(utf8.decode(response.bodyBytes));
      if (decoded is Map<String, dynamic> &&
          response.statusCode < 400 &&
          decoded['code'] == 0) {
        return const {};
      }
      throw ApiException(
        decoded is Map<String, dynamic> ? decoded['code'] : response.statusCode,
        decoded is Map<String, dynamic>
            ? decoded['message'] as String? ?? '请求失败'
            : '请求失败',
        response.statusCode,
        decoded is Map<String, dynamic> ? decoded['data'] : null,
      );
    }
    return _decodeEnvelope(response);
  }

  static String _query(Map<String, Object?> params) {
    final parts = params.entries
        .where((entry) => entry.value != null && entry.value != '')
        .map(
          (entry) =>
              '${Uri.encodeComponent(entry.key)}=${Uri.encodeComponent('${entry.value}')}',
        )
        .toList(growable: false);
    return parts.isEmpty ? '' : '?${parts.join('&')}';
  }

  Future<SmsCodeResult> sendSmsCode(String phone) async {
    final data = await _request(
      '/api/v1/auth/sms-codes',
      method: 'POST',
      body: {'phone': phone, 'purpose': 'login'},
      auth: false,
    );
    return SmsCodeResult.fromJson(data);
  }

  Future<LoginResult> login({
    required String challengeId,
    required String code,
    required bool agreementAccepted,
  }) async {
    final data = await _request(
      '/api/v1/auth/login',
      method: 'POST',
      body: {
        'challengeId': challengeId,
        'code': code,
        'agreementAccepted': agreementAccepted,
      },
      auth: false,
    );
    return LoginResult.fromJson(data);
  }

  Future<void> logout() async {
    await _request('/api/v1/auth/logout', method: 'POST', expectMap: false);
  }

  Future<FeedPage> feed({
    required String filter,
    String? cursor,
    int limit = 10,
    double? lat,
    double? lng,
    int radius = 3000,
  }) async {
    final data = await _request(
      '/api/v1/feed${_query({
        'filter': filter,
        'cursor': cursor,
        'limit': limit,
        'lat': lat,
        'lng': lng,
        'radius': radius,
      })}',
    );
    return FeedPage.fromJson(data);
  }

  Future<RankPage> rank() async {
    final data = await _request('/api/v1/rank/today');
    return RankPage.fromJson(data);
  }

  Future<RecipePage> recipes({
    required String category,
    String? cursor,
    int limit = 20,
  }) async {
    final data = await _request(
      '/api/v1/recipes${_query({
        'category': category,
        'cursor': cursor,
        'limit': limit,
      })}',
    );
    return RecipePage.fromJson(data);
  }

  Future<Recipe> recipe(String id) async {
    final data = await _request('/api/v1/recipes/${Uri.encodeComponent(id)}');
    return Recipe.fromJson(data);
  }

  Future<PostDetail> post(String id) async {
    final data = await _request('/api/v1/posts/${Uri.encodeComponent(id)}');
    return PostDetail.fromJson(data);
  }

  Future<LikeResult> setLike(String postId, bool liked) async {
    final data = await _request(
      '/api/v1/posts/${Uri.encodeComponent(postId)}/like',
      method: 'PUT',
      body: {'liked': liked},
    );
    return LikeResult.fromJson(data);
  }

  Future<FavoriteResult> setFavorite({
    required String targetType,
    required String targetId,
    required bool saved,
  }) async {
    final data = await _request(
      '/api/v1/favorites',
      method: 'PUT',
      body: {
        'targetType': targetType,
        'targetId': targetId,
        'saved': saved,
      },
    );
    return FavoriteResult.fromJson(data);
  }

  Future<MyPostPage> myPosts({String? cursor, int limit = 20}) async {
    final data = await _request(
      '/api/v1/me/posts${_query({'cursor': cursor, 'limit': limit})}',
    );
    return MyPostPage.fromJson(data);
  }

  Future<MyPostPage> myDrafts({String? cursor, int limit = 20}) async {
    final data = await _request(
      '/api/v1/me/drafts${_query({'cursor': cursor, 'limit': limit})}',
    );
    return MyPostPage.fromJson(data);
  }

  Future<DraftDetail> myDraft(String postId) async {
    final data = await _request(
      '/api/v1/me/drafts/${Uri.encodeComponent(postId)}',
    );
    return DraftDetail.fromJson(data);
  }

  Future<FavoritePage> myFavorites({String? cursor, int limit = 20}) async {
    final data = await _request(
      '/api/v1/me/favorites${_query({'cursor': cursor, 'limit': limit})}',
    );
    return FavoritePage.fromJson(data);
  }

  /// 地图是否可用。不可用时前端退化为手动填写店名/地址。
  Future<bool> mapEnabled() async {
    final data = await _request('/api/v1/maps/config');
    return data['enabled'] as bool? ?? false;
  }

  Future<List<Place>> searchPlaces({
    required String keyword,
    double? lat,
    double? lng,
    int limit = 10,
  }) async {
    final data = await _request(
      '/api/v1/maps/places${_query({
        'keyword': keyword,
        'lat': lat,
        'lng': lng,
        'limit': limit,
      })}',
    );
    final items = data['items'];
    return items is List
        ? items
              .whereType<Map<String, dynamic>>()
              .map(Place.fromJson)
              .toList(growable: false)
        : const [];
  }

  /// 拼好静态地图地址，直接交给 `Image.network`，无需下载字节。
  String staticMapUrl({
    required double lat,
    required double lng,
    int zoom = 16,
    int width = 640,
    int height = 320,
  }) {
    return '$baseUrl/api/v1/maps/static${_query({
      'lat': lat,
      'lng': lng,
      'zoom': zoom,
      'width': width,
      'height': height,
    })}';
  }

  Future<DraftSaveResult> createDraft(Map<String, dynamic> payload) async {
    final data = await _request(
      '/api/v1/posts/drafts',
      method: 'POST',
      body: payload,
    );
    return DraftSaveResult.fromJson(data);
  }

  Future<DraftSaveResult> updateDraft(
    String postId,
    Map<String, dynamic> payload,
  ) async {
    final data = await _request(
      '/api/v1/posts/${Uri.encodeComponent(postId)}/draft',
      method: 'PUT',
      body: payload,
    );
    return DraftSaveResult.fromJson(data);
  }

  Future<PublishResult> publishDraft(
    String postId,
    Map<String, dynamic> payload,
  ) async {
    final data = await _request(
      '/api/v1/posts/${Uri.encodeComponent(postId)}/publish',
      method: 'POST',
      body: payload,
    );
    return PublishResult.fromJson(data);
  }

  Future<DeletePostResult> deletePost(String postId) async {
    final data = await _request(
      '/api/v1/posts/${Uri.encodeComponent(postId)}',
      method: 'DELETE',
    );
    return DeletePostResult.fromJson(data);
  }

  Future<PublishResult> createPost(
    Map<String, dynamic> payload,
    String idempotencyKey,
  ) async {
    final data = await _request(
      '/api/v1/posts',
      method: 'POST',
      body: payload,
      auth: true,
      headers: {'Idempotency-Key': idempotencyKey},
    );
    return PublishResult.fromJson(data);
  }

  Future<AIChatResult> aiChat({
    String contextType = 'home',
    String? contextId,
    required String message,
  }) async {
    final data = await _request(
      '/api/v1/ai/chat',
      method: 'POST',
      body: {
        'contextType': contextType,
        'contextId': contextId,
        'message': message,
      },
    );
    return AIChatResult.fromJson(data);
  }

  Future<MediaAsset> uploadImage(String filePath) async {
    final current = token;
    if (current == null || current.isEmpty) {
      throw const ApiException('UNAUTHENTICATED', '请先登录后再上传图片', 401);
    }
    try {
      final request = http.MultipartRequest(
        'POST',
        Uri.parse('$baseUrl/api/v1/media'),
      );
      request.headers['Authorization'] = 'Bearer $current';
      request.files.add(await http.MultipartFile.fromPath('file', filePath));
      final streamed = await _http.send(request).timeout(_timeout);
      final response = await http.Response.fromStream(streamed);
      return MediaAsset.fromJson(_decodeEnvelope(response));
    } on TimeoutException {
      throw const ApiException('TIMEOUT', '图片上传超时，请重试', 0);
    } on http.ClientException {
      throw const ApiException('NETWORK_ERROR', '图片上传失败，请检查网络', 0);
    }
  }
}

class LikeResult {
  const LikeResult({
    required this.postId,
    required this.liked,
    required this.likeCount,
  });

  final String postId;
  final bool liked;
  final int likeCount;

  factory LikeResult.fromJson(Map<String, dynamic> json) => LikeResult(
    postId: json['postId'] as String? ?? '',
    liked: json['liked'] as bool? ?? false,
    likeCount: json['likeCount'] as int? ?? 0,
  );
}

class FavoriteResult {
  const FavoriteResult({required this.saved, this.savedAt});

  final bool saved;
  final String? savedAt;

  factory FavoriteResult.fromJson(Map<String, dynamic> json) =>
      FavoriteResult(
        saved: json['saved'] as bool? ?? false,
        savedAt: json['savedAt'] as String?,
      );
}
