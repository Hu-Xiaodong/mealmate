import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../core/format.dart';
import '../theme/app_theme.dart';

/// 首页双列瀑布卡：按原型稿的「图 + 标题 + 两行评价 + 作者/赞」结构展示。
class PostGridTile extends StatelessWidget {
  const PostGridTile({
    super.key,
    required this.post,
    required this.onTap,
    this.onLike,
    this.showDistance = false,
  });

  final PostCard post;
  final VoidCallback onTap;
  final VoidCallback? onLike;
  final bool showDistance;

  @override
  Widget build(BuildContext context) {
    final author = post.author?.nickname ?? '饭友';
    final distance = distanceLabel(post.distanceMeters);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        GestureDetector(
          onTap: onTap,
          behavior: HitTestBehavior.opaque,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              AspectRatio(
                aspectRatio: 4 / 5,
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(12),
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      _Cover(path: post.coverImage),
                      Positioned(
                        top: 8,
                        left: 8,
                        child: _Tag(label: sourceLabel(post.source)),
                      ),
                      if (post.imageCount > 1)
                        Positioned(
                          right: 7,
                          bottom: 7,
                          child: _Tag(label: '${post.imageCount}张', pill: true),
                        ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 9),
              Text(
                post.title,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w500,
                  height: 1.35,
                  color: AppColors.text,
                ),
              ),
              const SizedBox(height: 3),
              Text(
                post.review,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 13,
                  height: 1.5,
                  color: AppColors.muted,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 5),
        Row(
          children: [
            Expanded(
              child: Text(
                showDistance && distance.isNotEmpty
                    ? '$author · $distance'
                    : author,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 12, color: AppColors.muted),
              ),
            ),
            GestureDetector(
              onTap: onLike,
              behavior: HitTestBehavior.opaque,
              child: Padding(
                padding: const EdgeInsets.only(left: 6, top: 4, bottom: 4),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      post.likedByMe ? Icons.favorite : Icons.favorite_border,
                      size: 15,
                      color: post.likedByMe
                          ? AppColors.primary
                          : AppColors.muted,
                    ),
                    const SizedBox(width: 4),
                    Text(
                      '${post.likeCount}',
                      style: TextStyle(
                        fontSize: 13,
                        color: post.likedByMe
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
      ],
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
      color: AppColors.bg,
      alignment: Alignment.center,
      child: const Icon(
        Icons.restaurant,
        size: 26,
        color: AppColors.primaryDeep,
      ),
    );
  }
}

class _Tag extends StatelessWidget {
  const _Tag({required this.label, this.pill = false});

  final String label;
  final bool pill;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.symmetric(horizontal: pill ? 7 : 8, vertical: 2),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(pill ? 12 : 6),
      ),
      child: Text(
        label,
        style: const TextStyle(
          fontSize: 11,
          height: 1.4,
          color: AppColors.text,
        ),
      ),
    );
  }
}
