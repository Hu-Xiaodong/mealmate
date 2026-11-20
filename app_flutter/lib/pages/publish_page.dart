import 'dart:io';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:geolocator/geolocator.dart';
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
import 'store_map_page.dart';

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
  final ImagePicker _picker = ImagePicker();
  final TextEditingController _title = TextEditingController();
  final TextEditingController _review = TextEditingController();
  final TextEditingController _store = TextEditingController();
  final TextEditingController _address = TextEditingController();
  final TextEditingController _ingredients = TextEditingController();
  final TextEditingController _steps = TextEditingController();
  final TextEditingController _price = TextEditingController();

  List<_PickedImage> _images = const [];
  int _uploading = 0;
  String _source = 'self';
  bool _recipeOpen = false;

  /// 外卖 / 到店使用的定位。来源有两种：手机当前定位，或后端保存的历史定位。
  Coordinates? _coords;

  /// 地图选中的店铺坐标。地图里没找到店铺时为 null，但名称仍然可以提交。
  Place? _storePlace;

  bool _submitting = false;
  bool _resolvingLocation = false;
  String _idempotencyKey = _makeKey();

  String? _draftId;
  bool _loadingDraft = false;
  bool _savingDraft = false;
  List<String> _taste = const [];

  /// 口味标签选项改为后端接口下发，客户端不再写死。
  List<String> _tasteOptions = const [];
  bool _loadingTaste = false;
  String? _tasteError;

  @override
  void initState() {
    super.initState();
    _draftId = widget.draftId;
    _bootstrap();
  }

  /// 启动时依次加载标签字典和草稿。
  /// 标签加载失败不能阻塞草稿编辑：[_loadTasteTags] 自己吞掉错误并展示重试入口。
  Future<void> _bootstrap() async {
    await _loadTasteTags();
    // 标签加载期间用户可能已经离开页面，不能再对已销毁的页面调用 setState。
    if (!mounted) return;
    final draftId = _draftId;
    if (draftId != null) await _loadDraft();
  }

  @override
  void dispose() {
    _title.dispose();
    _review.dispose();
    _store.dispose();
    _address.dispose();
    _ingredients.dispose();
    _steps.dispose();
    _price.dispose();
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

  Future<void> _loadTasteTags() async {
    setState(() => _loadingTaste = true);
    try {
      final tags = await apiClient.tasteTags();
      if (!mounted) return;
      setState(() {
        _tasteOptions = tags;
        _tasteError = null;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _tasteError = error.message);
    } finally {
      if (mounted) setState(() => _loadingTaste = false);
    }
  }

  /// 口味标签的展示列表。
  ///
  /// 除了接口下发的字典，还要把“草稿里已经选中、但字典里已停用”的旧标签带上，
  /// 否则用户打开旧草稿会看不到自己选过的标签，也无法取消它。
  List<String> get _visibleTasteOptions {
    final missing = _taste.where((tag) => !_tasteOptions.contains(tag));
    return [..._tasteOptions, ...missing];
  }

  /// 解析外卖 / 到店要用的定位。
  ///
  /// 顺序严格按需求：
  /// 1. 手机已开启定位 → 取当前位置，并异步写入后端作为“最新定位”；
  /// 2. 手机没开启定位 → 读取后端保存的历史定位；
  /// 3. 两者都没有 → 弹框提示开启定位，用户确认后跳系统定位设置。
  ///
  /// [force] 为 true 时忽略页面上已缓存的坐标，重新走一遍检查。
  Future<Coordinates?> _resolveLocation({bool force = false}) async {
    if (!force && _coords != null) return _coords;
    if (_resolvingLocation) return null;
    setState(() => _resolvingLocation = true);
    try {
      final current = await currentLocationIfPermitted();
      if (current != null) {
        if (mounted) setState(() => _coords = current);
        // 写入历史定位失败不影响本次发布，所以不等待、不提示。
        apiClient.saveMyLocation(lat: current.lat, lng: current.lng).ignore();
        return current;
      }
      final history = await apiClient.myLocation();
      if (history != null) {
        if (mounted) setState(() => _coords = history);
        return history;
      }
      if (mounted) await _showLocationRequiredDialog();
      return null;
    } on ApiException catch (error) {
      if (mounted) showError(context, error, '定位获取失败');
      return null;
    } finally {
      if (mounted) setState(() => _resolvingLocation = false);
    }
  }

  Future<void> _showLocationRequiredDialog() async {
    final openSettings = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('请先开启手机定位'),
        content: const Text('外卖和到店需要用当前位置查找附近店铺。开启定位后再回来试试。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('去开启'),
          ),
        ],
      ),
    );
    if (openSettings != true) return;

    // 分两种情况：
    // - 系统定位总开关没开：跳系统“位置信息”设置页；
    // - 总开关已开但 App 没权限：永久拒绝只能去应用设置，普通拒绝可以直接再次申请。
    final serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) {
      final opened = await Geolocator.openLocationSettings();
      if (!opened) await Geolocator.openAppSettings();
      return;
    }
    final permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.deniedForever) {
      await Geolocator.openAppSettings();
    } else {
      await Geolocator.requestPermission();
    }
  }

  /// 切换来源：自己做不需要定位；外卖 / 到店必须先拿到定位。
  Future<void> _selectSource(String value) async {
    if (value == _source) return;
    if (value == 'self') {
      setState(() {
        _source = 'self';
        _coords = null;
        _storePlace = null;
        _store.clear();
        _address.clear();
      });
      return;
    }
    final coords = await _resolveLocation(force: true);
    if (!mounted || coords == null) return;
    setState(() {
      _source = value;
      _storePlace = null;
      _store.clear();
      _address.clear();
    });
  }

  /// 打开全屏地图选点页，并把结果回填到店名 / 地址字段。
  Future<void> _openStoreMap() async {
    final coords = _coords ?? await _resolveLocation();
    if (!mounted || coords == null) return;
    // 先收起键盘，避免输入法窗口残留影响地图页的全屏布局。
    FocusScope.of(context).unfocus();
    final isTakeaway = _source == 'takeaway';
    final initial = isTakeaway ? _store.text.trim() : _address.text.trim();
    final result = await Navigator.of(context).push<StoreMapResult>(
      MaterialPageRoute(
        builder: (_) => StoreMapPage(
          center: coords,
          initialKeyword: initial,
          title: isTakeaway ? '选择店家' : '选择店铺地址',
        ),
      ),
    );
    if (!mounted || result == null) return;
    setState(() {
      _storePlace = result.place;
      if (isTakeaway) {
        _store.text = _clampText(result.name, 80);
      } else {
        _address.text = _clampText(
          result.address.isEmpty ? result.name : result.address,
          160,
        );
      }
    });
  }

  /// 后端对店名限 80 字、地址限 160 字；程序赋值不会触发输入框的 maxLength，
  /// 所以这里手动截断，避免提交时被后端判为超长。
  static String _clampText(String value, int maxLength) {
    final text = value.trim();
    return text.length <= maxLength ? text : text.substring(0, maxLength);
  }

  Future<void> _loadDraft() async {
    final draftId = _draftId;
    if (draftId == null || !mounted) return;
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
          _coords = Coordinates(lat: location.lat, lng: location.lng);
        }
        final storeLocation = draft.storeLocation;
        _storePlace = storeLocation == null
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
    final place = _storePlace;
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
      // 外卖 / 到店会自动带上定位：它同时作为饭帖的“大概位置”，
      // 让首页「附近」仍然能按距离推荐。精度由后端统一降到三位小数。
      'location': _source != 'self' && _coords != null
          ? {
              'lat': _coords!.lat,
              'lng': _coords!.lng,
              'area': null,
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
    if (_source != 'self') {
      // 正常流程在点击来源时已经拿到定位；这里再兜一次底，
      // 防止用户打开旧草稿后直接发布、而草稿里没有保存定位。
      final coords = await _resolveLocation();
      if (!mounted || coords == null) return;
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
      // 提示和返回同时发生：先插入浮层，再立刻返回上一页。
      // 浮层挂在 Navigator 的 Overlay 上，不会随发布页一起销毁，会在上一页继续淡出。
      _showPublishResult(result.reviewRequired ? '已提交审核' : '发布成功');
      Navigator.of(context).pop();
    } on ApiException catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  /// 发布结果提示：屏幕上方居中，淡入、停留、淡出，结束后自动移除。
  ///
  /// 为什么用 Overlay：
  /// 1. SnackBar 固定在屏幕底部，不满足位置要求；
  /// 2. showDialog 会阻塞用户并需要点确认；
  /// 3. 浮层挂在 Navigator 的 Overlay 上，发布页返回后还能继续显示。
  void _showPublishResult(String message) {
    final overlay = Overlay.of(context);
    late final OverlayEntry entry;
    entry = OverlayEntry(
      builder: (context) {
        return Positioned(
          top: MediaQuery.sizeOf(context).height * 0.12,
          left: 0,
          right: 0,
          child: IgnorePointer(
            child: Center(
              child: _PublishResultToast(
                message: message,
                onFinished: () {
                  if (entry.mounted) entry.remove();
                },
              ),
            ),
          ),
        );
      },
    );
    overlay.insert(entry);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bg,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const AppHeader(showBack: true),
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
            onSelected: _selectSource,
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
            _storePicker(
              hint: '点击进入地图选择店家',
              value: _store.text.trim(),
              onTap: _resolvingLocation ? null : _openStoreMap,
              onClear: () => setState(() {
                _store.clear();
                _storePlace = null;
              }),
            ),
          ],
          if (_source == 'dine_in') ...[
            const SizedBox(height: 12),
            const _Label('店铺地址'),
            const SizedBox(height: 8),
            _storePicker(
              hint: '点击进入地图选择店铺地址',
              value: _address.text.trim(),
              onTap: _resolvingLocation ? null : _openStoreMap,
              onClear: () => setState(() {
                _address.clear();
                _storePlace = null;
              }),
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
              if (_loadingTaste)
                const SizedBox(
                  width: 12,
                  height: 12,
                  child: CircularProgressIndicator(
                    strokeWidth: 1.6,
                    color: AppColors.primary,
                  ),
                )
              else
                Text(
                  '${_taste.length}/3',
                  style: const TextStyle(fontSize: 12, color: AppColors.faint),
                ),
            ],
          ),
          const SizedBox(height: 8),
          if (_tasteError != null) ...[
            Row(
              children: [
                Expanded(
                  child: Text(
                    '口味标签加载失败：$_tasteError',
                    style: const TextStyle(fontSize: 12, color: AppColors.muted),
                  ),
                ),
                TextButton(
                  onPressed: _loadingTaste ? null : _loadTasteTags,
                  child: const Text('重试'),
                ),
              ],
            ),
          ] else if (!_loadingTaste && _tasteOptions.isEmpty)
            const Text(
              '暂时没有可选的口味标签',
              style: TextStyle(fontSize: 12, color: AppColors.faint),
            )
          else
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final tag in _visibleTasteOptions) _tasteChip(tag),
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

  /// 店名 / 地址选择框。
  ///
  /// 为什么做成“只读入口”而不是普通输入框：
  /// 需求要求点击后进入地图页选店，名称必须来自地图结果（或用户在地图页手写确认），
  /// 这样才能保证“名称”和“坐标”来自同一个来源。
  Widget _storePicker({
    required String hint,
    required String value,
    required VoidCallback? onTap,
    required VoidCallback onClear,
  }) {
    final empty = value.isEmpty;
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
        decoration: BoxDecoration(
          color: AppColors.bg,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          children: [
            const Icon(Icons.map_outlined, size: 18, color: AppColors.muted),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                empty ? hint : value,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 14,
                  color: empty ? AppColors.faint : AppColors.text,
                ),
              ),
            ),
            if (empty)
              const Icon(
                Icons.chevron_right,
                size: 18,
                color: AppColors.faint,
              )
            else
              GestureDetector(
                onTap: onClear,
                behavior: HitTestBehavior.opaque,
                child: const Padding(
                  padding: EdgeInsets.only(left: 8),
                  child: Icon(Icons.close, size: 16, color: AppColors.faint),
                ),
              ),
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
            const _Label('食材'),
            const SizedBox(height: 8),
            TextField(
              controller: _ingredients,
              minLines: 5,
              maxLines: 8,
              decoration: _inputDecoration(
                '例如：豆角 200 克、鲜面条 150 克、蒜 2 瓣',
              ),
              style: const TextStyle(fontSize: 14, color: AppColors.text),
            ),
            const SizedBox(height: 12),
            const _Label('步骤'),
            const SizedBox(height: 8),
            TextField(
              controller: _steps,
              minLines: 5,
              maxLines: 8,
              decoration: _inputDecoration(
                '例如：豆角掰段炒香，加水铺面焖 12 分钟，最后拌匀收汁',
              ),
              style: const TextStyle(fontSize: 14, color: AppColors.text),
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

/// 发布结果浮层里的提示卡片。
///
/// 单独做成有状态组件，是为了拿到 AnimationController 做淡入淡出：
/// 先淡入 180 毫秒，停留 900 毫秒，再淡出 180 毫秒，结束后通知外部移除浮层。
class _PublishResultToast extends StatefulWidget {
  const _PublishResultToast({required this.message, required this.onFinished});

  final String message;
  final VoidCallback onFinished;

  @override
  State<_PublishResultToast> createState() => _PublishResultToastState();
}

class _PublishResultToastState extends State<_PublishResultToast>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 180),
  );

  late final Animation<double> _opacity = CurvedAnimation(
    parent: _controller,
    curve: Curves.easeOut,
  );

  @override
  void initState() {
    super.initState();
    _play();
  }

  Future<void> _play() async {
    await _controller.forward();
    await Future<void>.delayed(const Duration(milliseconds: 900));
    if (!mounted) return;
    await _controller.reverse();
    if (mounted) widget.onFinished();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: _opacity,
      child: Material(
        color: Colors.transparent,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
          decoration: BoxDecoration(
            color: AppColors.card,
            borderRadius: BorderRadius.circular(14),
            boxShadow: const [
              BoxShadow(
                color: Colors.black26,
                blurRadius: 16,
                offset: Offset(0, 6),
              ),
            ],
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(
                Icons.check_circle,
                size: 20,
                color: AppColors.primary,
              ),
              const SizedBox(width: 8),
              Text(
                widget.message,
                style: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                  color: AppColors.text,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}


