import 'package:flutter/material.dart';

import '../pages/login_page.dart';
import '../session/session_store.dart';

/// 登录拦截：未登录时进入登录页，成功后继续执行原操作一次。
Future<bool> requireLogin(
  BuildContext context, {
  Future<void> Function()? action,
}) async {
  if (sessionStore.isLoggedIn) {
    if (action != null) await action();
    return true;
  }
  final result = await Navigator.of(
    context,
  ).push<bool>(MaterialPageRoute(builder: (_) => const LoginPage()));
  if (!context.mounted) return false;
  if (result == true && sessionStore.isLoggedIn) {
    if (action != null) await action();
    return true;
  }
  return false;
}
