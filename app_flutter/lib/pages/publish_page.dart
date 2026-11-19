import 'dart:io';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../core/format.dart';
import '../core/location.dart';
import '../core/login_gate.dart';
import '../session/session_store.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/common.dart';
import '../widgets/empty_state.dart';
import '../widgets/segmented_tabs.dart';
import 'post_detail_page.dart';

class PublishPage extends StatefulWidget {
  const PublishPage({super.key});

  @override
  State<PublishPage> createState() => _PublishPageState();
}

class _PickedImage {
  const _PickedImage({required this.assetId, required this.path});

  final String assetId;
  final String path;
}

class _PublishPageState extends State<PublishPage> {
  final ImagePicker _picker = ImagePicker();
  final TextEditingController _title = TextEditingController();
  final TextEditingController _review = TextEditingController();
  final TextEditingController _store = TextEditingController();
  final TextEditingController _address = TextEditingController();
  final TextEditingController _ingredients = TextEditingController();
  final TextEditingController _steps = TextEditingController();
  final TextEditingController _area = TextEditingController();

  List<_PickedImage> _images = const [];
  int _uploading = 0;
  String _source = 'self';
  bool _recipeOpen = false;
  bool _locationOpen = false;
  Coordinates? _coords;
  bool _submitting = false;
  String _idempotencyKey = _makeKey();

  @override
  void dispose() {
    _title.dispose();
    _review.dispose();
    _store.dispose();
    _address.dispose();
    _ingredients.dispose();
    _steps.dispose();
    _area.dispose();
    super.dispose();
  }

  static String _makeKey() {
    return 'pub-${DateTime.now().millisecondsSinceEpoch}-'
        '${Random().nextInt(1 << 32).toRadixString(36)}';
  }

  bool get _canSubmit =>
      sessionStore.isLoggedIn &&
      !_submitting &&
      _uploading == 0 &&
      _images.isNotEmpty;

  Future<void> _pickImages() async {
    final remain = 9 - _images.length;
    if (remain <= 0) {
      showMessage(context, '最多上传 9 张图片');
      return;
    }
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      backgroundColor: AppColors.card,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (sheetContext) => SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(
                Icons.photo_camera_outlined,
                color: AppColors.primary,
              ),
              title: const Text('拍照'),
              onTap: () =>
                  Navigator.of(sheetContext).pop(ImageSource.camera),
            ),
            ListTile(
              leading: const Icon(
                Icons.photo_library_outlined,
                color: AppColors.primary,
              ),
              title: const Text('从相册选择'),
              onTap: () =>
                  Navigator.of(sheetContext).pop(ImageSource.gallery),
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
    if (source == null) return;

    List<XFile> picked = const [];
    try {
      if (source == ImageSource.camera) {
        final file = await _picker.pickImage(
          source: ImageSource.camera,
          imageQuality: 85,
          maxWidth: 1600,
        );
        picked = file == null ? const [] : [file];
      } else {
        picked = await _picker.pickMultiImage(
          imageQuality: 85,
          maxWidth: 1600,
        );
      }
    } on PlatformException catch (_) {
      if (mounted) showMessage(context, '无法打开图片选择器，请检查相册权限');
      return;
    }
    if (!mounted || picked.isEmpty) return;

    for (final file in picked.take(remain)) {
      await _upload(file.path);
    }
  }

  Future<void> _upload(String path) async {
    if (!mounted) return;
    setState(() => _uploading += 1);
    try {
      final asset = await apiClient.uploadImage(path);
      if (!mounted) return;
      setState(() {
        _images = [..._images, _PickedImage(assetId: asset.assetId, path: path)];
      });
    } on ApiException catch (error) {
      if (mounted) showError(context, error, '图片上传失败');
    } finally {
      if (mounted) setState(() => _uploading -= 1);
    }
  }

  void _removeImage(int index) {
    setState(() {
      final next = [..._images]..removeAt(index);
      _images = next;
    });
  }

  Future<void> _toggleLocation() async {
    if (_locationOpen) {
      setState(() => _locationOpen = false);
      return;
    }
    try {
      final coords = await locateCoarse();
      if (!mounted) return;
      setState(() {
        _coords = coords;
        _locationOpen = true;
      });
    } on LocationFailure catch (error) {
      if (mounted) showMessage(context, error.message);
    }
  }

  List<String> _parseLines(String text) {
    return text
        .split('\n')
        .map((line) => line.trim())
        .where((line) => line.isNotEmpty)
        .toList(growable: false);
  }

  Future<void> _submit() async {
    if (!sessionStore.isLoggedIn) {
      await requireLogin(context);
      if (!mounted || !sessionStore.isLoggedIn) return;
    }
    if (_submitting) return;
    if (_uploading > 0) {
      showMessage(context, '图片还在上传，请稍候');
      return;
    }
    final title = _title.text.trim();
    if (title.isEmpty) {
      showMessage(context, '给这顿饭起个名字');
      return;
    }
    final review = _review.text.trim();
    if (review.isEmpty) {
      showMessage(context, '写一句真实的评价');
      return;
    }
    if (_images.isEmpty) {
      showMessage(context, '至少上传 1 张图片');
      return;
    }
    if (_source == 'takeaway' && _store.text.trim().isEmpty) {
      showMessage(context, '外卖来源需要填写店家名称');
      return;
    }
    if (_source == 'dine_in' && _address.text.trim().isEmpty) {
      showMessage(context, '到店来源需要填写店铺地址');
      return;
    }

    final ingredients = _parseLines(_ingredients.text);
    final steps = _parseLines(_steps.text);
    if (_recipeOpen && (ingredients.isEmpty || steps.isEmpty)) {
      showMessage(context, '作者做法需要食材和步骤一起填写');
      return;
    }

    final payload = <String, dynamic>{
      'title': title,
      'review': review,
      'source': _source,
      'imageAssetIds': _images.map((item) => item.assetId).toList(),
      'authorRecipe': _recipeOpen && ingredients.isNotEmpty && steps.isNotEmpty
          ? {'ingredients': ingredients, 'steps': steps}
          : null,
      'takeawayStore': _source == 'takeaway' ? _store.text.trim() : null,
      'dineInAddress': _source == 'dine_in' ? _address.text.trim() : null,
      'location': _locationOpen && _coords != null
          ? {
              'lat': _coords!.lat,
              'lng': _coords!.lng,
              'area': _area.text.trim().isEmpty ? null : _area.text.trim(),
              'publicConsent': true,
            }
          : null,
    };

    setState(() => _submitting = true);
    try {
      final result = await apiClient.createPost(payload, _idempotencyKey);
      _idempotencyKey = _makeKey();
      if (!mounted) return;
      if (result.reviewRequired) {
        showMessage(context, '已提交审核');
        Navigator.of(context).pop();
      } else {
        showMessage(context, '发布成功');
        Navigator.of(context).pushReplacement(
          MaterialPageRoute<void>(
            builder: (_) => PostDetailPage(postId: result.postId),
          ),
        );
      }
    } on ApiException catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const AppHeader(
              title: '发布今天的饭',
              subtitle: '真实的一餐，比精致的摆拍更有用',
              showBack: true,
            ),
            Expanded(
              child: sessionStore.isLoggedIn ? _form() : _guest(),
            ),
          ],
        ),
      ),
    );
  }

  Widget _guest() {
    return SingleChildScrollView(
      child: EmptyState(
        title: '登录后才能发布',
        description: '登录后可以上传图片、记录评价，也能管理自己的发布。',
        actionText: '手机号登录',
        onAction: () => requireLogin(context),
      ),
    );
  }

  Widget _form() {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 40),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _imageSection(),
          const SizedBox(height: 14),
          _textSection(),
          const SizedBox(height: 14),
          _recipeSection(),
          const SizedBox(height: 14),
          _locationSection(),
          const SizedBox(height: 18),
          PrimaryButton(
            label: _submitting ? '发布中…' : '发布',
            busy: _submitting,
            dimmed: !_canSubmit,
            onTap: _submit,
          ),
          const SizedBox(height: 12),
          const Text(
            '发布后会先进入审核，审核通过后出现在首页与热榜。',
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: 12,
              color: AppColors.faint,
              height: 1.6,
            ),
          ),
        ],
      ),
    );
  }

  Widget _imageSection() {
    return SectionCard(
      margin: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '这一餐的照片',
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w700,
              color: AppColors.text,
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            '1–9 张，单张不超过 5MB。第一张会作为封面。',
            style: TextStyle(fontSize: 12, color: AppColors.muted, height: 1.55),
          ),
          const SizedBox(height: 12),
          LayoutBuilder(
            builder: (context, constraints) {
              final tileWidth = (constraints.maxWidth - 20) / 3;
              return Wrap(
                spacing: 10,
                runSpacing: 10,
                children: [
                  for (var i = 0; i < _images.length; i++)
                    _imageTile(_images[i], i, tileWidth),
                  if (_images.length < 9)
                    _addTile(tileWidth),
                ],
              );
            },
          ),
        ],
      ),
    );
  }

  Widget _imageTile(_PickedImage image, int index, double width) {
    return SizedBox(
      width: width,
      height: 96,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(12),
        child: Stack(
          fit: StackFit.expand,
          children: [
            Image.file(
              File(image.path),
              fit: BoxFit.cover,
              errorBuilder: (_, _, _) =>
                  const ColoredBox(color: AppColors.peach),
            ),
            Positioned(
              top: 4,
              right: 4,
              child: GestureDetector(
                onTap: () => _removeImage(index),
                child: Container(
                  width: 20,
                  height: 20,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: AppColors.text.withValues(alpha: 0.55),
                    shape: BoxShape.circle,
                  ),
                  child: const Icon(
                    Icons.close,
                    size: 13,
                    color: Colors.white,
                  ),
                ),
              ),
            ),
            if (index == 0)
              Positioned(
                left: 6,
                bottom: 6,
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 2,
                  ),
                  decoration: BoxDecoration(
                    color: AppColors.primary.withValues(alpha: 0.9),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: const Text(
                    '封面',
                    style: TextStyle(fontSize: 10, color: Colors.white),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _addTile(double width) {
    return GestureDetector(
      onTap: _pickImages,
      behavior: HitTestBehavior.opaque,
      child: Container(
        width: width,
        height: 96,
        decoration: BoxDecoration(
          color: AppColors.peach,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: AppColors.primary.withValues(alpha: 0.4),
          ),
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.add, size: 22, color: AppColors.primary),
            const SizedBox(height: 4),
            Text(
              _uploading > 0 ? '上传中…' : '添加图片',
              style: const TextStyle(
                fontSize: 11,
                color: AppColors.primaryDeep,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _textSection() {
    return SectionCard(
      margin: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _Label('菜名'),
          const SizedBox(height: 8),
          TextField(
            controller: _title,
            maxLength: 24,
            onChanged: (_) => setState(() {}),
            decoration: _inputDecoration('例如：番茄鸡蛋盖饭', counter: true),
            style: const TextStyle(fontSize: 15, color: AppColors.text),
          ),
          const SizedBox(height: 12),
          const _Label('评价'),
          const SizedBox(height: 8),
          TextField(
            controller: _review,
            maxLength: 200,
            minLines: 3,
            maxLines: 5,
            onChanged: (_) => setState(() {}),
            decoration: _inputDecoration(
              '味道、分量、踩过的坑，都可以写下来',
              counter: true,
            ),
            style: const TextStyle(fontSize: 14, color: AppColors.text),
          ),
          const SizedBox(height: 12),
          const _Label('来源'),
          const SizedBox(height: 8),
          SegmentedTabs<String>(
            selected: _source,
            onSelected: (value) => setState(() => _source = value),
            trackColor: AppColors.bg,
            options: const [
              SegmentOption('self', '自己做'),
              SegmentOption('takeaway', '外卖'),
              SegmentOption('dine_in', '到店'),
            ],
          ),
          if (_source == 'takeaway') ...[
            const SizedBox(height: 12),
            const _Label('店家名称'),
            const SizedBox(height: 8),
            TextField(
              controller: _store,
              maxLength: 80,
              decoration: _inputDecoration('例如：街角便当'),
              style: const TextStyle(fontSize: 15, color: AppColors.text),
            ),
          ],
          if (_source == 'dine_in') ...[
            const SizedBox(height: 12),
            const _Label('店铺地址'),
            const SizedBox(height: 8),
            TextField(
              controller: _address,
              maxLength: 160,
              decoration: _inputDecoration('例如：演示路 12 号 · 老友粉店'),
              style: const TextStyle(fontSize: 15, color: AppColors.text),
            ),
          ],
        ],
      ),
    );
  }

  Widget _recipeSection() {
    return SectionCard(
      margin: EdgeInsets.zero,
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          GestureDetector(
            onTap: () => setState(() => _recipeOpen = !_recipeOpen),
            behavior: HitTestBehavior.opaque,
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        '补充我的做法',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.text,
                        ),
                      ),
                      const SizedBox(height: 4),
                      const Text(
                        '可选。你写的食材和步骤会优先展示给其他饭友。',
                        style: TextStyle(
                          fontSize: 12,
                          color: AppColors.muted,
                          height: 1.55,
                        ),
                      ),
                    ],
                  ),
                ),
                Icon(
                  _recipeOpen ? Icons.expand_more : Icons.chevron_right,
                  size: 20,
                  color: AppColors.faint,
                ),
              ],
            ),
          ),
          if (_recipeOpen) ...[
            const SizedBox(height: 12),
            const _Label('食材（每行一项）'),
            const SizedBox(height: 8),
            TextField(
              controller: _ingredients,
              minLines: 5,
              maxLines: 8,
              decoration: _inputDecoration(
                '豆角 200 克\n鲜面条 150 克\n蒜 2 瓣',
              ),
              style: const TextStyle(fontSize: 14, color: AppColors.text),
            ),
            const SizedBox(height: 12),
            const _Label('步骤（每行一步）'),
            const SizedBox(height: 8),
            TextField(
              controller: _steps,
              minLines: 5,
              maxLines: 8,
              decoration: _inputDecoration(
                '豆角掰段炒香\n加水铺面焖 12 分钟\n拌匀收汁',
              ),
              style: const TextStyle(fontSize: 14, color: AppColors.text),
            ),
          ],
        ],
      ),
    );
  }

  Widget _locationSection() {
    return SectionCard(
      margin: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          GestureDetector(
            onTap: _toggleLocation,
            behavior: HitTestBehavior.opaque,
            child: Row(
              children: [
                const Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '公开大概位置',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.text,
                        ),
                      ),
                      SizedBox(height: 4),
                      Text(
                        '开启后会出现在「附近 3 公里」，只保留百米级精度。',
                        style: TextStyle(
                          fontSize: 12,
                          color: AppColors.muted,
                          height: 1.55,
                        ),
                      ),
                    ],
                  ),
                ),
                _Toggle(value: _locationOpen),
              ],
            ),
          ),
          if (_locationOpen) ...[
            const SizedBox(height: 12),
            const _Label('位置描述（可选）'),
            const SizedBox(height: 8),
            TextField(
              controller: _area,
              maxLength: 80,
              decoration: _inputDecoration('例如：徐汇区某商圈'),
              style: const TextStyle(fontSize: 15, color: AppColors.text),
            ),
          ],
        ],
      ),
    );
  }

  InputDecoration _inputDecoration(String hint, {bool counter = false}) {
    return InputDecoration(
      filled: true,
      fillColor: AppColors.bg,
      hintText: hint,
      hintStyle: const TextStyle(fontSize: 13, color: AppColors.faint),
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      counterText: counter ? null : '',
      counterStyle: const TextStyle(fontSize: 11, color: AppColors.faint),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide.none,
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide.none,
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.primary, width: 1.2),
      ),
    );
  }
}

class _Label extends StatelessWidget {
  const _Label(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(fontSize: 13, color: AppColors.muted),
    );
  }
}

class _Toggle extends StatelessWidget {
  const _Toggle({required this.value});

  final bool value;

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 180),
      width: 44,
      height: 26,
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: value ? AppColors.primary : AppColors.line,
        borderRadius: BorderRadius.circular(13),
      ),
      child: AnimatedAlign(
        duration: const Duration(milliseconds: 180),
        alignment: value ? Alignment.centerRight : Alignment.centerLeft,
        child: Container(
          width: 20,
          height: 20,
          decoration: const BoxDecoration(
            color: Colors.white,
            shape: BoxShape.circle,
          ),
        ),
      ),
    );
  }
}
