import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../core/format.dart';
import '../core/location.dart';
import '../core/login_gate.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/empty_state.dart';
import '../widgets/post_card_tile.dart';
import '../widgets/segmented_tabs.dart';
import 'post_detail_page.dart';
import 'publish_page.dart';

class HomePage extends StatefulWidget {
  const HomePage({super.key});

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
  String _businessDate = '';
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
        _coords = await locateCoarse();
      } on LocationFailure catch (error) {
        _filter = 'all';
        _coords = null;
        effectiveFilter = 'all';
        if (mounted) showMessage(context, error.message);
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
        _businessDate = page.businessDate;
        _posts = reset ? page.items : [..._posts, ...page.items];
        _cursor = page.nextCursor;
        _hasMore = page.hasMore;
      });
    } on ApiException catch (error) {
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

  void _switchFilter(String next) {
    if (_filter == next) return;
    setState(() => _filter = next);
    _load(reset: true);
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

  Future<void> _openPublish() async {
    await requireLogin(
      context,
      action: () async {
        await Navigator.of(context).push(
          MaterialPageRoute<void>(builder: (_) => const PublishPage()),
        );
      },
    );
  }

  void _openPost(PostCard post) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => PostDetailPage(postId: post.id),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final subtitle = _businessDate.isEmpty
        ? '今天的饭，都在这里'
        : '今天 · ${dateLabel(_businessDate)}';

    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            AppHeader(
              title: 'MealMate',
              subtitle: subtitle,
              action: GestureDetector(
                onTap: _openPublish,
                behavior: HitTestBehavior.opaque,
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 16,
                    vertical: 8,
                  ),
                  decoration: BoxDecoration(
                    color: AppColors.primary,
                    borderRadius: BorderRadius.circular(999),
                    boxShadow: const [
                      BoxShadow(
                        color: Color(0x38CC462C),
                        blurRadius: 14,
                        offset: Offset(0, 6),
                      ),
                    ],
                  ),
                  child: const Row(
                    children: [
                      Icon(Icons.add, size: 14, color: Colors.white),
                      SizedBox(width: 2),
                      Text(
                        '发布',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 10, 20, 14),
              child: SegmentedTabs<String>(
                selected: _filter,
                onSelected: _switchFilter,
                options: const [
                  SegmentOption('all', '全部'),
                  SegmentOption('near', '附近 3 公里'),
                ],
              ),
            ),
            Expanded(
              child: RefreshIndicator(
                color: AppColors.primary,
                onRefresh: () => _load(reset: true),
                child: ListView(
                  controller: _scroll,
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
                  children: [
                    for (final post in _posts)
                      PostCardTile(
                        post: post,
                        showDistance: _filter == 'near',
                        onTap: () => _openPost(post),
                        onLike: () => _toggleLike(post),
                      ),
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
                        title: '今天还没有饭帖',
                        description: '拍下你的这一餐，成为今天的第一条。',
                        actionText: '去发布',
                        onAction: _openPublish,
                      )
                    else if (_posts.isNotEmpty && !_hasMore)
                      const Padding(
                        padding: EdgeInsets.symmetric(vertical: 16),
                        child: Center(
                          child: Text(
                            '今天就看到这里',
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
