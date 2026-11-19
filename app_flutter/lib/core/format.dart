import 'package:flutter/material.dart';

import '../api/api_client.dart';

const Map<String, String> kSourceLabels = {
  'self': '自己做',
  'takeaway': '外卖',
  'dine_in': '到店',
};

const Map<String, String> kToolLabels = {
  'wok': '炒锅',
  'pot': '炖锅',
  'microwave': '微波炉',
  'rice_cooker': '电饭煲',
  'steamer': '蒸锅',
};

String sourceLabel(String source) => kSourceLabels[source] ?? '其他';

List<String> toolLabels(List<String> codes) =>
    codes.map((code) => kToolLabels[code] ?? code).toList(growable: false);

String timeLabel(String? iso) {
  if (iso == null || iso.isEmpty) return '';
  final parsed = DateTime.tryParse(iso);
  if (parsed == null) return '';
  final local = parsed.toLocal();
  final hour = local.hour.toString().padLeft(2, '0');
  final minute = local.minute.toString().padLeft(2, '0');
  return '$hour:$minute';
}

String distanceLabel(int? meters) {
  if (meters == null) return '';
  if (meters <= 30) return '就在附近';
  if (meters < 1000) return '$meters 米';
  return '${(meters / 1000).toStringAsFixed(1)} 公里';
}

String dateLabel(String date) {
  final parts = date.split('-');
  if (parts.length < 3) return '';
  final month = int.tryParse(parts[1]);
  final day = int.tryParse(parts[2]);
  if (month == null || day == null) return '';
  return '$month月$day日';
}

void showMessage(BuildContext context, String message) {
  final messenger = ScaffoldMessenger.of(context);
  messenger.hideCurrentSnackBar();
  messenger.showSnackBar(
    SnackBar(content: Text(message), duration: const Duration(seconds: 2)),
  );
}

void showError(
  BuildContext context,
  Object error, [
  String fallback = '操作失败，请稍后再试',
]) {
  final message = error is ApiException ? error.message : fallback;
  showMessage(context, message.isEmpty ? fallback : message);
}
