import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../core/analytics.dart';
import '../core/format.dart';
import '../core/location.dart';
import '../core/login_gate.dart';
import '../session/session_store.dart';
import '../theme/app_theme.dart';
import '../widgets/ai_assistant.dart';
import '../widgets/empty_state.dart';
import '../widgets/post_grid_tile.dart';
import 'post_detail_page.dart';
import 'publish_page.dart';

class HomePage extends StatefulWidget {
  const HomePage({super.key, this.onAiOpen, this.onAiDragStart});

  /// 由 [MainShell] 统一打开 AI 面板：首页只负责发起，不重复处理埋点。
  final VoidCallback? onAiOpen;

  /// 拖动悬钮时通知外层取消“首次 AI 提示”的等待。
  final VoidCallback? onAiDragStart;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  final ScrollController _scroll = ScrollController();

  List<PostCard> _posts = const [];
  String _filter = 'all';
  String? _cursor;
  bool _hasMore = false;
  bool _loading = false;
  bool _firstLoaded = false;
  Coordinates? _coords;

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
    if (_loading) return;
    setState(() {
      _loading = true;
      if (reset) _cursor = null;
    });

    var effectiveFilter = _filter;
    if (effectiveFilter == 'near' && _coords == null) {
      try {
        final coords = await locateCoarse();
        _coords = coords;
        // 浏览用户可能永远不进发布页，这里顺手保存最近定位：
        // 只写一份、带节流，换来下次定位失败时仍有兜底。
        rememberLocation(coords).ignore();
      } on LocationFailure catch (error) {
        // 当前定位失败时先退到服务端保存的最近定位；
        // 连历史定位也没有，才降级为“全部”并提示原因。
        final history = await _loadRememberedLocation();
        if (history != null) {
          _coords = history;
          if (mounted) showMessage(context, '定位暂不可用，已使用上次的位置');
        } else {
          _filter = 'all';
          _coords = null;
          effectiveFilter = 'all';
          if (mounted) showMessage(context, error.message);
        }
      }
    }

    try {
      final page = await apiClient.feed(
        filter: effectiveFilter,
        cursor: reset ? null : _cursor,
        limit: 10,
        lat: _coords?.lat,
        lng: _coords?.lng,
      );
      if (!mounted) return;
      setState(() {
        _posts = reset ? page.items : [..._posts, ...page.items];
        _cursor = page.nextCursor;
        _hasMore = page.hasMore;
      });
      // 曝光埋点用“首批已加载卡片”近似“至少一半可见 1 秒”：
      // 首屏最多同时看到 6 张，重置加载时各记一次，翻页不重复记。
      if (reset) {
        for (var i = 0; i < _posts.length && i < 6; i++) {
          analytics.track(
            'meal_impression',
            pageName: 'home',
            properties: {
              'postId': _posts[i].id,
              'listType': effectiveFilter == 'near' ? 'nearby' : 'all',
              'position': i + 1,
            },
          );
        }
      }
      if (reset && effectiveFilter == 'near') {
        analytics.track(
          'nearby_result',
          pageName: 'home',
          properties: {
            'permissionState': _coords != null ? 'granted' : 'unavailable',
            'resultCode': 'ok',
            'countBucket': _countBucket(page.items.length),
          },
        );
      }
    } on ApiException catch (error) {
      analytics.clientError(module: 'home_feed', errorCode: error.code);
      if (mounted) showError(context, error);
    } finally {
      if (mounted) {
        setState(() {
          _loading = false;
          _firstLoaded = true;
        });
      }
    }
  }

  /// 读取服务端保存的最近定位；游客或请求失败都按“没有历史定位”处理。
  ///
  /// 这里不展示错误：它只是兜底分支，失败后页面还有“降级为全部”的最终方案，
  /// 再弹一次错误提示只会打扰用户。
  Future<Coordinates?> _loadRememberedLocation() async {
    if (!sessionStore.isLoggedIn) return null;
    try {
      return await apiClient.myLocation();
    } on ApiException {
      return null;
    }
  }

  /// 结果数量分桶，避免把精确数量当成业务指标上报。
  String _countBucket(int count) {
    if (count <= 0) return '0';
    if (count <= 5) return '1-5';
    if (count <= 20) return '6-20';
    return '20+';
  }

  void _switchFilter(String next) {
    if (_filter == next) return;
    setState(() => _filter = next);
    _load(reset: true);
  }

  Future<void> _toggleLike(PostCard post) async {
    await requireLogin(
      context,
      entry: 'home',
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
            pageName: 'home',
            properties: {
              'postId': post.id,
              'desiredState': desired ? 'liked' : 'unliked',
              'resultCode': 'ok',
            },
          );
        } on ApiException catch (error) {
          analytics.track(
            'like_result',
            pageName: 'home',
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

  Future<void> _openPublish() async {
    await requireLogin(
      context,
      entry: 'home',
      pendingAction: 'publish',
      action: () async {
        await Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => const PublishPage(entry: 'home'),
          ),
        );
      },
    );
  }

  void _openPost(PostCard post) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => PostDetailPage(postId: post.id, entry: 'home'),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.card,
      body: SafeArea(
        bottom: false,
        child: Stack(
          children: [
            Column(
              children: [
                Expanded(
                  child: RefreshIndicator(
                    color: AppColors.primary,
                    onRefresh: () => _load(reset: true),
                    child: ListView(
                      controller: _scroll,
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 88),
                      children: [
                        const Text(
                          '看看大家今天吃什么，给晚饭找点灵感。',
                          style: TextStyle(
                            fontSize: 13,
                            color: AppColors.muted,
                          ),
                        ),
                        const SizedBox(height: 12),
                        _filterChips(),
                        const SizedBox(height: 16),
                        ..._feedRows(),
                        if (_loading && _posts.isEmpty)
                          const Padding(
                            padding: EdgeInsets.symmetric(vertical: 16),
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
                        else if (_firstLoaded && _posts.isEmpty)
                          EmptyState(
                            title: '还没有饭帖',
                            description: '拍下你的这一餐，成为第一条分享。',
                            actionText: '去发布',
                            onAction: _openPublish,
                          )
                        else if (_posts.isNotEmpty && !_hasMore)
                          const Padding(
                            padding: EdgeInsets.symmetric(vertical: 16),
                            child: Center(
                              child: Text(
                                '已经到底了',
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
            Positioned.fill(
              child: DraggableAiFab(
                onTap: () {
                  // 打开动作交给 MainShell：它负责埋点和“已用过 AI”标记。
                  if (widget.onAiOpen != null) {
                    widget.onAiOpen!();
                  } else {
                    showAiChatSheet(context);
                  }
                },
                onDragStart: widget.onAiDragStart,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _publishAction() {
    return GestureDetector(
      onTap: _openPublish,
      behavior: HitTestBehavior.opaque,
      child: Container(
        // 与“全部 / 附近”按钮同高、同圆角，放在同一行更像一组控件。
        height: 44,
        padding: const EdgeInsets.symmetric(horizontal: 15),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: AppColors.primary,
          borderRadius: BorderRadius.circular(22),
        ),
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.add, size: 16, color: Colors.white),
            SizedBox(width: 4),
            Text(
              '晒饭',
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w500,
                color: Colors.white,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _filterChips() {
    // 全部、附近与晒饭放在同一行：左侧是筛选，右侧是发布入口。
    return Row(
      children: [
        _filterChip('all', '全部'),
        const SizedBox(width: 8),
        _filterChip('near', '附近'),
        const Spacer(),
        _publishAction(),
      ],
    );
  }

  Widget _filterChip(String value, String label) {
    final selected = _filter == value;
    return GestureDetector(
      onTap: () => _switchFilter(value),
      behavior: HitTestBehavior.opaque,
      child: Container(
        height: 44,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        decoration: BoxDecoration(
          color: selected ? AppColors.peach : AppColors.bg,
          borderRadius: BorderRadius.circular(22),
          border: Border(
            bottom: BorderSide(
              color: selected ? AppColors.primary : Colors.transparent,
              width: 2,
            ),
          ),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              label,
              style: TextStyle(
                fontSize: 13,
                fontWeight: selected ? FontWeight.w500 : FontWeight.w400,
                color: AppColors.text,
              ),
            ),
          ],
        ),
      ),
    );
  }

  List<Widget> _feedRows() {
    final rows = <Widget>[];
    for (var i = 0; i < _posts.length; i += 2) {
      final left = _posts[i];
      final right = i + 1 < _posts.length ? _posts[i + 1] : null;
      rows.add(
        Padding(
          padding: const EdgeInsets.only(bottom: 24),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: PostGridTile(
                  post: left,
                  showDistance: _filter == 'near',
                  onTap: () => _openPost(left),
                  onLike: () => _toggleLike(left),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: right == null
                    ? const SizedBox.shrink()
                    : PostGridTile(
                        post: right,
                        showDistance: _filter == 'near',
                        onTap: () => _openPost(right),
                        onLike: () => _toggleLike(right),
                      ),
              ),
            ],
          ),
        ),
      );
    }
    return rows;
  }
}
