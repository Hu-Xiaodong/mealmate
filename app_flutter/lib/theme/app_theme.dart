import 'package:flutter/material.dart';

/// 与小程序 `App.vue` 对齐的设计令牌。
abstract final class AppColors {
  static const primary = Color(0xFFCC462C);
  static const primaryDeep = Color(0xFFB33226);
  static const peach = Color(0xFFFFF0EB);
  static const text = Color(0xFF242424);
  static const muted = Color(0xFF666666);
  static const faint = Color(0xFF999999);
  static const line = Color(0xFFECECEE);
  static const bg = Color(0xFFF6F7F8);
  static const card = Color(0xFFFFFFFF);
  static const success = Color(0xFF3D7D52);
  static const danger = Color(0xFFB33226);
}

abstract final class AppRadius {
  static const lg = 20.0;
  static const md = 14.0;
  static const sm = 10.0;
}

ThemeData buildAppTheme() {
  final scheme = ColorScheme.fromSeed(seedColor: AppColors.primary).copyWith(
    primary: AppColors.primary,
    onPrimary: Colors.white,
    secondary: AppColors.primaryDeep,
    onSecondary: Colors.white,
    surface: AppColors.card,
    onSurface: AppColors.text,
    error: AppColors.danger,
  );

  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: AppColors.bg,
    splashFactory: InkSparkle.splashFactory,
    textTheme: const TextTheme(
      bodyMedium: TextStyle(color: AppColors.text, fontSize: 15, height: 1.5),
      bodySmall: TextStyle(color: AppColors.muted, fontSize: 12, height: 1.5),
    ),
    snackBarTheme: const SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: Color(0xF2242424),
      contentTextStyle: TextStyle(color: Colors.white, fontSize: 13),
    ),
    dividerColor: AppColors.line,
  );
}
