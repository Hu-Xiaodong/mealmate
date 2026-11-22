import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/api_client.dart';
import '../api/models.dart';

/// 会话与设备标识，token/资料持久化到 SharedPreferences。
class SessionStore extends ChangeNotifier {
  SessionStore(this.api);

  static const _tokenKey = 'mealmate_token';
  static const _profileKey = 'mealmate_profile';
  static const _deviceKey = 'mealmate_device_id';

  final ApiClient api;

  String? _token;
  Profile? _profile;

  bool get isLoggedIn => _token != null && _token!.isNotEmpty;
  Profile? get profile => _profile;

  Future<void> bootstrap() async {
    final prefs = await SharedPreferences.getInstance();
    _token = prefs.getString(_tokenKey);
    final rawProfile = prefs.getString(_profileKey);
    if (rawProfile != null && rawProfile.isNotEmpty) {
      try {
        final decoded = jsonDecode(rawProfile);
        if (decoded is Map<String, dynamic>) {
          _profile = Profile.fromJson(decoded);
        }
      } on FormatException {
        _profile = null;
      }
    }
    var deviceId = prefs.getString(_deviceKey);
    if (deviceId == null || deviceId.isEmpty) {
      deviceId =
          'dev-${DateTime.now().millisecondsSinceEpoch}-${_randomToken(8)}';
      await prefs.setString(_deviceKey, deviceId);
    }
    api.deviceId = deviceId;
    api.token = _token;
    // 服务端判定令牌失效时，接口层会回调这里清理本地会话，
    // 避免“我的”页面仍显示已登录、但所有请求都被拒绝。
    api.onSessionExpired = clear;
  }

  Future<void> apply(LoginResult result) async {
    _token = result.token;
    _profile = result.profile;
    api.token = result.token;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenKey, result.token);
    await prefs.setString(_profileKey, jsonEncode(result.profile.toJson()));
  }

  Future<void> clear() async {
    _token = null;
    _profile = null;
    api.token = null;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_tokenKey);
    await prefs.remove(_profileKey);
  }

  static String _randomToken(int length) {
    const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
    final random = Random();
    return List.generate(length, (_) => chars[random.nextInt(chars.length)]
        ).join();
  }
}

final SessionStore sessionStore = SessionStore(apiClient);
