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

  /// 会话失效时的回调，由 SessionStore 注入，用于清理本地保存的令牌与资料。
  Future<void> Function()? onSessionExpired;

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
      throw ApiException('BAD_RESPONSE', '服务返回了无法解析的内容', response.statusCode);
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
    try {
      return _parseResponse(response, expectMap: expectMap);
    } on ApiException catch (error) {
      // 本地保存的令牌可能因为过期、被撤销或服务端更换签名密钥而失效。
      // 公开接口（例如首页内容流）允许匿名访问，此时不能把“令牌失效”
      // 当成“没有内容”或直接报错，而应清理本地会话后以游客身份重试一次。
      final expired =
          error.code == 'SESSION_EXPIRED' || error.code == 'UNAUTHORIZED';
      final current = token;
      if (!expired || !auth || current == null || current.isEmpty) {
        rethrow;
      }
      token = null;
      final callback = onSessionExpired;
      if (callback != null) {
        await callback();
      }
      final retry = await _send(run);
      return _parseResponse(retry, expectMap: expectMap);
    }
  }

  Map<String, dynamic> _parseResponse(
    http.Response response, {
    required bool expectMap,
  }) {
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
      '/api/v1/feed${_query({'filter': filter, 'cursor': cursor, 'limit': limit, 'lat': lat, 'lng': lng, 'radius': radius})}',
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
      '/api/v1/recipes${_query({'category': category, 'cursor': cursor, 'limit': limit})}',
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
      body: {'targetType': targetType, 'targetId': targetId, 'saved': saved},
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
      '/api/v1/maps/places${_query({'keyword': keyword, 'lat': lat, 'lng': lng, 'limit': limit})}',
    );
    final items = data['items'];
    return items is List
        ? items
              .whereType<Map<String, dynamic>>()
              .map(Place.fromJson)
              .toList(growable: false)
        : const [];
  }

  /// 口味标签字典。
  ///
  /// 标签由后端数据库维护，客户端不再写死选项：
  /// 产品调整标签时只改数据库，App 不需要发新版本。
  Future<List<String>> tasteTags() async {
    final data = await _request('/api/v1/taste-tags');
    final items = data['items'];
    if (items is! List) return const [];
    return items
        .whereType<Map<String, dynamic>>()
        .map((item) => item['name'] as String? ?? '')
        .where((name) => name.isNotEmpty)
        .toList(growable: false);
  }

  /// 当前账号最近一次保存的定位；没有记录时返回 null。
  Future<Coordinates?> myLocation() async {
    final data = await _request('/api/v1/me/location');
    final location = data['location'];
    if (location is! Map<String, dynamic>) return null;
    final lat = (location['lat'] as num?)?.toDouble();
    final lng = (location['lng'] as num?)?.toDouble();
    if (lat == null || lng == null) return null;
    return Coordinates(lat: lat, lng: lng);
  }

  /// 保存“我最近一次定位”，供下次无法获取手机定位时兜底。
  Future<void> saveMyLocation({
    required double lat,
    required double lng,
    String? area,
  }) async {
    await _request(
      '/api/v1/me/location',
      method: 'PUT',
      body: {'lat': lat, 'lng': lng, 'area': area},
    );
  }

  /// 拼好静态地图地址，直接交给 `Image.network`，无需下载字节。
  String staticMapUrl({
    required double lat,
    required double lng,
    int zoom = 16,
    int width = 640,
    int height = 320,
  }) {
    return '$baseUrl/api/v1/maps/static${_query({'lat': lat, 'lng': lng, 'zoom': zoom, 'width': width, 'height': height})}';
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

  /// 批量上报客户端埋点。
  ///
  /// 这个接口允许游客调用；如果当前已登录，会带上令牌，
  /// 后端据此回填账号归属，事件体里不传任何账号信息。
  Future<void> reportEvents(List<Map<String, Object?>> events) async {
    await _request(
      '/api/v1/analytics/events',
      method: 'POST',
      body: {'events': events},
      expectMap: false,
    );
  }

  Future<AIChatResult> aiChat({
    String contextType = 'home',
    String? contextId,
    required String message,
    List<Map<String, String>> history = const [],
  }) async {
    final data = await _request(
      '/api/v1/ai/chat',
      method: 'POST',
      body: {
        'contextType': contextType,
        'contextId': contextId,
        'message': message,
        if (history.isNotEmpty) 'history': history,
      },
    );
    return AIChatResult.fromJson(data);
  }

  /// 流式问答：服务端按 SSE 逐段推送文字，收到一段就回调一次 [onDelta]。
  ///
  /// 为什么不用普通 `post`：
  /// 普通请求会等服务端把完整响应写完才返回，用户在这段时间里只能看到“思考中”；
  /// SSE 让服务端一边生成一边写，客户端一边读一边展示，首字出现时间明显更短。
  /// 这里仍然使用同一个 `http.Client`，只是换成 `send` 拿到可逐行读取的响应流。
  Future<AIChatResult> aiChatStream({
    String contextType = 'home',
    String? contextId,
    required String message,
    List<Map<String, String>> history = const [],
    required void Function(String delta) onDelta,
  }) async {
    final request = http.Request(
      'POST',
      Uri.parse('$baseUrl/api/v1/ai/chat/stream'),
    );
    request.headers.addAll(_headers());
    request.body = jsonEncode({
      'contextType': contextType,
      'contextId': contextId,
      'message': message,
      if (history.isNotEmpty) 'history': history,
    });

    http.StreamedResponse streamed;
    try {
      // 只限制“多久之内必须开始响应”。本地 14B 模型首次加载可能较慢，
      // 因此比普通接口的 15 秒放宽到 60 秒；开始返回后由下面的循环持续读取。
      streamed = await _http.send(request).timeout(const Duration(seconds: 60));
    } on TimeoutException {
      throw const ApiException('TIMEOUT', 'AI 响应超时，请稍后重试', 0);
    } on http.ClientException {
      throw const ApiException('NETWORK_ERROR', '网络连接失败，请检查网络', 0);
    }

    if (streamed.statusCode >= 400) {
      final text = await streamed.stream.bytesToString();
      try {
        final decoded = jsonDecode(text);
        if (decoded is Map<String, dynamic>) {
          throw ApiException(
            decoded['code'] ?? streamed.statusCode,
            decoded['message'] as String? ?? 'AI 请求失败',
            streamed.statusCode,
            decoded['data'],
          );
        }
      } on FormatException {
        // 不是标准错误信封时，走下面的通用提示。
      }
      throw ApiException(
        'AI_STREAM_FAILED',
        'AI 请求失败（${streamed.statusCode}）',
        streamed.statusCode,
      );
    }

    AIChatResult? result;
    // 服务端每个事件占一行：`data: {"type":"delta","text":"..."}`。
    // 只处理 data 行，空行和注释行（以冒号开头）直接跳过。
    try {
      await for (final line
          in streamed.stream
              .transform(utf8.decoder)
              .transform(const LineSplitter())) {
        if (!line.startsWith('data:')) continue;
        final payloadText = line.substring(5).trim();
        if (payloadText.isEmpty) continue;
        Object? decoded;
        try {
          decoded = jsonDecode(payloadText);
        } on FormatException {
          // 代理或网络异常可能插入非 JSON 行，跳过即可，不影响后续事件。
          continue;
        }
        if (decoded is! Map<String, dynamic>) continue;
        final payload = decoded;
        final type = payload['type'];
        if (type == 'delta') {
          final text = payload['text'];
          if (text is String && text.isNotEmpty) {
            onDelta(text);
          }
        } else if (type == 'done') {
          final data = payload['data'];
          if (data is Map<String, dynamic>) {
            result = AIChatResult.fromJson(data);
          }
        } else if (type == 'error') {
          throw ApiException(
            payload['code'] ?? 'AI_STREAM_ERROR',
            payload['message'] as String? ?? 'AI 回答失败',
            0,
          );
        }
      }
    } on http.ClientException {
      throw const ApiException('NETWORK_ERROR', '网络连接中断，请重试', 0);
    } on TimeoutException {
      throw const ApiException('TIMEOUT', 'AI 响应超时，请重试', 0);
    }

    if (result == null) {
      throw const ApiException('AI_STREAM_INCOMPLETE', 'AI 回答不完整，请重试', 0);
    }
    return result;
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

  factory FavoriteResult.fromJson(Map<String, dynamic> json) => FavoriteResult(
    saved: json['saved'] as bool? ?? false,
    savedAt: json['savedAt'] as String?,
  );
}
