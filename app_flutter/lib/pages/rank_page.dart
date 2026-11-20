import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../core/format.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/empty_state.dart';
import 'post_detail_page.dart';

class RankPage extends StatefulWidget {
  const RankPage({super.key});

  @override
  State<RankPage> createState() => _RankPageState();
}

class _RankPageState extends State<RankPage> {
  List<RankItem> _items = const [];
  bool _loading = false;
  bool _loaded = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final data = await apiClient.rank();
      if (!mounted) return;
      setState(() => _items = data.items);
    } on ApiException catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) {
        setState(() {
          _loading = false;
          _loaded = true;
        });
      }
    }
  }

  void _open(RankItem item) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => PostDetailPage(postId: item.post.id),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.card,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const AppHeader(title: '今日热榜', compact: true),
            Expanded(
              child: RefreshIndicator(
                color: AppColors.primary,
                onRefresh: _load,
                child: ListView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
                  children: [
                    const Text(
                      '今日点赞 TOP20',
                      style: TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w500,
                        color: AppColors.text,
                      ),
                    ),
                    const SizedBox(height: 3),
                    const Text(
                      '今天大家看了最想吃的饭',
                      style: TextStyle(fontSize: 13, color: AppColors.muted),
                    ),
                    const SizedBox(height: 12),
                    for (final item in _items)
                      _RankRow(item: item, onTap: () => _open(item)),
                    if (_loading && _items.isEmpty)
                      const Padding(
                        padding: EdgeInsets.symmetric(vertical: 24),
                        child: Center(
                          child: Text(
                            '正在结算今天的赞…',
                            style: TextStyle(
                              fontSize: 12,
                              color: AppColors.faint,
                            ),
                          ),
                        ),
                      )
                    else if (_loaded && _items.isEmpty)
                      const EmptyState(
                        title: '今天还没有上榜饭帖',
                        description: '去首页给喜欢的饭帖点个赞，榜单会实时更新。',
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

class _RankRow extends StatelessWidget {
  const _RankRow({required this.item, required this.onTap});

  final RankItem item;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final ingredients = item.mainIngredients.take(3).toList(growable: false);
    final cover = resolveMedia(item.post.coverImage);
    final author = item.post.author?.nickname ?? '饭友';

    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 16),
        decoration: const BoxDecoration(
          border: Border(bottom: BorderSide(color: AppColors.line)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            SizedBox(
              width: 88,
              height: 88,
              child: Stack(
                children: [
                  Positioned.fill(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(12),
                      child: cover.isEmpty
                          ? const _ThumbPlaceholder()
                          : Image.network(
                              cover,
                              fit: BoxFit.cover,
                              errorBuilder: (_, _, _) =>
                                  const _ThumbPlaceholder(),
                            ),
                    ),
                  ),
                  Positioned(
                    top: 5,
                    left: 5,
                    child: _RankBadge(rank: item.rank),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    item.post.title,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w500,
                      height: 1.4,
                      color: AppColors.text,
                    ),
                  ),
                  if (ingredients.isNotEmpty) ...[
                    const SizedBox(height: 7),
                    Wrap(
                      spacing: 5,
                      runSpacing: 5,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        if (item.ingredientOrigin == 'platform_reference')
                          const Text(
                            '参考食材',
                            style: TextStyle(
                              fontSize: 11,
                              color: AppColors.muted,
                            ),
                          ),
                        for (final name in ingredients)
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 7,
                              vertical: 2,
                            ),
                            decoration: BoxDecoration(
                              color: AppColors.bg,
                              borderRadius: BorderRadius.circular(5),
                            ),
                            child: Text(
                              name,
                              style: const TextStyle(
                                fontSize: 11,
                                color: AppColors.muted,
                              ),
                            ),
                          ),
                      ],
                    ),
                  ],
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          '$author · ${sourceLabel(item.post.source)}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 12,
                            color: AppColors.muted,
                          ),
                        ),
                      ),
                      const Icon(
                        Icons.favorite,
                        size: 14,
                        color: AppColors.primary,
                      ),
                      const SizedBox(width: 4),
                      Text(
                        '${item.effectiveLikeCount}',
                        style: const TextStyle(
                          fontSize: 13,
                          color: AppColors.primary,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _RankBadge extends StatelessWidget {
  const _RankBadge({required this.rank});

  final int rank;

  @override
  Widget build(BuildContext context) {
    final (background, foreground) = switch (rank) {
      1 => (AppColors.primary, Colors.white),
      2 => (const Color(0xFFE5E8ED), const Color(0xFF35383D)),
      3 => (const Color(0xFFF1CFB7), const Color(0xFF5A3218)),
      _ => (const Color(0xFF4B4E54), Colors.white),
    };

    return Container(
      constraints: const BoxConstraints(minWidth: 24),
      height: 24,
      padding: const EdgeInsets.symmetric(horizontal: 5),
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(6),
        boxShadow: rank == 1
            ? const [
                BoxShadow(
                  color: Color(0x3DCC462C),
                  blurRadius: 5,
                  offset: Offset(0, 2),
                ),
              ]
            : null,
      ),
      child: Text(
        '$rank',
        style: TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w500,
          color: foreground,
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
      color: AppColors.bg,
      alignment: Alignment.center,
      child: const Icon(
        Icons.restaurant,
        size: 22,
        color: AppColors.primaryDeep,
      ),
    );
  }
}
