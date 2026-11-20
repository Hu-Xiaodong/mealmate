import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../core/format.dart';
import '../theme/app_theme.dart';

/// 首页 / 我的发布使用的饭帖大图卡。
class PostCardTile extends StatelessWidget {
  const PostCardTile({
    super.key,
    required this.post,
    required this.onTap,
    this.onLike,
    this.onDelete,
    this.showDistance = false,
  });

  final PostCard post;
  final VoidCallback onTap;
  final VoidCallback? onLike;
  final VoidCallback? onDelete;
  final bool showDistance;

  @override
  Widget build(BuildContext context) {
    final distance = distanceLabel(post.distanceMeters);
    final authorInitial = (post.author?.nickname ?? '饭').characters.first;

    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        boxShadow: const [
          BoxShadow(
            color: Color(0x0F242424),
            blurRadius: 18,
            offset: Offset(0, 6),
          ),
        ],
      ),
      clipBehavior: Clip.antiAlias,
      child: GestureDetector(
        onTap: onTap,
        behavior: HitTestBehavior.opaque,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SizedBox(
              height: 290,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  _Cover(path: post.coverImage),
                  Positioned(
                    top: 14,
                    left: 14,
                    child: Row(
                      children: [
                        _Badge(
                          label: sourceLabel(post.source),
                          background: AppColors.primary.withValues(alpha: 0.92),
                        ),
                        if (showDistance && distance.isNotEmpty) ...[
                          const SizedBox(width: 6),
                          _Badge(
                            label: distance,
                            background: Colors.white.withValues(alpha: 0.9),
                            foreground: AppColors.primaryDeep,
                          ),
                        ],
                        if (post.pendingReview) ...[
                          const SizedBox(width: 6),
                          _Badge(
                            label: '审核中',
                            background: AppColors.success.withValues(alpha: 0.9),
                          ),
                        ],
                      ],
                    ),
                  ),
                  if (onDelete != null)
                    Positioned(
                      top: 12,
                      right: 12,
                      child: GestureDetector(
                        onTap: onDelete,
                        behavior: HitTestBehavior.opaque,
                        child: Container(
                          padding: const EdgeInsets.all(6),
                          decoration: BoxDecoration(
                            color: Colors.black.withValues(alpha: 0.4),
                            shape: BoxShape.circle,
                          ),
                          child: const Icon(
                            Icons.delete_outline,
                            size: 16,
                            color: Colors.white,
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    post.title,
                    style: const TextStyle(
                      fontSize: 19,
                      fontWeight: FontWeight.w700,
                      color: AppColors.text,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    post.review,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 14,
                      color: AppColors.muted,
                      height: 1.55,
                    ),
                  ),
                  const SizedBox(height: 14),
                  Row(
                    children: [
                      Container(
                        width: 26,
                        height: 26,
                        alignment: Alignment.center,
                        decoration: const BoxDecoration(
                          color: AppColors.peach,
                          shape: BoxShape.circle,
                        ),
                        child: Text(
                          authorInitial,
                          style: const TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                            color: AppColors.primaryDeep,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(
                        post.author?.nickname ?? '饭友',
                        style: const TextStyle(
                          fontSize: 13,
                          color: AppColors.text,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(
                        timeLabel(post.publishedAt),
                        style: const TextStyle(
                          fontSize: 12,
                          color: AppColors.faint,
                        ),
                      ),
                      const Spacer(),
                      GestureDetector(
                        onTap: onLike,
                        behavior: HitTestBehavior.opaque,
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 9,
                            vertical: 4,
                          ),
                          decoration: BoxDecoration(
                            color: AppColors.bg,
                            borderRadius: BorderRadius.circular(999),
                          ),
                          child: Row(
                            children: [
                              Icon(
                                post.likedByMe
                                    ? Icons.favorite
                                    : Icons.favorite_border,
                                size: 16,
                                color: post.likedByMe
                                    ? AppColors.primary
                                    : AppColors.muted,
                              ),
                              const SizedBox(width: 4),
                              Text(
                                '${post.likeCount}',
                                style: const TextStyle(
                                  fontSize: 12,
                                  color: AppColors.muted,
                                ),
                              ),
                            ],
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

class _Cover extends StatelessWidget {
  const _Cover({this.path});

  final String? path;

  @override
  Widget build(BuildContext context) {
    final url = resolveMedia(path);
    if (url.isEmpty) return const _CoverPlaceholder();
    return Image.network(
      url,
      fit: BoxFit.cover,
      errorBuilder: (_, _, _) => const _CoverPlaceholder(),
    );
  }
}

class _CoverPlaceholder extends StatelessWidget {
  const _CoverPlaceholder();

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.peach,
      alignment: Alignment.center,
      child: const Icon(
        Icons.restaurant,
        color: AppColors.primaryDeep,
        size: 34,
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  const _Badge({
    required this.label,
    required this.background,
    this.foreground = Colors.white,
  });

  final String label;
  final Color background;
  final Color foreground;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 11,
          height: 1.4,
          color: foreground,
        ),
      ),
    );
  }
}
