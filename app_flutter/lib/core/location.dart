import 'package:geolocator/geolocator.dart';

import '../api/models.dart';

class LocationFailure implements Exception {
  const LocationFailure(this.message);

  final String message;

  @override
  String toString() => message;
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
