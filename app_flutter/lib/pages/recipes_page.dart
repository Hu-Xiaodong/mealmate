import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../core/analytics.dart';
import '../core/format.dart';
import '../theme/app_theme.dart';
import '../widgets/ai_assistant.dart';
import '../widgets/empty_state.dart';
import '../widgets/recipe_card_tile.dart';
import 'recipe_detail_page.dart';

class RecipesPage extends StatefulWidget {
  const RecipesPage({super.key});

  @override
  State<RecipesPage> createState() => _RecipesPageState();
}

class _RecipesPageState extends State<RecipesPage> {
  static const List<SegmentOptionData> _categories = [
    SegmentOptionData('recommended', '推荐'),
    SegmentOptionData('quick', '快手'),
    SegmentOptionData('one_pot', '一锅'),
    SegmentOptionData('few', '少食材'),
  ];

  final ScrollController _scroll = ScrollController();

  List<Recipe> _recipes = const [];
  String _category = 'recommended';
  String? _cursor;
  bool _hasMore = false;
  bool _loading = false;
  bool _loaded = false;

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
    try {
      final page = await apiClient.recipes(
        category: _category,
        cursor: reset ? null : _cursor,
        limit: 20,
      );
      if (!mounted) return;
      setState(() {
        _recipes = reset ? page.items : [..._recipes, ...page.items];
        _cursor = page.nextCursor;
        _hasMore = page.hasMore;
      });
    } on ApiException catch (error) {
      analytics.clientError(module: 'recipe_list', errorCode: error.code);
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

  void _switchCategory(String next) {
    if (_category == next) return;
    setState(() => _category = next);
    _load(reset: true);
  }

  void _open(Recipe recipe) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => RecipeDetailPage(
          recipeId: recipe.id,
          entry: 'recipe_list',
          category: _category,
        ),
      ),
    );
  }

  /// 菜谱列表的 AI 入口：和首页共用同一个面板，但语境换成“帮你挑菜”。
  void _openAi() {
    analytics.trackAiOpen(contextType: 'recipe_list', entry: 'fab');
    showAiChatSheet(context, contextType: 'recipe_list');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        bottom: false,
        child: Stack(
          children: [
            Column(
              children: [
                // 不固定高度：分类按钮的高度由文字和上下内边距自然撑开。
                // 之前写死 48，在字体放大或不同屏幕密度下会把文字上下裁掉。
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.fromLTRB(20, 12, 20, 10),
                  child: Row(
                    children: [
                      for (final item in _categories) ...[
                        _CategoryChip(
                          label: item.label,
                          active: _category == item.code,
                          onTap: () => _switchCategory(item.code),
                        ),
                        if (item != _categories.last) const SizedBox(width: 8),
                      ],
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
                      padding: const EdgeInsets.fromLTRB(16, 4, 16, 88),
                      children: [
                        for (final recipe in _recipes)
                          RecipeCardTile(
                            recipe: recipe,
                            onTap: () => _open(recipe),
                          ),
                        if (_loading && _recipes.isEmpty)
                          const Padding(
                            padding: EdgeInsets.symmetric(vertical: 20),
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
                        else if (_loaded && _recipes.isEmpty)
                          const EmptyState(
                            title: '这个分类还没有菜谱',
                            description: '菜谱需要经过试做和来源核对，我们会慢慢补齐。',
                          )
                        else if (_recipes.isNotEmpty && !_hasMore)
                          const Padding(
                            padding: EdgeInsets.symmetric(vertical: 20),
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
            Positioned.fill(child: DraggableAiFab(onTap: _openAi)),
          ],
        ),
      ),
    );
  }
}

class SegmentOptionData {
  const SegmentOptionData(this.code, this.label);

  final String code;
  final String label;
}

class _CategoryChip extends StatelessWidget {
  const _CategoryChip({
    required this.label,
    required this.active,
    required this.onTap,
  });

  final String label;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 7),
        decoration: BoxDecoration(
          color: active ? AppColors.peach : AppColors.card,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(
            color: active
                ? AppColors.primary.withValues(alpha: 0.35)
                : AppColors.line,
          ),
        ),
        child: Text(
          label,
          maxLines: 1,
          softWrap: false,
          style: TextStyle(
            fontSize: 13,
            fontWeight: active ? FontWeight.w600 : FontWeight.w400,
            color: active ? AppColors.primaryDeep : AppColors.muted,
          ),
        ),
      ),
    );
  }
}
