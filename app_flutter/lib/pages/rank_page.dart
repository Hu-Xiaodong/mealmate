import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../core/format.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/common.dart';
import '../widgets/empty_state.dart';
import 'post_detail_page.dart';

class RankPage extends StatefulWidget {
  const RankPage({super.key});

  @override
  State<RankPage> createState() => _RankPageState();
}

class _RankPageState extends State<RankPage> {
  List<RankItem> _items = const [];
  String _statDate = '';
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
      setState(() {
        _items = data.items;
        _statDate = data.statDate;
      });
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
    final subtitle = _statDate.isEmpty
        ? '今日有效赞排序'
        : '$_statDate · 有效赞排序';

    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            AppHeader(title: '热榜', subtitle: subtitle),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 14),
              child: Container(
                padding: const EdgeInsets.fromLTRB(14, 10, 14, 10),
                decoration: BoxDecoration(
                  color: AppColors.peach,
                  borderRadius: BorderRadius.circular(AppRadius.sm),
                ),
                child: const Text(
                  '每天按有效赞数排序，最多 20 条。榜单每天零点重新开始。',
                  style: TextStyle(
                    fontSize: 12,
                    color: AppColors.primaryDeep,
                    height: 1.5,
                  ),
                ),
              ),
            ),
            Expanded(
              child: RefreshIndicator(
                color: AppColors.primary,
                onRefresh: _load,
                child: ListView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
                  children: [
                    for (final item in _items) _RankRow(item: item, onTap: _open),
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
  final ValueChanged<RankItem> onTap;

  @override
  Widget build(BuildContext context) {
    final top = item.rank <= 3;
    final ingredients = item.mainIngredients.take(3).toList(growable: false);
    final cover = resolveMedia(item.post.coverImage);
    final author = item.post.author?.nickname ?? '饭友';

    return GestureDetector(
      onTap: () => onTap(item),
      behavior: HitTestBehavior.opaque,
      child: Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(AppRadius.md),
          boxShadow: const [
            BoxShadow(
              color: Color(0x0D242424),
              blurRadius: 14,
              offset: Offset(0, 4),
            ),
          ],
        ),
        child: Row(
          children: [
            Container(
              width: 28,
              height: 28,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: top ? AppColors.primary : AppColors.bg,
                shape: BoxShape.circle,
              ),
              child: Text(
                '${item.rank}',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                  color: top ? Colors.white : AppColors.muted,
                ),
              ),
            ),
            const SizedBox(width: 12),
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
                    item.post.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                      color: AppColors.text,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: ingredients.isEmpty
                        ? [InfoChip(label: sourceLabel(item.post.source))]
                        : [
                            for (final name in ingredients)
                              InfoChip(label: name),
                          ],
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Text(
                        '♥ ${item.effectiveLikeCount}',
                        style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: AppColors.primary,
                        ),
                      ),
                      const SizedBox(width: 12),
                      Flexible(
                        child: Text(
                          author,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 12,
                            color: AppColors.faint,
                          ),
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
