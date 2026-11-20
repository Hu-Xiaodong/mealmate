import 'package:geolocator/geolocator.dart';

import '../api/models.dart';

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
