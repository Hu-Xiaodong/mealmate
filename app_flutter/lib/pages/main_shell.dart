import 'package:flutter/material.dart';

import '../core/location.dart';
import '../theme/app_theme.dart';
import 'home_page.dart';
import 'mine_page.dart';
import 'rank_page.dart';
import 'recipes_page.dart';

class MainShell extends StatefulWidget {
  const MainShell({super.key});

  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> with WidgetsBindingObserver {
  int _index = 0;

  static const List<Widget> _pages = [
    HomePage(),
    RankPage(),
    RecipesPage(),
    MinePage(),
  ];

  static const List<_NavData> _tabs = [
    _NavData('首页', Icons.home_outlined, Icons.home),
    _NavData(
      '热榜',
      Icons.local_fire_department_outlined,
      Icons.local_fire_department,
    ),
    _NavData('菜谱', Icons.menu_book_outlined, Icons.menu_book),
    _NavData('我的', Icons.person_outline, Icons.person),
  ];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // 冷启动后静默补一次最近定位：只针对“已登录 + 已授权 + 超过 24 小时”，
    // 不会弹权限框，也不会阻塞首页加载。
    WidgetsBinding.instance.addPostFrameCallback((_) {
      refreshRememberedLocationIfStale().ignore();
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // 从后台回到前台时再检查一次：用户可能已经在别处移动了位置。
    // 具体是否真正取定位由节流逻辑决定，频繁切换前后台不会反复请求。
    if (state == AppLifecycleState.resumed) {
      refreshRememberedLocationIfStale().ignore();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bg,
      body: IndexedStack(index: _index, children: _pages),
      bottomNavigationBar: Container(
        decoration: const BoxDecoration(
          color: AppColors.card,
          border: Border(top: BorderSide(color: AppColors.line)),
        ),
        child: SafeArea(
          top: false,
          child: SizedBox(
            height: 58,
            child: Row(
              children: [
                for (var i = 0; i < _tabs.length; i++)
                  Expanded(
                    child: GestureDetector(
                      onTap: () => setState(() => _index = i),
                      behavior: HitTestBehavior.opaque,
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(
                            _index == i ? _tabs[i].activeIcon : _tabs[i].icon,
                            size: 22,
                            color: _index == i
                                ? AppColors.primary
                                : AppColors.muted,
                          ),
                          const SizedBox(height: 3),
                          Text(
                            _tabs[i].label,
                            style: TextStyle(
                              fontSize: 11,
                              fontWeight: _index == i
                                  ? FontWeight.w600
                                  : FontWeight.w400,
                              color: _index == i
                                  ? AppColors.primary
                                  : AppColors.muted,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _NavData {
  const _NavData(this.label, this.icon, this.activeIcon);

  final String label;
  final IconData icon;
  final IconData activeIcon;
}
