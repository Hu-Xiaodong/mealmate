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
  const PublishPage({super.key, this.draftId});

  /// 传入草稿编号时进入“继续编辑草稿”模式。
  final String? draftId;

  @override
  State<PublishPage> createState() => _PublishPageState();
}

class _PickedImage {
  const _PickedImage({required this.assetId, this.path = '', this.url});

  final String assetId;

  /// 本地文件路径；草稿里的历史图片没有本地文件，改用 [url] 预览。
  final String path;
  final String? url;
}

class _PublishPageState extends State<PublishPage> {
  static const List<String> _tasteOptions = [
    '清淡',
    '正常',
    '香辣',
    '酸甜',
    '咸鲜',
    '油炸',
    '烧烤',
    '汤羹',
    '面食',
  ];

  final ImagePicker _picker = ImagePicker();
  final TextEditingController _title = TextEditingController();
  final TextEditingController _review = TextEditingController();
  final TextEditingController _store = TextEditingController();
  final TextEditingController _address = TextEditingController();
  final TextEditingController _ingredients = TextEditingController();
  final TextEditingController _steps = TextEditingController();
  final TextEditingController _area = TextEditingController();
  final TextEditingController _price = TextEditingController();
  final TextEditingController _placeKeyword = TextEditingController();

  List<_PickedImage> _images = const [];
  int _uploading = 0;
  String _source = 'self';
  bool _recipeOpen = false;
  bool _locationOpen = false;
  Coordinates? _coords;
  bool _submitting = false;
  String _idempotencyKey = _makeKey();

  String? _draftId;
  bool _loadingDraft = false;
  bool _savingDraft = false;
  List<String> _taste = const [];

  bool _mapEnabled = false;
  bool _searching = false;
  List<Place> _places = const [];
  Place? _place;

  @override
  void initState() {
    super.initState();
    _draftId = widget.draftId;
    if (_draftId != null) _loadDraft();
    _loadMapConfig();
  }

  @override
  void dispose() {
    _title.dispose();
    _review.dispose();
    _store.dispose();
    _address.dispose();
    _ingredients.dispose();
    _steps.dispose();
    _area.dispose();
    _price.dispose();
    _placeKeyword.dispose();
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

  Future<void> _loadMapConfig() async {
    try {
      final enabled = await apiClient.mapEnabled();
      if (!mounted) return;
      setState(() => _mapEnabled = enabled);
    } on ApiException {
      // 配置接口失败时按“地图不可用”处理，手动填写店名/地址仍可正常发布。
      if (!mounted) return;
      setState(() => _mapEnabled = false);
    }
  }

  Future<void> _loadDraft() async {
    final draftId = _draftId;
    if (draftId == null) return;
    setState(() => _loadingDraft = true);
    try {
      final draft = await apiClient.myDraft(draftId);
      if (!mounted) return;
      setState(() {
        _title.text = draft.title;
        _review.text = draft.review;
        _source = draft.source ?? 'self';
        _store.text = draft.takeawayStore ?? '';
        _address.text = draft.dineInAddress ?? '';
        _price.text = draft.avgPrice?.toString() ?? '';
        _taste = List<String>.from(draft.tasteTags);
        _images = [
          for (var i = 0; i < draft.imageAssetIds.length; i++)
            _PickedImage(
              assetId: draft.imageAssetIds[i],
              url: i < draft.images.length ? draft.images[i] : null,
            ),
        ];
        final recipe = draft.authorRecipe;
        if (recipe != null) {
          _recipeOpen = true;
          _ingredients.text = recipe.ingredients.join('\n');
          _steps.text = recipe.steps.join('\n');
        }
        final location = draft.location;
        if (location != null) {
          _locationOpen = true;
          _coords = Coordinates(lat: location.lat, lng: location.lng);
          _area.text = location.area ?? '';
        }
        final storeLocation = draft.storeLocation;
        _place = storeLocation == null
            ? null
            : Place(
                id: storeLocation.poiId ?? '',
                name: '',
                address: '',
                lat: storeLocation.lat,
                lng: storeLocation.lng,
              );
      });
    } on ApiException catch (error) {
      if (mounted) showError(context, error, '草稿加载失败');
    } finally {
      if (mounted) setState(() => _loadingDraft = false);
    }
  }

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

  void _toggleTaste(String tag) {
    if (_taste.contains(tag)) {
      setState(() => _taste = _taste.where((item) => item != tag).toList());
      return;
    }
    if (_taste.length >= 3) {
      showMessage(context, '最多选择 3 个口味标签');
      return;
    }
    setState(() => _taste = [..._taste, tag]);
  }

  Future<void> _searchPlaces() async {
    final keyword = _placeKeyword.text.trim();
    if (keyword.isEmpty) {
      showMessage(context, '先输入店名再搜索');
      return;
    }
    if (!_locationOpen || _coords == null) {
      showMessage(context, '先开启下方“公开大概位置”再搜索店铺');
      return;
    }
    if (_searching) return;
    setState(() => _searching = true);
    try {
      final items = await apiClient.searchPlaces(
        keyword: keyword,
        lat: _locationOpen ? _coords?.lat : null,
        lng: _locationOpen ? _coords?.lng : null,
      );
      if (!mounted) return;
      setState(() => _places = items);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _places = const [];
        if (error.status == 503) _mapEnabled = false;
      });
      if (error.status == 503) {
        showMessage(context, '地图暂不可用，可手动填写地址');
      } else {
        showError(context, error, '搜索店铺失败');
      }
    } finally {
      if (mounted) setState(() => _searching = false);
    }
  }

  void _selectPlace(Place place) {
    setState(() {
      _place = place;
      _places = const [];
      if (_source == 'takeaway') {
        _store.text = place.name;
      } else if (_source == 'dine_in') {
        _address.text = place.address.isEmpty
            ? place.name
            : '${place.name} · ${place.address}';
      }
    });
  }

  String _placeLabel() {
    final place = _place;
    if (place == null) return '';
    if (place.name.isNotEmpty) return place.name;
    if (_source == 'takeaway') return _store.text.trim();
    return _address.text.trim();
  }

  List<String> _parseLines(String text) {
    return text
        .split('\n')
        .map((line) => line.trim())
        .where((line) => line.isNotEmpty)
        .toList(growable: false);
  }

  Map<String, dynamic> _payload() {
    final ingredients = _parseLines(_ingredients.text);
    final steps = _parseLines(_steps.text);
    final recipe = _recipeOpen && ingredients.isNotEmpty && steps.isNotEmpty
        ? {'ingredients': ingredients, 'steps': steps}
        : null;
    final place = _place;
    final storeLocation = _source != 'self' && place != null
        ? StoreLocation(
            lat: place.lat,
            lng: place.lng,
            poiId: place.id.isEmpty ? null : place.id,
          ).toJson()
        : null;
    return {
      'title': _title.text.trim(),
      'review': _review.text.trim(),
      'source': _source,
      'imageAssetIds': _images.map((item) => item.assetId).toList(),
      'authorRecipe': recipe,
      'takeawayStore': _source == 'takeaway' ? _store.text.trim() : null,
      'dineInAddress': _source == 'dine_in' ? _address.text.trim() : null,
      'avgPrice': int.tryParse(_price.text.trim()),
      'tasteTags': _taste,
      'storeLocation': storeLocation,
      'location': _locationOpen && _coords != null
          ? {
              'lat': _coords!.lat,
              'lng': _coords!.lng,
              'area': _area.text.trim().isEmpty ? null : _area.text.trim(),
              'publicConsent': true,
            }
          : null,
    };
  }

  Future<void> _saveDraft() async {
    if (!sessionStore.isLoggedIn) {
      await requireLogin(context);
      if (!mounted || !sessionStore.isLoggedIn) return;
    }
    if (_savingDraft || _submitting) return;
    if (_uploading > 0) {
      showMessage(context, '图片还在上传，请稍候');
      return;
    }

    setState(() => _savingDraft = true);
    try {
      final payload = _payload();
      final draftId = _draftId;
      final result = draftId == null
          ? await apiClient.createDraft(payload)
          : await apiClient.updateDraft(draftId, payload);
      if (!mounted) return;
      setState(() => _draftId = result.postId);
      showMessage(context, '草稿已保存');
    } on ApiException catch (error) {
      if (mounted) showError(context, error, '草稿保存失败');
    } finally {
      if (mounted) setState(() => _savingDraft = false);
    }
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

    final payload = _payload();

    setState(() => _submitting = true);
    try {
      final draftId = _draftId;
      final result = draftId == null
          ? await apiClient.createPost(payload, _idempotencyKey)
          : await apiClient.publishDraft(draftId, payload);
      if (draftId == null) _idempotencyKey = _makeKey();
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
    if (_loadingDraft) {
      return const Center(
        child: CircularProgressIndicator(color: AppColors.primary),
      );
    }
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 40),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _imageSection(),
          const SizedBox(height: 14),
          _textSection(),
          const SizedBox(height: 14),
          _priceTasteSection(),
          const SizedBox(height: 14),
          _recipeSection(),
          const SizedBox(height: 14),
          if (_mapEnabled && _source != 'self') ...[
            _storeSearchSection(),
            const SizedBox(height: 14),
          ],
          _locationSection(),
          const SizedBox(height: 18),
          PrimaryButton(
            label: _submitting ? '发布中…' : '发布',
            busy: _submitting,
            dimmed: !_canSubmit,
            onTap: _submit,
          ),
          const SizedBox(height: 10),
          _draftButton(),
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

  Widget _draftButton() {
    return GestureDetector(
      onTap: _savingDraft ? null : _saveDraft,
      behavior: HitTestBehavior.opaque,
      child: Opacity(
        opacity: _savingDraft ? 0.6 : 1,
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 13),
          decoration: BoxDecoration(
            color: AppColors.peach,
            borderRadius: BorderRadius.circular(999),
            border: Border.all(color: AppColors.primary.withValues(alpha: 0.4)),
          ),
          child: Text(
            _savingDraft ? '保存中…' : '存草稿',
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: AppColors.primaryDeep,
            ),
          ),
        ),
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
            _imagePreview(image),
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

  Widget _imagePreview(_PickedImage image) {
    if (image.path.isNotEmpty) {
      return Image.file(
        File(image.path),
        fit: BoxFit.cover,
        errorBuilder: (_, _, _) => const ColoredBox(color: AppColors.peach),
      );
    }
    final url = resolveMedia(image.url);
    if (url.isEmpty) return const ColoredBox(color: AppColors.peach);
    return Image.network(
      url,
      fit: BoxFit.cover,
      errorBuilder: (_, _, _) => const ColoredBox(color: AppColors.peach),
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

  Widget _priceTasteSection() {
    return SectionCard(
      margin: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _Label('人均价格（可选）'),
          const SizedBox(height: 8),
          TextField(
            controller: _price,
            keyboardType: TextInputType.number,
            inputFormatters: [
              FilteringTextInputFormatter.digitsOnly,
              LengthLimitingTextInputFormatter(4),
            ],
            decoration: _inputDecoration('例如：28（单位：元）'),
            style: const TextStyle(fontSize: 15, color: AppColors.text),
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              const Expanded(child: _Label('口味标签（最多 3 个）')),
              Text(
                '${_taste.length}/3',
                style: const TextStyle(fontSize: 12, color: AppColors.faint),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final tag in _tasteOptions) _tasteChip(tag),
            ],
          ),
        ],
      ),
    );
  }

  Widget _tasteChip(String tag) {
    final selected = _taste.contains(tag);
    return GestureDetector(
      onTap: () => _toggleTaste(tag),
      behavior: HitTestBehavior.opaque,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 160),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: selected ? AppColors.peach : AppColors.bg,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(
            color: selected ? AppColors.primary : Colors.transparent,
          ),
        ),
        child: Text(
          tag,
          style: TextStyle(
            fontSize: 12,
            color: selected ? AppColors.primaryDeep : AppColors.muted,
            fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
          ),
        ),
      ),
    );
  }

  Widget _storeSearchSection() {
    final place = _place;
    return SectionCard(
      margin: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '搜索店铺',
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w700,
              color: AppColors.text,
            ),
          ),
          const SizedBox(height: 4),
          const Text(
            '先开启下方「公开大概位置」，搜索会按你附近 1 公里查找；选中后自动回填名称和地址。',
            style: TextStyle(fontSize: 12, color: AppColors.muted, height: 1.55),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _placeKeyword,
                  textInputAction: TextInputAction.search,
                  onSubmitted: (_) => _searchPlaces(),
                  decoration: _inputDecoration(
                    _source == 'takeaway' ? '例如：老友粉店' : '例如：商场里的粉店',
                  ),
                  style: const TextStyle(fontSize: 14, color: AppColors.text),
                ),
              ),
              const SizedBox(width: 8),
              GestureDetector(
                onTap: _searching ? null : _searchPlaces,
                behavior: HitTestBehavior.opaque,
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 16,
                    vertical: 12,
                  ),
                  decoration: BoxDecoration(
                    color: AppColors.primary,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    _searching ? '搜索中…' : '搜索',
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: Colors.white,
                    ),
                  ),
                ),
              ),
            ],
          ),
          if (_places.isNotEmpty) ...[
            const SizedBox(height: 10),
            for (final item in _places) _placeRow(item),
          ],
          if (place != null) ...[
            const SizedBox(height: 12),
            ClipRRect(
              borderRadius: BorderRadius.circular(12),
              child: AspectRatio(
                aspectRatio: 2,
                child: Image.network(
                  apiClient.staticMapUrl(lat: place.lat, lng: place.lng),
                  fit: BoxFit.cover,
                  errorBuilder: (_, _, _) => Container(
                    color: AppColors.peach,
                    alignment: Alignment.center,
                    child: const Text(
                      '地图加载失败，可继续填写地址',
                      style: TextStyle(fontSize: 12, color: AppColors.muted),
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: Text(
                    _placeLabel().isEmpty ? '已选择店铺位置' : _placeLabel(),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 12,
                      color: AppColors.muted,
                    ),
                  ),
                ),
                GestureDetector(
                  onTap: () => setState(() {
                    _place = null;
                    _places = const [];
                  }),
                  behavior: HitTestBehavior.opaque,
                  child: const Padding(
                    padding: EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 4,
                    ),
                    child: Text(
                      '清除',
                      style: TextStyle(
                        fontSize: 12,
                        color: AppColors.primary,
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _placeRow(Place place) {
    final distance = distanceLabel(place.distanceMeters);
    return GestureDetector(
      onTap: () => _selectPlace(place),
      behavior: HitTestBehavior.opaque,
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: AppColors.bg,
          borderRadius: BorderRadius.circular(10),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    place.name,
                    style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: AppColors.text,
                    ),
                  ),
                  if (place.address.isNotEmpty) ...[
                    const SizedBox(height: 3),
                    Text(
                      place.address,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 11,
                        color: AppColors.faint,
                      ),
                    ),
                  ],
                ],
              ),
            ),
            if (distance.isNotEmpty) ...[
              const SizedBox(width: 8),
              Text(
                distance,
                style: const TextStyle(fontSize: 11, color: AppColors.faint),
              ),
            ],
          ],
        ),
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
