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
import '../widgets/post_card_tile.dart';
import 'post_detail_page.dart';
import 'publish_page.dart';

/// 我的发布 / 我的草稿共用的列表页。
///
/// [draftOnly] 为 true 时只请求草稿箱，反之只请求已发布内容；
/// 两个入口在“我的”页里拆成独立菜单，页面内不再提供页签切换。
class MyPostsPage extends StatefulWidget {
  const MyPostsPage({super.key, this.draftOnly = false});

  final bool draftOnly;

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
  int _requestId = 0;

  @override
  void initState() {
    super.initState();
    analytics.pageView(
      widget.draftOnly ? 'drafts' : 'my_posts',
      entry: 'mine',
    );
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
    if (!reset && _loading) return;
    if (!sessionStore.isLoggedIn) return;
    final requestId = ++_requestId;
    setState(() {
      _loading = true;
      if (reset) _cursor = null;
    });
    try {
      final page = widget.draftOnly
          ? await apiClient.myDrafts(cursor: reset ? null : _cursor, limit: 20)
          : await apiClient.myPosts(cursor: reset ? null : _cursor, limit: 20);
      if (!mounted || requestId != _requestId) return;
      setState(() {
        _posts = reset ? page.items : [..._posts, ...page.items];
        _cursor = page.nextCursor;
        _hasMore = page.hasMore;
        _loadedOnce = true;
      });
    } on ApiException catch (error) {
      if (mounted && requestId == _requestId) showError(context, error);
    } finally {
      if (mounted && requestId == _requestId) {
        setState(() => _loading = false);
      }
    }
  }

  Future<void> _goPublish() async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => const PublishPage(entry: 'my_posts'),
      ),
    );
    if (!mounted) return;
    await _load(reset: true);
  }

  Future<void> _openDraft(PostCard draft) async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => PublishPage(draftId: draft.id, entry: 'my_posts'),
      ),
    );
    if (!mounted) return;
    await _load(reset: true);
  }

  Future<void> _toggleLike(PostCard post) async {
    await requireLogin(
      context,
      entry: 'my_posts',
      pendingAction: 'like',
      action: () async {
        final desired = !post.likedByMe;
        try {
          final result = await apiClient.setLike(post.id, desired);
          if (!mounted) return;
          setState(() {
            post.likedByMe = result.liked;
            post.likeCount = result.likeCount;
          });
          analytics.track(
            'like_result',
            pageName: 'my_posts',
            properties: {
              'postId': post.id,
              'desiredState': desired ? 'liked' : 'unliked',
              'resultCode': 'ok',
            },
          );
        } on ApiException catch (error) {
          analytics.track(
            'like_result',
            pageName: 'my_posts',
            properties: {
              'postId': post.id,
              'desiredState': desired ? 'liked' : 'unliked',
              'resultCode': '${error.code}',
            },
          );
          if (!mounted) return;
          showError(context, error);
        }
      },
    );
  }

  void _open(PostCard post) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => PostDetailPage(postId: post.id, entry: 'my_posts'),
      ),
    );
  }

  Future<void> _delete(PostCard post) async {
    final isDraft = widget.draftOnly;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AppColors.card,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.lg),
        ),
        title: Text(isDraft ? '删除这条草稿？' : '删除这条饭帖？'),
        content: Text(
          isDraft ? '删除后草稿箱里不再显示，且无法恢复。' : '删除后其他人将看不到这条饭帖。',
          style: const TextStyle(fontSize: 13, color: AppColors.muted),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text(
              '取消',
              style: TextStyle(color: AppColors.muted),
            ),
          ),
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text(
              '删除',
              style: TextStyle(color: AppColors.danger),
            ),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      await apiClient.deletePost(post.id);
      if (!mounted) return;
      setState(() => _posts = _posts.where((item) => item.id != post.id).toList());
      showMessage(context, isDraft ? '草稿已删除' : '已删除');
    } on ApiException catch (error) {
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
            AppHeader(
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
                    '去发布',
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
                        title: widget.draftOnly ? '登录后查看草稿' : '登录后查看发布',
                        description: widget.draftOnly
                            ? '登录后可以继续编辑存下的草稿。'
                            : '登录后可以管理自己发布的饭帖和审核状态。',
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
                        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
                        children: [
                          for (final post in _posts)
                            if (widget.draftOnly)
                              _DraftTile(
                                draft: post,
                                onTap: () => _openDraft(post),
                                onDelete: () => _delete(post),
                              )
                            else
                              PostCardTile(
                                post: post,
                                onTap: () => _open(post),
                                onLike: () => _toggleLike(post),
                                onDelete: () => _delete(post),
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
                            widget.draftOnly
                                ? EmptyState(
                                    title: '还没有草稿',
                                    description: '在发布页点「存草稿」，先放这里，想好了再发。',
                                    actionText: '去发布',
                                    onAction: _goPublish,
                                  )
                                : EmptyState(
                                    title: '还没有发布过',
                                    description: '拍下今天的这一餐，第一条饭帖由你开始。',
                                    actionText: '去发布',
                                    onAction: _goPublish,
                                  )
                          else if (_posts.isNotEmpty && !_hasMore)
                            Padding(
                              padding: const EdgeInsets.symmetric(vertical: 18),
                              child: Center(
                                child: Text(
                                  widget.draftOnly
                                      ? '草稿都在这里了'
                                      : '发布记录都在这里了',
                                  style: const TextStyle(
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

/// 草稿卡片：标题可空、封面可空，并展示最近更新时间。
class _DraftTile extends StatelessWidget {
  const _DraftTile({
    required this.draft,
    required this.onTap,
    required this.onDelete,
  });

  final PostCard draft;
  final VoidCallback onTap;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final title = draft.title.trim().isEmpty ? '未命名草稿' : draft.title;
    final cover = resolveMedia(draft.coverImage);
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(AppRadius.md),
        boxShadow: const [
          BoxShadow(
            color: Color(0x0F242424),
            blurRadius: 14,
            offset: Offset(0, 4),
          ),
        ],
      ),
      clipBehavior: Clip.antiAlias,
      child: GestureDetector(
        onTap: onTap,
        behavior: HitTestBehavior.opaque,
        child: Row(
          children: [
            SizedBox(
              width: 96,
              height: 96,
              child: cover.isEmpty
                  ? Container(
                      color: AppColors.peach,
                      alignment: Alignment.center,
                      child: const Icon(
                        Icons.description_outlined,
                        color: AppColors.primaryDeep,
                        size: 26,
                      ),
                    )
                  : Image.network(
                      cover,
                      fit: BoxFit.cover,
                      errorBuilder: (_, _, _) => Container(
                        color: AppColors.peach,
                        alignment: Alignment.center,
                        child: const Icon(
                          Icons.description_outlined,
                          color: AppColors.primaryDeep,
                          size: 26,
                        ),
                      ),
                    ),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(12, 12, 4, 12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                        color: AppColors.text,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      draft.review.trim().isEmpty ? '草稿' : draft.review,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.muted,
                        height: 1.5,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      _updatedLabel(draft.updatedAt),
                      style: const TextStyle(
                        fontSize: 11,
                        color: AppColors.faint,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            GestureDetector(
              onTap: onDelete,
              behavior: HitTestBehavior.opaque,
              child: const Padding(
                padding: EdgeInsets.symmetric(horizontal: 10, vertical: 16),
                child: Icon(
                  Icons.delete_outline,
                  size: 18,
                  color: AppColors.faint,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  static String _updatedLabel(String? iso) {
    if (iso == null || iso.isEmpty) return '';
    final parsed = DateTime.tryParse(iso);
    if (parsed == null) return '';
    final local = parsed.toLocal();
    final hour = local.hour.toString().padLeft(2, '0');
    final minute = local.minute.toString().padLeft(2, '0');
    return '更新于 ${local.month}月${local.day}日 $hour:$minute';
  }
}
