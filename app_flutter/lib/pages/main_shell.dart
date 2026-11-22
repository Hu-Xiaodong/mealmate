import 'dart:async';

import 'package:flutter/material.dart';

import '../core/analytics.dart';
import '../core/location.dart';
import '../theme/app_theme.dart';
import '../widgets/ai_assistant.dart';
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

  static const List<String> _pageNames = ['home', 'rank', 'recipes', 'mine'];

  late final List<Widget> _pages = [
    HomePage(
      onAiOpen: () => _handleAiOpened(contextType: 'home', entry: 'fab'),
      onAiDragStart: () => _dismissHint('dismiss'),
    ),
    const RankPage(),
    const RecipesPage(),
    const MinePage(),
  ];

  /// 首页 AI 轻提示的等待计时器：前台停留 10 秒后才展示。
  Timer? _hintDelayTimer;

  /// 提示自动收起的计时器：展示 4 秒后收起。
  Timer? _hintHideTimer;

  bool _hintVisible = false;

  /// 本次运行是否已经处理过提示（展示过或已用过 AI），避免反复弹。
  bool _hintResolved = false;

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
      analytics.pageView('home', entry: 'launch');
      _scheduleHint();
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // 从后台回到前台时再检查一次：用户可能已经在别处移动了位置。
    // 具体是否真正取定位由节流逻辑决定，频繁切换前后台不会反复请求。
    if (state == AppLifecycleState.resumed) {
      refreshRememberedLocationIfStale().ignore();
      if (_index == 0 && !_hintResolved) _scheduleHint();
    } else if (state == AppLifecycleState.paused) {
      // 切后台要取消等待并收起提示，避免用户回来看到过期的提示。
      _cancelPendingHint();
      _dismissHint('dismiss');
    }
  }

  @override
  void dispose() {
    _hintDelayTimer?.cancel();
    _hintHideTimer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  /// 安排“首次前台停留 10 秒”的 AI 提示。
  void _scheduleHint() {
    _hintDelayTimer?.cancel();
    if (_index != 0 || _hintResolved) return;
    _hintDelayTimer = Timer(const Duration(seconds: 10), () async {
      if (!mounted || _index != 0 || _hintVisible || _hintResolved) return;
      final shouldShow = await analytics.shouldShowAiHint();
      if (!mounted || !shouldShow || _index != 0) return;
      _hintResolved = true;
      // 先记为已展示再真正显示：即使用户马上切页，也不会再次弹。
      await analytics.markAiHintShown();
      if (!mounted) return;
      setState(() => _hintVisible = true);
      analytics.track(
        'ai_hint_impression',
        pageName: 'home',
        properties: {'entry': 'fab', 'delayMs': 10000},
      );
      _hintHideTimer = Timer(const Duration(seconds: 4), () {
        if (mounted && _hintVisible) _dismissHint('timeout');
      });
    });
  }

  void _cancelPendingHint() {
    _hintDelayTimer?.cancel();
    _hintDelayTimer = null;
  }

  /// 收起提示并记录用户行为：主动关闭、点击打开或自动超时。
  void _dismissHint(String action) {
    _hintDelayTimer?.cancel();
    _hintHideTimer?.cancel();
    if (!_hintVisible) return;
    setState(() => _hintVisible = false);
    analytics.track(
      'ai_hint_action',
      pageName: 'home',
      properties: {'action': action},
    );
  }

  /// 三处 AI 入口统一从这里打开：记录 ai_open，并把“已用过 AI”持久化。
  void _handleAiOpened({required String contextType, required String entry}) {
    _dismissHint('open');
    _hintResolved = true;
    analytics.trackAiOpen(contextType: contextType, entry: entry);
    showAiChatSheet(context, contextType: contextType);
  }

  void _switchTab(int next) {
    if (_index == next) return;
    final leavingHome = _index == 0;
    setState(() => _index = next);
    analytics.pageView(_pageNames[next], entry: 'tab');
    if (leavingHome) {
      // 离开首页时取消等待并收起提示，回到首页且未展示过才重新计时。
      _cancelPendingHint();
      _dismissHint('dismiss');
    } else if (next == 0) {
      _scheduleHint();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bg,
      body: Stack(
        children: [
          IndexedStack(index: _index, children: _pages),
          if (_hintVisible)
            Positioned(
              right: 12,
              bottom: 70,
              child: _AiHintBubble(
                onOpen: () => _handleAiOpened(contextType: 'home', entry: 'hint'),
                onDismiss: () => _dismissHint('dismiss'),
              ),
            ),
        ],
      ),
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
                      onTap: () => _switchTab(i),
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

/// 首页首次的 AI 轻提示，只出现一次，点击直接打开 AI 面板。
class _AiHintBubble extends StatelessWidget {
  const _AiHintBubble({required this.onOpen, required this.onDismiss});

  final VoidCallback onOpen;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onOpen,
      behavior: HitTestBehavior.opaque,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 240),
        padding: const EdgeInsets.fromLTRB(12, 8, 4, 8),
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: AppColors.line),
          boxShadow: const [
            BoxShadow(
              color: Color(0x24242424),
              blurRadius: 16,
              offset: Offset(0, 4),
            ),
          ],
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.auto_awesome, size: 15, color: AppColors.primary),
            const SizedBox(width: 6),
            const Flexible(
              child: Text(
                '纠结吃什么？问我。',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w500,
                  color: AppColors.text,
                ),
              ),
            ),
            GestureDetector(
              onTap: onDismiss,
              behavior: HitTestBehavior.opaque,
              child: const SizedBox(
                width: 32,
                height: 32,
                child: Icon(Icons.close, size: 14, color: AppColors.faint),
              ),
            ),
          ],
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
