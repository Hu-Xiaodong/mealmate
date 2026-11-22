import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../core/format.dart';
import '../core/login_gate.dart';
import '../session/session_store.dart';
import '../theme/app_theme.dart';
import 'favorites_page.dart';
import 'my_posts_page.dart';
import 'publish_page.dart';

class MinePage extends StatelessWidget {
  const MinePage({super.key});

  Future<void> _openProtected(
    BuildContext context,
    WidgetBuilder builder,
  ) async {
    await requireLogin(
      context,
      action: () async {
        await Navigator.of(
          context,
        ).push<void>(MaterialPageRoute(builder: builder));
      },
    );
  }

  Future<void> _logout(BuildContext context) async {
    try {
      await apiClient.logout();
    } on ApiException {
      // 会话可能已失效，仍然清理本地状态。
    }
    await sessionStore.clear();
    if (context.mounted) showMessage(context, '已退出登录');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        bottom: false,
        child: AnimatedBuilder(
          animation: sessionStore,
          builder: (context, _) {
            return Column(
              children: [
                Expanded(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        if (!sessionStore.isLoggedIn)
                          _guestCard(context)
                        else
                          _profileCard(context),
                        _menuCard(context),
                        _aiTipCard(),
                      ],
                    ),
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }

  Widget _guestCard(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(22, 30, 22, 26),
      decoration: _cardDecoration(),
      child: Column(
        children: [
          Container(
            width: 58,
            height: 58,
            alignment: Alignment.center,
            decoration: const BoxDecoration(
              color: AppColors.peach,
              shape: BoxShape.circle,
            ),
            child: const Text(
              '饭',
              style: TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w700,
                color: AppColors.primaryDeep,
              ),
            ),
          ),
          const SizedBox(height: 14),
          const Text(
            '还没有登录',
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: AppColors.text,
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            '登录后可以点赞、收藏，也能把今天的饭发布出来。',
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: 13,
              color: AppColors.muted,
              height: 1.6,
            ),
          ),
          const SizedBox(height: 18),
          GestureDetector(
            onTap: () => requireLogin(context),
            behavior: HitTestBehavior.opaque,
            child: Container(
              padding: const EdgeInsets.symmetric(
                horizontal: 34,
                vertical: 11,
              ),
              decoration: BoxDecoration(
                color: AppColors.primary,
                borderRadius: BorderRadius.circular(999),
                boxShadow: const [
                  BoxShadow(
                    color: Color(0x38CC462C),
                    blurRadius: 18,
                    offset: Offset(0, 8),
                  ),
                ],
              ),
              child: const Text(
                '手机号登录',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _profileCard(BuildContext context) {
    final nickname = sessionStore.profile?.nickname ?? '饭友';
    final initial = nickname.characters.first;

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: _cardDecoration(),
      child: Row(
        children: [
          Container(
            width: 54,
            height: 54,
            alignment: Alignment.center,
            decoration: const BoxDecoration(
              color: AppColors.peach,
              shape: BoxShape.circle,
            ),
            child: Text(
              initial,
              style: const TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w700,
                color: AppColors.primaryDeep,
              ),
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  nickname,
                  style: const TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w700,
                    color: AppColors.text,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  sessionStore.profile?.phoneMasked ?? '',
                  style: const TextStyle(
                    fontSize: 13,
                    color: AppColors.muted,
                  ),
                ),
              ],
            ),
          ),
          GestureDetector(
            onTap: () => _logout(context),
            behavior: HitTestBehavior.opaque,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
              decoration: BoxDecoration(
                border: Border.all(color: AppColors.line),
                borderRadius: BorderRadius.circular(999),
              ),
              child: const Text(
                '退出',
                style: TextStyle(fontSize: 12, color: AppColors.muted),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _menuCard(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(top: 14),
      padding: const EdgeInsets.symmetric(horizontal: 18),
      decoration: _cardDecoration(),
      child: Column(
        children: [
          _menuItem(
            '我的发布',
            () => _openProtected(
              context,
              (_) => const MyPostsPage(),
            ),
          ),
          _divider(),
          _menuItem(
            '我的草稿',
            () => _openProtected(
              context,
              (_) => const MyPostsPage(draftOnly: true),
            ),
          ),
          _divider(),
          _menuItem(
            '我的收藏',
            () => _openProtected(
              context,
              (_) => const FavoritesPage(),
            ),
          ),
          _divider(),
          _menuItem(
            '发布今天的饭',
            () => _openProtected(
              context,
              (_) => const PublishPage(),
            ),
          ),
        ],
      ),
    );
  }

  Widget _menuItem(String label, VoidCallback onTap) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 16),
        child: Row(
          children: [
            Expanded(
              child: Text(
                label,
                style: const TextStyle(fontSize: 15, color: AppColors.text),
              ),
            ),
            const Icon(
              Icons.chevron_right,
              size: 20,
              color: AppColors.faint,
            ),
          ],
        ),
      ),
    );
  }

  Widget _divider() {
    return Container(height: 1, color: AppColors.line);
  }

  Widget _aiTipCard() {
    return Container(
      margin: const EdgeInsets.only(top: 14),
      padding: const EdgeInsets.all(18),
      decoration: _cardDecoration(),
      child: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'AI 每日额度',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: AppColors.text,
            ),
          ),
          SizedBox(height: 6),
          Text(
            '游客每天 5 次问答，登录后每天 20 次。AI 只推荐平台核对过的菜谱，不代替真实烹饪判断。',
            style: TextStyle(
              fontSize: 12,
              color: AppColors.muted,
              height: 1.6,
            ),
          ),
        ],
      ),
    );
  }

  BoxDecoration _cardDecoration() {
    return BoxDecoration(
      color: AppColors.card,
      borderRadius: BorderRadius.circular(AppRadius.lg),
      boxShadow: const [
        BoxShadow(
          color: Color(0x0D242424),
          blurRadius: 18,
          offset: Offset(0, 6),
        ),
      ],
    );
  }
}
