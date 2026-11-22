import 'package:flutter/material.dart';

import 'core/analytics.dart';
import 'pages/main_shell.dart';
import 'session/session_store.dart';
import 'theme/app_theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await sessionStore.bootstrap();
  // 埋点要在第一帧之前就绪：首页首次曝光和 AI 提示都要用到。
  await analytics.bootstrap();
  runApp(const MealApp());
}

class MealApp extends StatelessWidget {
  const MealApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'MealMate',
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      home: const MainShell(),
    );
  }
}
