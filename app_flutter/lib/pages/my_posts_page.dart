import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../core/format.dart';
import '../core/login_gate.dart';
import '../session/session_store.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/empty_state.dart';
import '../widgets/post_card_tile.dart';
import 'post_detail_page.dart';
import 'publish_page.dart';

class MyPostsPage extends StatefulWidget {
  const MyPostsPage({super.key});

  @override
  State<MyPostsPage> createState() => _MyPostsPageState();
}

class _MyPostsPageState extends State<MyPostsPage> {
  final ScrollController _scroll = ScrollController();

  List<PostCard> _posts = const [];
  String? _cursor;
  bool _hasMore = false;
  bool _loading = false;
  bool _loadedOnce = false;

  @override
  void initState() {
    super.initState();
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
      final page = await apiClient.myPosts(
        cursor: reset ? null : _cursor,
        limit: 20,
      );
      if (!mounted) return;
      setState(() {
        _posts = reset ? page.items : [..._posts, ...page.items];
        _cursor = page.nextCursor;
        _hasMore = page.hasMore;
        _loadedOnce = true;
      });
    } on ApiException catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _goPublish() async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(builder: (_) => const PublishPage()),
    );
    if (!mounted) return;
    await _load(reset: true);
  }

  Future<void> _toggleLike(PostCard post) async {
    await requireLogin(
      context,
      action: () async {
        try {
          final result = await apiClient.setLike(post.id, !post.likedByMe);
          if (!mounted) return;
          setState(() {
            post.likedByMe = result.liked;
            post.likeCount = result.likeCount;
          });
        } on ApiException catch (error) {
          if (!mounted) return;
          showError(context, error);
        }
      },
    );
  }

  void _open(PostCard post) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => PostDetailPage(postId: post.id),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            AppHeader(
              title: '我的发布',
              subtitle: '记录每一顿认真吃过的饭',
              showBack: true,
              action: GestureDetector(
                onTap: _goPublish,
                behavior: HitTestBehavior.opaque,
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 16,
                    vertical: 8,
                  ),
                  decoration: BoxDecoration(
                    color: AppColors.peach,
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: const Text(
                    '发布',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.primaryDeep,
                    ),
                  ),
                ),
              ),
            ),
            Expanded(
              child: !sessionStore.isLoggedIn
                  ? SingleChildScrollView(
                      child: EmptyState(
                        title: '登录后查看发布',
                        description: '登录后可以管理自己发布的饭帖和审核状态。',
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
                          for (final post in _posts)
                            PostCardTile(
                              post: post,
                              onTap: () => _open(post),
                              onLike: () => _toggleLike(post),
                            ),
                          if (_loading && _posts.isEmpty)
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
                          else if (_loadedOnce && _posts.isEmpty)
                            EmptyState(
                              title: '还没有发布过',
                              description: '拍下今天的这一餐，第一条饭帖由你开始。',
                              actionText: '去发布',
                              onAction: _goPublish,
                            )
                          else if (_posts.isNotEmpty && !_hasMore)
                            const Padding(
                              padding: EdgeInsets.symmetric(vertical: 18),
                              child: Center(
                                child: Text(
                                  '发布记录都在这里了',
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
}
