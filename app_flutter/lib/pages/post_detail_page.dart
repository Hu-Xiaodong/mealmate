import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../core/format.dart';
import '../core/login_gate.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/common.dart';
import '../widgets/empty_state.dart';
import 'recipe_detail_page.dart';

class PostDetailPage extends StatefulWidget {
  const PostDetailPage({super.key, required this.postId});

  final String postId;

  @override
  State<PostDetailPage> createState() => _PostDetailPageState();
}

class _PostDetailPageState extends State<PostDetailPage> {
  PostDetail? _detail;
  bool _loading = true;
  bool _aiOpen = false;
  bool _aiSending = false;
  AIChatResult? _aiResult;
  int _galleryIndex = 0;
  final TextEditingController _aiController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _aiController.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final data = await apiClient.post(widget.postId);
      if (!mounted) return;
      setState(() => _detail = data);
    } on ApiException catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _toggleLike() async {
    final detail = _detail;
    if (detail == null) return;
    await requireLogin(
      context,
      action: () async {
        try {
          final result = await apiClient.setLike(detail.id, !detail.likedByMe);
          if (!mounted) return;
          setState(() {
            detail.likedByMe = result.liked;
            detail.likeCount = result.likeCount;
          });
        } on ApiException catch (error) {
          if (!mounted) return;
          showError(context, error);
        }
      },
    );
  }

  Future<void> _toggleSave() async {
    final detail = _detail;
    if (detail == null) return;
    await requireLogin(
      context,
      action: () async {
        try {
          final result = await apiClient.setFavorite(
            targetType: 'post',
            targetId: detail.id,
            saved: !detail.savedByMe,
          );
          if (!mounted) return;
          setState(() => detail.savedByMe = result.saved);
          showMessage(context, result.saved ? '已收藏' : '已取消收藏');
        } on ApiException catch (error) {
          if (!mounted) return;
          showError(context, error);
        }
      },
    );
  }

  Future<void> _sendAi() async {
    final detail = _detail;
    final message = _aiController.text.trim();
    if (detail == null || message.isEmpty || _aiSending) return;
    setState(() => _aiSending = true);
    try {
      final result = await apiClient.aiChat(
        contextType: 'post',
        contextId: detail.id,
        message: message,
      );
      if (!mounted) return;
      setState(() => _aiResult = result);
    } on ApiException catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _aiSending = false);
    }
  }

  void _openRecipe(String id) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(builder: (_) => RecipeDetailPage(recipeId: id)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final detail = _detail;

    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            AppHeader(
              subtitle: detail == null ? '' : timeLabel(detail.publishedAt),
              showBack: true,
            ),
            Expanded(
              child: _loading && detail == null
                  ? const Center(
                      child: CircularProgressIndicator(
                        color: AppColors.primary,
                      ),
                    )
                  : detail == null
                  ? const EmptyState(
                      title: '这条饭帖看不到',
                      description: '可能已被作者删除或还未通过审核。',
                    )
                  : _content(detail),
            ),
          ],
        ),
      ),
      bottomNavigationBar: detail == null ? null : _buildBar(detail),
    );
  }

  Widget _content(PostDetail detail) {
    final ingredientLines = _ingredientLines(detail);
    final stepLines = _stepLines(detail);
    final recipeTitle = _recipeTitle(detail);

    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (detail.images.isNotEmpty) _gallery(detail.images),
          SectionCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Text(
                        detail.title,
                        style: const TextStyle(
                          fontSize: 22,
                          fontWeight: FontWeight.w700,
                          color: AppColors.text,
                        ),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 4,
                      ),
                      decoration: BoxDecoration(
                        color: AppColors.peach,
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: Text(
                        sourceLabel(detail.source),
                        style: const TextStyle(
                          fontSize: 11,
                          color: AppColors.primaryDeep,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                Text(
                  detail.review,
                  style: const TextStyle(
                    fontSize: 15,
                    color: AppColors.muted,
                    height: 1.7,
                  ),
                ),
                if (detail.avgPrice != null || detail.tasteTags.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      if (detail.avgPrice != null)
                        InfoChip(
                          label: '人均 ¥${detail.avgPrice}',
                          highlight: true,
                        ),
                      for (final tag in detail.tasteTags) InfoChip(label: tag),
                    ],
                  ),
                ],
                const SizedBox(height: 16),
                Row(
                  children: [
                    Container(
                      width: 30,
                      height: 30,
                      alignment: Alignment.center,
                      decoration: const BoxDecoration(
                        color: AppColors.peach,
                        shape: BoxShape.circle,
                      ),
                      child: Text(
                        (detail.author?.nickname ?? '饭').characters.first,
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: AppColors.primaryDeep,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      detail.author?.nickname ?? '饭友',
                      style: const TextStyle(fontSize: 13),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      timeLabel(detail.publishedAt),
                      style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.faint,
                      ),
                    ),
                  ],
                ),
                if (detail.takeawayStore != null)
                  _infoRow('外卖店家', detail.takeawayStore!),
                if (detail.dineInAddress != null)
                  _infoRow('到店地址', detail.dineInAddress!),
                if (detail.coarseArea != null)
                  _infoRow('附近', detail.coarseArea!),
              ],
            ),
          ),
          if (detail.storeLocation != null) _storeCard(detail),
          if (ingredientLines.isNotEmpty || stepLines.isNotEmpty)
            SectionCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          recipeTitle,
                          style: const TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w700,
                            color: AppColors.primaryDeep,
                          ),
                        ),
                      ),
                      if (detail.recipe != null && detail.authorRecipe == null)
                        GestureDetector(
                          onTap: () => _openRecipe(detail.recipe!.id),
                          child: const Text(
                            '完整菜谱 ›',
                            style: TextStyle(
                              fontSize: 12,
                              color: AppColors.primary,
                            ),
                          ),
                        ),
                    ],
                  ),
                  if (ingredientLines.isNotEmpty) ...[
                    const SizedBox(height: 14),
                    const _SectionLabel('食材'),
                    const SizedBox(height: 8),
                    for (final line in ingredientLines) _ingredientRow(line),
                  ],
                  if (stepLines.isNotEmpty) ...[
                    const SizedBox(height: 14),
                    const _SectionLabel('步骤'),
                    const SizedBox(height: 8),
                    for (var i = 0; i < stepLines.length; i++)
                      _stepRow(i + 1, stepLines[i]),
                  ],
                ],
              ),
            )
          else
            const SectionCard(
              child: Text(
                '这条饭帖没有可核实的做法，AI 也不会凭图片补出一套菜谱。',
                style: TextStyle(
                  fontSize: 13,
                  color: AppColors.muted,
                  height: 1.6,
                ),
              ),
            ),
          SectionCard(child: _aiPanel()),
        ],
      ),
    );
  }

  String _storeName(PostDetail detail) {
    final takeaway = detail.takeawayStore?.trim() ?? '';
    if (takeaway.isNotEmpty) return takeaway;
    final dineIn = detail.dineInAddress?.trim() ?? '';
    if (dineIn.isNotEmpty) return dineIn;
    return detail.title;
  }

  Future<void> _openMap(PostDetail detail) async {
    final store = detail.storeLocation;
    if (store == null) return;
    final name = Uri.encodeComponent(_storeName(detail));
    final address = detail.dineInAddress?.trim() ?? '';
    final addr = Uri.encodeComponent(address.isEmpty ? _storeName(detail) : address);
    // 腾讯地图统一资源标识符：优先唤起已安装的腾讯地图应用，未安装时退回网页。
    // 坐标顺序是“纬度,经度”，与高德的“经度,纬度”相反；
    // coord、title、addr 三个属性都是腾讯要求必填的，referer 填应用名称。
    final uri = Uri.parse(
      'https://apis.map.qq.com/uri/v1/marker'
      '?marker=coord:${store.lat},${store.lng};title:$name;addr:$addr'
      '&referer=mealmate',
    );
    try {
      final opened = await launchUrl(uri, mode: LaunchMode.externalApplication);
      if (!opened && mounted) showMessage(context, '未找到可打开地图的应用');
    } catch (_) {
      if (mounted) showMessage(context, '未找到可打开地图的应用');
    }
  }

  Widget _storeCard(PostDetail detail) {
    final store = detail.storeLocation!;
    return SectionCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '店铺位置',
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w700,
              color: AppColors.text,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            _storeName(detail),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 12, color: AppColors.muted),
          ),
          const SizedBox(height: 10),
          ClipRRect(
            borderRadius: BorderRadius.circular(AppRadius.sm),
            child: AspectRatio(
              aspectRatio: 2,
              child: Image.network(
                apiClient.staticMapUrl(lat: store.lat, lng: store.lng),
                fit: BoxFit.cover,
                errorBuilder: (_, _, _) => Container(
                  color: AppColors.peach,
                  alignment: Alignment.center,
                  child: const Text(
                    '地图加载失败，不影响查看饭帖',
                    style: TextStyle(fontSize: 12, color: AppColors.muted),
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(height: 10),
          GestureDetector(
            onTap: () => _openMap(detail),
            behavior: HitTestBehavior.opaque,
            child: Container(
              padding: const EdgeInsets.symmetric(vertical: 11),
              decoration: BoxDecoration(
                color: AppColors.primary,
                borderRadius: BorderRadius.circular(999),
              ),
              child: const Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.navigation_outlined, size: 16, color: Colors.white),
                  SizedBox(width: 6),
                  Text(
                    '打开地图导航',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: Colors.white,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _gallery(List<String> images) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(AppRadius.lg),
      child: SizedBox(
        height: 360,
        child: Stack(
          fit: StackFit.expand,
          children: [
            PageView.builder(
              itemCount: images.length,
              onPageChanged: (index) => setState(() => _galleryIndex = index),
              itemBuilder: (context, index) {
                final url = resolveMedia(images[index]);
                return url.isEmpty
                    ? const ColoredBox(color: AppColors.peach)
                    : Image.network(
                        url,
                        fit: BoxFit.cover,
                        errorBuilder: (_, _, _) => const ColoredBox(
                          color: AppColors.peach,
                          child: Icon(
                            Icons.restaurant,
                            color: AppColors.primaryDeep,
                            size: 34,
                          ),
                        ),
                      );
              },
            ),
            if (images.length > 1)
              Positioned(
                top: 12,
                right: 12,
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: Colors.black.withValues(alpha: 0.4),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(
                    '${_galleryIndex + 1}/${images.length}',
                    style: const TextStyle(fontSize: 11, color: Colors.white),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _aiPanel() {
    final result = _aiResult;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        GestureDetector(
          onTap: () => setState(() => _aiOpen = !_aiOpen),
          behavior: HitTestBehavior.opaque,
          child: Row(
            children: [
              const Expanded(
                child: Text(
                  '问问 AI',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: AppColors.text,
                  ),
                ),
              ),
              Text(
                _aiOpen ? '收起' : '展开',
                style: const TextStyle(fontSize: 12, color: AppColors.faint),
              ),
            ],
          ),
        ),
        const SizedBox(height: 6),
        const Text(
          '结合这条饭帖帮你再想想，只推荐平台核对过的菜谱。',
          style: TextStyle(
            fontSize: 12,
            color: AppColors.muted,
            height: 1.5,
          ),
        ),
        if (_aiOpen) ...[
          const SizedBox(height: 14),
          TextField(
            controller: _aiController,
            maxLength: 200,
            maxLines: 3,
            style: const TextStyle(fontSize: 14, color: AppColors.text),
            decoration: InputDecoration(
              filled: true,
              fillColor: AppColors.bg,
              hintText: '例如：只有 15 分钟，还能加点什么？',
              hintStyle: const TextStyle(
                fontSize: 13,
                color: AppColors.faint,
              ),
              contentPadding: const EdgeInsets.all(12),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(AppRadius.sm),
                borderSide: BorderSide.none,
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(AppRadius.sm),
                borderSide: BorderSide.none,
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(AppRadius.sm),
                borderSide: const BorderSide(
                  color: AppColors.primary,
                  width: 1.2,
                ),
              ),
            ),
          ),
          Align(
            alignment: Alignment.centerRight,
            child: PillButton(
              label: _aiSending ? '思考中…' : '发送',
              busy: _aiSending,
              small: true,
              onTap: _sendAi,
            ),
          ),
          if (result != null) ...[
            const SizedBox(height: 14),
            Container(height: 1, color: AppColors.line),
            const SizedBox(height: 14),
            Text(
              result.message,
              style: const TextStyle(
                fontSize: 13,
                color: AppColors.muted,
                height: 1.7,
              ),
            ),
            const SizedBox(height: 10),
            for (final item in result.recommendations) ...[
              GestureDetector(
                onTap: () => _openRecipe(item.targetId),
                behavior: HitTestBehavior.opaque,
                child: Container(
                  padding: const EdgeInsets.all(8),
                  margin: const EdgeInsets.only(bottom: 8),
                  decoration: BoxDecoration(
                    color: AppColors.bg,
                    borderRadius: BorderRadius.circular(AppRadius.sm),
                  ),
                  child: Row(
                    children: [
                      ClipRRect(
                        borderRadius: BorderRadius.circular(8),
                        child: SizedBox(
                          width: 64,
                          height: 64,
                          child: resolveMedia(item.coverImage).isEmpty
                              ? const _MiniCover()
                              : Image.network(
                                  resolveMedia(item.coverImage),
                                  fit: BoxFit.cover,
                                  errorBuilder: (_, _, _) =>
                                      const _MiniCover(),
                                ),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              item.title,
                              style: const TextStyle(
                                fontSize: 14,
                                fontWeight: FontWeight.w600,
                                color: AppColors.text,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              item.reason,
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontSize: 11,
                                color: AppColors.muted,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
            Text(
              '今日剩余 ${result.quota.remaining} 次',
              style: const TextStyle(fontSize: 11, color: AppColors.faint),
            ),
          ],
        ],
      ],
    );
  }

  Widget _buildBar(PostDetail detail) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.96),
        border: const Border(top: BorderSide(color: AppColors.line)),
      ),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
          child: Row(
            children: [
              GestureDetector(
                onTap: _toggleLike,
                behavior: HitTestBehavior.opaque,
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 8,
                  ),
                  child: Row(
                    children: [
                      Icon(
                        detail.likedByMe
                            ? Icons.favorite
                            : Icons.favorite_border,
                        size: 20,
                        color: detail.likedByMe
                            ? AppColors.primary
                            : AppColors.muted,
                      ),
                      const SizedBox(width: 4),
                      Text(
                        '${detail.likeCount}',
                        style: const TextStyle(
                          fontSize: 12,
                          color: AppColors.muted,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              GestureDetector(
                onTap: _toggleSave,
                behavior: HitTestBehavior.opaque,
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 8,
                  ),
                  child: Row(
                    children: [
                      Icon(
                        detail.savedByMe ? Icons.star : Icons.star_border,
                        size: 20,
                        color: detail.savedByMe
                            ? AppColors.primary
                            : AppColors.muted,
                      ),
                      const SizedBox(width: 4),
                      Text(
                        detail.savedByMe ? '已收藏' : '收藏',
                        style: const TextStyle(
                          fontSize: 12,
                          color: AppColors.muted,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: GestureDetector(
                  onTap: () => setState(() => _aiOpen = !_aiOpen),
                  behavior: HitTestBehavior.opaque,
                  child: Container(
                    padding: const EdgeInsets.symmetric(vertical: 11),
                    decoration: BoxDecoration(
                      color: AppColors.primary,
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: const Text(
                      '问 AI 今晚吃啥',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: Colors.white,
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _recipeTitle(PostDetail detail) {
    if (detail.authorRecipe != null) return '作者随饭帖提供的做法';
    if (detail.recipe != null) return detail.recipeLabel ?? '平台参考做法';
    return '';
  }

  List<String> _ingredientLines(PostDetail detail) {
    if (detail.authorRecipe != null) return detail.authorRecipe!.ingredients;
    if (detail.recipe != null) {
      return detail.recipe!.ingredients
          .map((item) => '${item.name} ${item.amount}'.trim())
          .toList(growable: false);
    }
    return const [];
  }

  List<String> _stepLines(PostDetail detail) {
    if (detail.authorRecipe != null) return detail.authorRecipe!.steps;
    if (detail.recipe != null) return detail.recipe!.steps;
    return const [];
  }

  Widget _infoRow(String label, String value) {
    return Container(
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.only(top: 12),
      decoration: const BoxDecoration(
        border: Border(top: BorderSide(color: AppColors.line)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 64,
            child: Text(
              label,
              style: const TextStyle(fontSize: 13, color: AppColors.faint),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: const TextStyle(fontSize: 13, color: AppColors.text),
            ),
          ),
        ],
      ),
    );
  }

  Widget _ingredientRow(String line) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 5,
            height: 5,
            margin: const EdgeInsets.only(top: 7),
            decoration: const BoxDecoration(
              color: AppColors.primary,
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              line,
              style: const TextStyle(fontSize: 14, color: AppColors.text),
            ),
          ),
        ],
      ),
    );
  }

  Widget _stepRow(int index, String text) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
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
}

class _SectionLabel extends StatelessWidget {
  const _SectionLabel(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(
        fontSize: 13,
        fontWeight: FontWeight.w600,
        color: AppColors.muted,
      ),
    );
  }
}

class _MiniCover extends StatelessWidget {
  const _MiniCover();

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.peach,
      alignment: Alignment.center,
      child: const Icon(
        Icons.menu_book_outlined,
        size: 20,
        color: AppColors.primaryDeep,
      ),
    );
  }
}
