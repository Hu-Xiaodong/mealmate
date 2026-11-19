import 'package:flutter/material.dart';

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

class _MainShellState extends State<MainShell> {
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
