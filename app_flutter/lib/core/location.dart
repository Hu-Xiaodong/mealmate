import 'package:geolocator/geolocator.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../session/session_store.dart';

class LocationFailure implements Exception {
  const LocationFailure(this.message);

  final String message;

  @override
  String toString() => message;
}

/// 只在“已经允许定位”的情况下取一次当前位置，绝不弹系统授权框。
///
/// 为什么需要这个函数：
/// 发布页点击“外卖 / 到店”时，要求先判断用户是否已开启定位。
/// 如果这里调用 [locateCoarse]，会在用户没准备好时突然弹出系统权限框，
/// 体验很突兀；所以这里只做“静默检查”，拿不到就返回 null，由页面决定下一步。
Future<Coordinates?> currentLocationIfPermitted() async {
  try {
    // 第一步：系统定位开关是否打开（手机顶部下拉里的“位置信息”）。
    if (!await Geolocator.isLocationServiceEnabled()) return null;
    // 第二步：App 是否已经拿到定位权限。
    final permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied ||
        permission == LocationPermission.deniedForever) {
      return null;
    }
    // 第三步：真正取一次位置。精度用 medium，兼顾速度和准确性；
    // 8 秒超时避免室内定位一直卡住，让页面能及时走“历史定位”兜底。
    final position = await Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.medium,
        timeLimit: Duration(seconds: 8),
      ),
    );
    return Coordinates(lat: position.latitude, lng: position.longitude);
  } catch (_) {
    // 超时、定位服务异常等都按“没拿到当前位置”处理，不在这里打扰用户。
    return null;
  }
}

/// “最近定位”写入节流参数。
///
/// 为什么需要节流：
/// 最近定位只在“手机定位不可用”时用来兜底，不要求秒级精确。
/// 如果每次启动、每次切换附近都写一次，会白白消耗流量、服务端写入和电量，
/// 也放大敏感信息的产生频率。所以只在“位置明显变化”或“间隔足够久”时才写。
const double _locationMinDistanceMeters = 500;
const Duration _locationMinInterval = Duration(hours: 24);

/// 节流记录按账号分开保存：换账号登录时互不影响，也不会读到上一个账号的时间。
String _throttleKey(String field, String accountId) =>
    'mealmate_last_location_${field}_$accountId';

/// 把已经拿到的坐标写入服务端“最近定位”，按距离和时间做节流。
///
/// 调用方不需要等待结果：这是兜底数据，写失败不影响当前操作，下次再补。
Future<void> rememberLocation(Coordinates coords) async {
  // 接口要求登录；游客没有服务端账号，跳过即可。
  if (!sessionStore.isLoggedIn) return;
  final accountId = sessionStore.profile?.accountId;
  final prefs = await SharedPreferences.getInstance();

  if (accountId != null && accountId.isNotEmpty) {
    final savedAt = prefs.getInt(_throttleKey('at', accountId));
    final savedLat = prefs.getDouble(_throttleKey('lat', accountId));
    final savedLng = prefs.getDouble(_throttleKey('lng', accountId));
    if (savedAt != null && savedLat != null && savedLng != null) {
      final age = DateTime.now().difference(
        DateTime.fromMillisecondsSinceEpoch(savedAt),
      );
      final moved = Geolocator.distanceBetween(
        savedLat,
        savedLng,
        coords.lat,
        coords.lng,
      );
      // 既没明显移动、也没超过时间间隔：本次不写，省掉一次无意义的请求。
      if (age < _locationMinInterval && moved < _locationMinDistanceMeters) {
        return;
      }
    }
  }

  try {
    await apiClient.saveMyLocation(lat: coords.lat, lng: coords.lng);
  } on ApiException {
    // 兜底数据写失败就留到下次，不打断用户当前流程，也不弹错误。
    return;
  }

  if (accountId != null && accountId.isNotEmpty) {
    await prefs.setInt(
      _throttleKey('at', accountId),
      DateTime.now().millisecondsSinceEpoch,
    );
    await prefs.setDouble(_throttleKey('lat', accountId), coords.lat);
    await prefs.setDouble(_throttleKey('lng', accountId), coords.lng);
  }
}

/// 冷启动或回到前台时，静默补一次“最近定位”。
///
/// 只有以下条件全部满足才真正取位置：
/// 1. 已登录：接口要求登录，游客没有保存的意义；
/// 2. 距上次成功写入已超过 24 小时：避免每次启停都唤醒定位，省电省流量；
/// 3. 系统定位已开启且 App 已有权限：这里绝不弹系统授权框。
///
/// 这样“只看不发”的用户也会逐步拥有历史定位，供首页“附近”和发布页兜底。
Future<void> refreshRememberedLocationIfStale() async {
  if (!sessionStore.isLoggedIn) return;
  final accountId = sessionStore.profile?.accountId;
  if (accountId == null || accountId.isEmpty) return;
  final prefs = await SharedPreferences.getInstance();
  final savedAt = prefs.getInt(_throttleKey('at', accountId));
  if (savedAt != null) {
    final age = DateTime.now().difference(
      DateTime.fromMillisecondsSinceEpoch(savedAt),
    );
    if (age < _locationMinInterval) return;
  }
  final coords = await currentLocationIfPermitted();
  if (coords == null) return;
  await rememberLocation(coords);
}

/// 请求一次低精度定位；拒绝授权或失败时抛出可展示的 [LocationFailure]。
Future<Coordinates> locateCoarse() async {
  try {
    final serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) {
      throw const LocationFailure('系统定位未开启，无法查看附近');
    }
    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.deniedForever) {
      throw const LocationFailure('位置权限已被拒绝，可在系统设置中开启');
    }
    if (permission == LocationPermission.denied) {
      throw const LocationFailure('允许位置权限后才能查看附近');
    }
    final position = await Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.low,
        timeLimit: Duration(seconds: 10),
      ),
    );
    return Coordinates(lat: position.latitude, lng: position.longitude);
  } on LocationFailure {
    rethrow;
  } catch (_) {
    throw const LocationFailure('未获取到位置，请稍后重试');
  }
}
