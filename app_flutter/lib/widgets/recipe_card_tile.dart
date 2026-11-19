import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../core/format.dart';
import '../theme/app_theme.dart';
import 'common.dart';

class RecipeCardTile extends StatelessWidget {
  const RecipeCardTile({super.key, required this.recipe, required this.onTap});

  final Recipe recipe;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final url = resolveMedia(recipe.coverImage);
    final tools = toolLabels(recipe.tools);

    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        margin: const EdgeInsets.only(bottom: 12),
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
            ClipRRect(
              borderRadius: BorderRadius.circular(12),
              child: SizedBox(
                width: 96,
                height: 96,
                child: url.isEmpty
                    ? const _CoverPlaceholder()
                    : Image.network(
                        url,
                        fit: BoxFit.cover,
                        errorBuilder: (_, _, _) => const _CoverPlaceholder(),
                      ),
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    recipe.title,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                      color: AppColors.text,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: [
                      InfoChip(
                        label: '${recipe.totalMinutes} 分钟',
                        highlight: true,
                      ),
                      for (final tool in tools) InfoChip(label: tool),
                      InfoChip(label: '${recipe.servings} 人份'),
                    ],
                  ),
                  if (recipe.preconditions != null &&
                      recipe.preconditions!.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Text(
                      recipe.preconditions!,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.faint,
                      ),
                    ),
                  ],
                ],
              ),
            ),
            if (recipe.savedByMe)
              const Padding(
                padding: EdgeInsets.only(left: 8),
                child: Icon(Icons.star, size: 16, color: AppColors.primary),
              ),
          ],
        ),
      ),
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
        Icons.menu_book_outlined,
        color: AppColors.primaryDeep,
        size: 26,
      ),
    );
  }
}
