import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../core/analytics.dart';
import '../core/format.dart';
import '../core/login_gate.dart';
import '../session/session_store.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/empty_state.dart';
import 'post_detail_page.dart';
import 'recipe_detail_page.dart';

class FavoritesPage extends StatefulWidget {
  const FavoritesPage({super.key});

  @override
  State<FavoritesPage> createState() => _FavoritesPageState();
}

class _FavoritesPageState extends State<FavoritesPage> {
  final ScrollController _scroll = ScrollController();

  List<FavoriteItem> _items = const [];
  String? _cursor;
  bool _hasMore = false;
  bool _loading = false;
  bool _loadedOnce = false;

  @override
  void initState() {
    super.initState();
    analytics.pageView('favorites', entry: 'mine');
    _scroll.addListener(_onScroll);
    _load(reset: true);
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (!_hasMore || _loading || !_scroll.hasClients) return;
    if (_scroll.position.pixels >= _scroll.position.maxScrollExtent - 200) {
      _load(reset: false);
    }
  }

  Future<void> _load({required bool reset}) async {
    if (_loading || !sessionStore.isLoggedIn) return;
    setState(() {
      _loading = true;
      if (reset) _cursor = null;
    });
    try {
      final page = await apiClient.myFavorites(
        cursor: reset ? null : _cursor,
        limit: 20,
      );
      if (!mounted) return;
      setState(() {
        _items = reset ? page.items : [..._items, ...page.items];
        _cursor = page.nextCursor;
        _hasMore = page.hasMore;
        _loadedOnce = true;
      });
    } on ApiException catch (error) {
      analytics.clientError(module: 'favorites', errorCode: error.code);
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _open(FavoriteItem item) {
    if (!item.available) {
      showMessage(context, '这条内容已下架或被作者删除');
      return;
    }
    final route = item.targetType == 'post'
        ? MaterialPageRoute<void>(
            builder: (_) => PostDetailPage(
              postId: item.targetId,
              entry: 'favorites',
            ),
          )
        : MaterialPageRoute<void>(
            builder: (_) => RecipeDetailPage(
              recipeId: item.targetId,
              entry: 'favorites',
            ),
          );
    Navigator.of(context).push(route);
  }

  Future<void> _remove(FavoriteItem item) async {
    try {
      await apiClient.setFavorite(
        targetType: item.targetType,
        targetId: item.targetId,
        saved: false,
      );
      if (!mounted) return;
      setState(() {
        _items = _items
            .where(
              (row) =>
                  !(row.targetType == item.targetType &&
                      row.targetId == item.targetId),
            )
            .toList(growable: false);
      });
      showMessage(context, '已取消收藏');
      analytics.track(
        'favorite_result',
        pageName: 'favorites',
        properties: {
          'targetType': item.targetType,
          'targetId': item.targetId,
          'desiredState': 'unsaved',
          'resultCode': 'ok',
        },
      );
    } on ApiException catch (error) {
      analytics.track(
        'favorite_result',
        pageName: 'favorites',
        properties: {
          'targetType': item.targetType,
          'targetId': item.targetId,
          'desiredState': 'unsaved',
          'resultCode': '${error.code}',
        },
      );
      if (mounted) showError(context, error);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const AppHeader(showBack: true),
            Expanded(
              child: !sessionStore.isLoggedIn
                  ? SingleChildScrollView(
                      child: EmptyState(
                        title: '登录后查看收藏',
                        description: '收藏的饭帖和菜谱会保存在账号里，换设备也能看到。',
                        actionText: '手机号登录',
                        onAction: () => requireLogin(context),
                      ),
                    )
                  : RefreshIndicator(
                      color: AppColors.primary,
                      onRefresh: () => _load(reset: true),
                      child: ListView(
                        controller: _scroll,
                        physics: const AlwaysScrollableScrollPhysics(),
                        padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
                        children: [
                          for (final item in _items) _row(item),
                          if (_loading && _items.isEmpty)
                            const Padding(
                              padding: EdgeInsets.symmetric(vertical: 18),
                              child: Center(
                                child: Text(
                                  '加载中…',
                                  style: TextStyle(
                                    fontSize: 12,
                                    color: AppColors.faint,
                                  ),
                                ),
                              ),
                            )
                          else if (_loadedOnce && _items.isEmpty)
                            const EmptyState(
                              title: '还没有收藏',
                              description: '在饭帖或菜谱详情页点收藏，就会出现在这里。',
                            )
                          else if (_items.isNotEmpty && !_hasMore)
                            const Padding(
                              padding: EdgeInsets.symmetric(vertical: 18),
                              child: Center(
                                child: Text(
                                  '收藏都在这里了',
                                  style: TextStyle(
                                    fontSize: 12,
                                    color: AppColors.faint,
                                  ),
                                ),
                              ),
                            ),
                        ],
                      ),
                    ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _row(FavoriteItem item) {
    final cover = resolveMedia(item.coverImage);
    final savedDate = item.savedAt.length >= 10
        ? item.savedAt.substring(0, 10)
        : item.savedAt;

    return GestureDetector(
      onTap: () => _open(item),
      behavior: HitTestBehavior.opaque,
      child: Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          boxShadow: const [
            BoxShadow(
              color: Color(0x0D242424),
              blurRadius: 18,
              offset: Offset(0, 6),
            ),
          ],
        ),
        child: Row(
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(12),
              child: SizedBox(
                width: 88,
                height: 88,
                child: cover.isEmpty
                    ? const _ThumbPlaceholder()
                    : Image.network(
                        cover,
                        fit: BoxFit.cover,
                        errorBuilder: (_, _, _) => const _ThumbPlaceholder(),
                      ),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    item.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      color: item.available
                          ? AppColors.text
                          : AppColors.faint,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    item.summary,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 12,
                      color: AppColors.muted,
                      height: 1.5,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '${item.targetType == 'post' ? '饭帖' : '菜谱'} · '
                    '${dateLabel(savedDate)}',
                    style: const TextStyle(
                      fontSize: 11,
                      color: AppColors.faint,
                    ),
                  ),
                ],
              ),
            ),
            GestureDetector(
              onTap: () => _remove(item),
              behavior: HitTestBehavior.opaque,
              child: Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 6,
                ),
                decoration: BoxDecoration(
                  border: Border.all(color: AppColors.line),
                  borderRadius: BorderRadius.circular(999),
                ),
                child: const Text(
                  '取消',
                  style: TextStyle(fontSize: 12, color: AppColors.muted),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ThumbPlaceholder extends StatelessWidget {
  const _ThumbPlaceholder();

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.peach,
      alignment: Alignment.center,
      child: const Icon(
        Icons.restaurant,
        size: 22,
        color: AppColors.primaryDeep,
      ),
    );
  }
}
