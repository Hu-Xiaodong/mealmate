import 'package:flutter/material.dart';

import '../pages/login_page.dart';
import '../session/session_store.dart';
import 'analytics.dart';

/// 登录拦截：未登录时进入登录页，成功后继续执行原操作一次。
///
/// [entry] 和 [pendingAction] 只用于埋点，用来回答“用户为什么被要求登录”：
/// 是点赞、收藏还是发布触发的。业务逻辑不依赖这两个参数。
Future<bool> requireLogin(
  BuildContext context, {
  String entry = 'unknown',
  String pendingAction = 'unknown',
  Future<void> Function()? action,
}) async {
  if (sessionStore.isLoggedIn) {
    if (action != null) await action();
    return true;
  }
  analytics.track(
    'login_open',
    properties: {'entry': entry, 'pendingAction': pendingAction},
  );
  final startedAt = DateTime.now();
  final result = await Navigator.of(
    context,
  ).push<bool>(MaterialPageRoute(builder: (_) => LoginPage(entry: entry)));
  if (!context.mounted) return false;
  if (result == true && sessionStore.isLoggedIn) {
    // 登录成功后把被拦截的动作真正执行一次，并记录恢复结果。
    if (action != null) {
      analytics.track(
        'pending_action_resumed',
        properties: {
          'pendingAction': pendingAction,
          'resultCode': 'ok',
          'latencyMs': DateTime.now().difference(startedAt).inMilliseconds,
        },
      );
      await action();
    }
    return true;
  }
  // 用户直接返回，不算失败；单独记一条 cancel，避免把取消误判成登录失败。
  analytics.track(
    'login_result',
    properties: {
      'entry': entry,
      'outcome': 'cancel',
      'pendingAction': pendingAction,
      'durationMs': DateTime.now().difference(startedAt).inMilliseconds,
    },
  );
  return false;
}
