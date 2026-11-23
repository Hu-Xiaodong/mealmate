import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../core/analytics.dart';
import '../core/format.dart';
import '../core/login_gate.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/common.dart';
import '../widgets/empty_state.dart';

class RecipeDetailPage extends StatefulWidget {
  const RecipeDetailPage({
    super.key,
    required this.recipeId,
    this.entry = 'unknown',
    this.category,
  });

  final String recipeId;

  /// 从哪个入口打开：列表、饭帖详情、AI 推荐或收藏，用于埋点区分意图。
  final String entry;

  /// 菜谱列表当前分类，只用于埋点，不影响详情内容。
  final String? category;

  @override
  State<RecipeDetailPage> createState() => _RecipeDetailPageState();
}

class _RecipeDetailPageState extends State<RecipeDetailPage> {
  Recipe? _recipe;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    analytics.pageView(
      'recipe_detail',
      entry: widget.entry,
      targetType: 'recipe',
      targetId: widget.recipeId,
    );
    analytics.track(
      'recipe_open',
      pageName: 'recipe_detail',
      properties: {
        'recipeId': widget.recipeId,
        'entry': widget.entry,
        if (widget.category != null) 'category': widget.category,
      },
    );
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final data = await apiClient.recipe(widget.recipeId);
      if (!mounted) return;
      setState(() => _recipe = data);
    } on ApiException catch (error) {
      analytics.clientError(module: 'recipe_detail', errorCode: error.code);
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _toggleSave() async {
    final recipe = _recipe;
    if (recipe == null) return;
    await requireLogin(
      context,
      entry: 'recipe_detail',
      pendingAction: 'favorite',
      action: () async {
        final desired = !recipe.savedByMe;
        try {
          final result = await apiClient.setFavorite(
            targetType: 'recipe',
            targetId: recipe.id,
            saved: desired,
          );
          if (!mounted) return;
          setState(() => recipe.savedByMe = result.saved);
          showMessage(context, result.saved ? '已收藏菜谱' : '已取消收藏');
          analytics.track(
            'favorite_result',
            pageName: 'recipe_detail',
            properties: {
              'targetType': 'recipe',
              'targetId': recipe.id,
              'desiredState': desired ? 'saved' : 'unsaved',
              'resultCode': 'ok',
            },
          );
        } on ApiException catch (error) {
          analytics.track(
            'favorite_result',
            pageName: 'recipe_detail',
            properties: {
              'targetType': 'recipe',
              'targetId': recipe.id,
              'desiredState': desired ? 'saved' : 'unsaved',
              'resultCode': '${error.code}',
            },
          );
          if (!mounted) return;
          showError(context, error);
        }
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final recipe = _recipe;
    final timeLabel = recipe?.totalMinutes == null
        ? '耗时未标注'
        : '${recipe!.totalMinutes} 分钟';
    final subtitle = recipe == null ? '' : '$timeLabel · ${recipe.servings} 人份';

    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            AppHeader(subtitle: subtitle, showBack: true),
            Expanded(
              child: _loading && recipe == null
                  ? const Center(
                      child: CircularProgressIndicator(
                        color: AppColors.primary,
                      ),
                    )
                  : recipe == null
                  ? const EmptyState(
                      title: '这道菜谱看不到',
                      description: '可能已经下架，去看看其他快手菜。',
                    )
                  : _content(recipe),
            ),
          ],
        ),
      ),
      bottomNavigationBar: recipe == null ? null : _buildBar(recipe),
    );
  }

  Widget _content(Recipe recipe) {
    final cover = resolveMedia(recipe.coverImage);
    final tools = toolLabels(recipe.tools);

    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(AppRadius.lg),
            child: SizedBox(
              height: 280,
              child: cover.isEmpty
                  ? const ColoredBox(color: AppColors.peach)
                  : Image.network(
                      cover,
                      fit: BoxFit.cover,
                      errorBuilder: (_, _, _) => const ColoredBox(
                        color: AppColors.peach,
                        child: Icon(
                          Icons.menu_book_outlined,
                          size: 34,
                          color: AppColors.primaryDeep,
                        ),
                      ),
                    ),
            ),
          ),
          SectionCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  recipe.title,
                  style: const TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.w700,
                    color: AppColors.text,
                  ),
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    if (recipe.totalMinutes != null)
                      InfoChip(
                        label: '${recipe.totalMinutes!} 分钟',
                        highlight: true,
                      ),
                    for (final tool in tools) InfoChip(label: tool),
                    InfoChip(label: '${recipe.servings} 人份'),
                  ],
                ),
                if (recipe.preconditions != null &&
                    recipe.preconditions!.isNotEmpty)
                  Container(
                    margin: const EdgeInsets.only(top: 14),
                    padding: const EdgeInsets.only(top: 14),
                    decoration: const BoxDecoration(
                      border: Border(top: BorderSide(color: AppColors.line)),
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const SizedBox(
                          width: 42,
                          child: Text(
                            '前提',
                            style: TextStyle(
                              fontSize: 13,
                              color: AppColors.faint,
                            ),
                          ),
                        ),
                        Expanded(
                          child: Text(
                            recipe.preconditions!,
                            style: const TextStyle(
                              fontSize: 13,
                              color: AppColors.muted,
                              height: 1.6,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
          SectionCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '食材',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: AppColors.primaryDeep,
                  ),
                ),
                const SizedBox(height: 10),
                for (var i = 0; i < recipe.ingredients.length; i++)
                  _ingredientRow(
                    recipe.ingredients[i],
                    isLast: i == recipe.ingredients.length - 1,
                  ),
              ],
            ),
          ),
          SectionCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '步骤',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: AppColors.primaryDeep,
                  ),
                ),
                const SizedBox(height: 10),
                for (var i = 0; i < recipe.steps.length; i++)
                  _stepRow(i + 1, recipe.steps[i]),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(6, 14, 6, 0),
            child: Text(
              '内容来源：'
              '${recipe.contentOrigin == 'platform' ? '平台试做菜谱' : recipe.contentOrigin}'
              ' · '
              '${recipe.validationStatus == 'tested' ? '已试做核对' : recipe.validationStatus}',
              style: const TextStyle(
                fontSize: 11,
                color: AppColors.faint,
                height: 1.6,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _ingredientRow(Ingredient item, {required bool isLast}) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 9),
      decoration: BoxDecoration(
        border: isLast
            ? null
            : const Border(bottom: BorderSide(color: AppColors.line)),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              item.name,
              style: const TextStyle(fontSize: 14, color: AppColors.text),
            ),
          ),
          Text(
            item.amount,
            style: const TextStyle(fontSize: 13, color: AppColors.muted),
          ),
        ],
      ),
    );
  }

  Widget _stepRow(int index, String text) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 7),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 20,
            height: 20,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: AppColors.peach,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Text(
              '$index',
              style: const TextStyle(
                fontSize: 12,
                color: AppColors.primaryDeep,
              ),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(
                fontSize: 14,
                height: 1.6,
                color: AppColors.text,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildBar(Recipe recipe) {
    final saved = recipe.savedByMe;
    return Container(
      decoration: const BoxDecoration(
        color: Color(0xF5FFFFFF),
        border: Border(top: BorderSide(color: AppColors.line)),
      ),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
          child: GestureDetector(
            onTap: _toggleSave,
            behavior: HitTestBehavior.opaque,
            child: Container(
              padding: const EdgeInsets.symmetric(vertical: 12),
              decoration: BoxDecoration(
                color: saved ? AppColors.peach : AppColors.primary,
                borderRadius: BorderRadius.circular(999),
                border: saved
                    ? Border.all(
                        color: AppColors.primary.withValues(alpha: 0.35),
                      )
                    : null,
              ),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(
                    saved ? Icons.star : Icons.star_border,
                    size: 18,
                    color: saved ? AppColors.primaryDeep : Colors.white,
                  ),
                  const SizedBox(width: 8),
                  Text(
                    saved ? '已收藏' : '收藏这道菜',
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: saved ? AppColors.primaryDeep : Colors.white,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
