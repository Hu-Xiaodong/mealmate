import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../core/format.dart';
import '../core/location.dart';
import '../theme/app_theme.dart';

/// 地图选点页的返回值。
///
/// 为什么要单独定义一个结果对象，而不是直接返回 [Place]：
/// 用户在“地图里没找到”时仍然可以确认，此时没有坐标，只有一个手写名称。
/// 用一个对象把“名称、地址、可选的坐标”一起带回发布页，调用方不用区分两种情况。
class StoreMapResult {
  const StoreMapResult({required this.name, required this.address, this.place});

  final String name;
  final String address;
  final Place? place;
}

/// 全屏静态地图选点页。
///
/// 为什么用“静态地图图片”而不是地图 SDK：
/// 1. 地图 Key 只保存在后端，客户端拿不到，避免 Key 被反编译泄露；
/// 2. 不需要在 Android / iOS 工程里配置地图 SDK 的包名与签名证书；
/// 3. 需求只要求“搜索 → 地图定位到店铺 → 看详情 → 确认”，静态图足够。
/// 代价是不能用手指拖动地图，所以页面提供缩放与回到当前位置按钮作为补偿。
class StoreMapPage extends StatefulWidget {
  const StoreMapPage({
    super.key,
    required this.center,
    this.initialKeyword = '',
    this.title = '选择店铺',
  });

  /// 打开页面时的地图中心点，来自发布页已经确定的当前位置或历史定位。
  final Coordinates center;
  final String initialKeyword;
  final String title;

  @override
  State<StoreMapPage> createState() => _StoreMapPageState();
}

class _StoreMapPageState extends State<StoreMapPage> {
  final TextEditingController _keyword = TextEditingController();

  /// 输入停顿计时器：用户停止输入 1 秒后才自动搜索，避免每敲一个字就请求一次地图服务。
  Timer? _debounce;

  late Coordinates _center;
  int _zoom = 16;

  /// 用户点击选中的候选地点。
  ///
  /// 搜索结果出来后默认不选中任何一条：默认选中等于替用户做决定，
  /// 而第一个结果未必是用户想要的那家店。只有用户主动点击才把它记为选中。
  Place? _selected;

  /// 一次搜索返回的候选地点列表。
  /// 同名店铺可能有多个分店，只取第一个会让用户选不到其他结果。
  List<Place> _results = const [];

  bool _searching = false;

  /// 是否已经完成过一次搜索。用来区分“还没搜”和“搜了但没结果”。
  bool _searched = false;
  String? _error;

  /// 请求序号：网络返回顺序不保证，用它丢弃过期结果，避免旧结果覆盖新结果。
  int _searchSeq = 0;

  @override
  void initState() {
    super.initState();
    _center = widget.center;
    _keyword.text = widget.initialKeyword;
    if (widget.initialKeyword.trim().isNotEmpty) {
      // 首帧结束后再请求，确保此时已经可以安全调用 setState。
      WidgetsBinding.instance.addPostFrameCallback((_) => _search());
    }
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _keyword.dispose();
    super.dispose();
  }

  void _onKeywordChanged(String value) {
    _debounce?.cancel();
    // 关键词一变，之前发出的搜索结果就过期了：
    // 立刻让请求编号前进，避免旧响应回来后又把地图拉回旧店铺。
    _searchSeq++;
    if (value.trim().isEmpty) {
      setState(() {
        _selected = null;
        _results = const [];
        _searched = false;
        _error = null;
        _searching = false;
      });
      return;
    }
    setState(() => _searching = false);
    _debounce = Timer(const Duration(seconds: 1), _search);
  }

  Future<void> _search() async {
    final keyword = _keyword.text.trim();
    if (keyword.isEmpty) {
      // 清空输入时同样要让在途请求失效。
      _searchSeq++;
      setState(() {
        _selected = null;
        _results = const [];
        _searched = false;
        _error = null;
        _searching = false;
      });
      return;
    }
    _debounce?.cancel();
    final seq = ++_searchSeq;
    setState(() {
      _searching = true;
      _error = null;
    });
    try {
      final items = await apiClient.searchPlaces(
        keyword: keyword,
        lat: _center.lat,
        lng: _center.lng,
      );
      // 过期的响应直接丢弃：用户可能已经改了关键词并发了新请求。
      if (!mounted || seq != _searchSeq) return;
      setState(() {
        _searched = true;
        _results = items;
        // 不自动选中任何一条，也不移动地图中心：
        // 用户点哪条才选中哪条；不点则确认时使用输入的名称。
        _selected = null;
      });
    } on ApiException catch (error) {
      if (!mounted || seq != _searchSeq) return;
      setState(() {
        _selected = null;
        _results = const [];
        _searched = true;
        // 地图服务不可用时，不阻塞用户：仍然可以确认使用手写的名称。
        _error = error.status == 503
            ? '地图服务暂时不可用，可以直接确认使用输入的名称'
            : error.message;
      });
    } finally {
      if (mounted && seq == _searchSeq) {
        setState(() => _searching = false);
      }
    }
  }

  Future<void> _locate() async {
    final coords = await currentLocationIfPermitted();
    if (!mounted) return;
    if (coords == null) {
      showMessage(context, '没有获取到当前位置，请检查手机定位是否开启');
      return;
    }
    setState(() {
      _center = coords;
      _zoom = 16;
      // 回到当前位置后，之前选中的店铺已经和地图中心不一致，
      // 清掉结果和候选列表，避免用户确认一个地图上看不到的店铺。
      _selected = null;
      _results = const [];
      _searched = false;
      _error = null;
    });
  }

  void _changeZoom(int delta) {
    final next = (_zoom + delta).clamp(12, 18);
    if (next == _zoom) return;
    setState(() => _zoom = next);
  }

  /// 点击结果列表里的某一项：设为最终选择，并把地图中心移到该地点。
  void _selectPlace(Place place) {
    setState(() {
      _selected = place;
      _center = Coordinates(lat: place.lat, lng: place.lng);
      _zoom = 16;
    });
  }

  /// 结果列表里的单条地点。
  /// 整行都包在 GestureDetector 里，点名称、地址或距离任意位置都能选中。
  Widget _resultTile(Place place) {
    final isSelected = identical(place, _selected);
    return GestureDetector(
      onTap: () => _selectPlace(place),
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: isSelected ? AppColors.peach : AppColors.bg,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: isSelected ? AppColors.primary : Colors.transparent,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              place.name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w700,
                color: isSelected ? AppColors.primary : AppColors.text,
              ),
            ),
            if (place.address.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                place.address,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 12,
                  color: AppColors.muted,
                  height: 1.4,
                ),
              ),
            ],
            if (distanceLabel(place.distanceMeters).isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                '距当前位置 ${distanceLabel(place.distanceMeters)}',
                style: const TextStyle(fontSize: 11, color: AppColors.faint),
              ),
            ],
          ],
        ),
      ),
    );
  }

  /// 确认使用。
  ///
  /// 规则：用户点过哪条结果，就提交哪条；一条都没点，就提交输入框里的名称。
  void _confirm() {
    final selected = _selected;
    if (selected != null) {
      Navigator.of(context).pop(
        StoreMapResult(
          name: selected.name,
          address: selected.address,
          place: selected,
        ),
      );
      return;
    }
    final keyword = _keyword.text.trim();
    if (keyword.isEmpty) {
      showMessage(context, '请输入店铺名称');
      return;
    }
    // 没有点击任何候选时，直接把输入的名称带回去；
    // 坐标为空，发布页不会生成店铺坐标。
    Navigator.of(context).pop(StoreMapResult(name: keyword, address: ''));
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    final ratio = MediaQuery.devicePixelRatioOf(context);
    // 静态地图接口限制宽高最大 1024（地图服务本身也限制免费额度下的图片尺寸）。
    // 用物理像素请求，屏幕上的地图才不会模糊。
    // 宽高必须按同一个比例缩放，否则会把地图拉伸变形；
    // 超过上限时取“长边不超过 1024”的统一缩放系数。
    final rawWidth = size.width * ratio;
    final rawHeight = size.height * ratio;
    final scale = min(1.0, 1024 / max(rawWidth, rawHeight));
    final mapWidth = (rawWidth * scale).round().clamp(100, 1024);
    final mapHeight = (rawHeight * scale).round().clamp(100, 1024);
    final mapUrl = apiClient.staticMapUrl(
      lat: _center.lat,
      lng: _center.lng,
      zoom: _zoom,
      width: mapWidth,
      height: mapHeight,
    );

    return Scaffold(
      backgroundColor: AppColors.bg,
      // 全屏地图不能跟随键盘缩小：底部面板自己用 viewInsets 抬高。
      // 否则输入法残留时，主体会被压成只剩面板高度，地图和顶部栏都会被盖住。
      resizeToAvoidBottomInset: false,
      // Scaffold 的 body 给的是宽松约束，Stack 默认会缩到非定位子组件的高度。
      // 这里用 SizedBox.expand 强制撑满，否则地图和底部面板会被压到屏幕顶部。
      body: SizedBox.expand(
        child: Stack(
          children: [
          Positioned.fill(
            child: Image.network(
              mapUrl,
              // key 绑定 URL：中心点或缩放变化时 URL 会变，图片随之重新请求。
              key: ValueKey(mapUrl),
              fit: BoxFit.cover,
              loadingBuilder: (context, child, progress) {
                if (progress == null) return child;
                return const ColoredBox(
                  color: AppColors.peach,
                  child: Center(
                    child: CircularProgressIndicator(color: AppColors.primary),
                  ),
                );
              },
              errorBuilder: (_, _, _) => const ColoredBox(
                color: AppColors.peach,
                child: Center(
                  child: Padding(
                    padding: EdgeInsets.all(24),
                    child: Text(
                      '地图加载失败\n可以直接输入店铺名称后确认',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontSize: 13,
                        color: AppColors.muted,
                        height: 1.6,
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
          // 地图中心的定位标记：静态图不能拖动，标记固定在屏幕中心，
          // 地图中心点是什么位置，标记就指向它。
          Positioned.fill(
            child: IgnorePointer(
              child: Align(
                alignment: Alignment.center,
                child: Transform.translate(
                  offset: const Offset(0, -16),
                  child: const Icon(
                    Icons.location_on,
                    size: 40,
                    color: AppColors.primary,
                    shadows: [
                      Shadow(color: Colors.black26, blurRadius: 6),
                    ],
                  ),
                ),
              ),
            ),
          ),
          SafeArea(
            bottom: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
              child: Row(
                children: [
                  _roundButton(
                    icon: Icons.arrow_back,
                    onTap: () => Navigator.of(context).pop(),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 10,
                      ),
                      decoration: BoxDecoration(
                        color: AppColors.card.withValues(alpha: 0.94),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Text(
                        widget.title,
                        style: const TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w700,
                          color: AppColors.text,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          Positioned(
            right: 12,
            top: size.height * 0.32,
            child: Column(
              children: [
                _roundButton(
                  icon: Icons.add,
                  onTap: () => _changeZoom(1),
                ),
                const SizedBox(height: 8),
                _roundButton(
                  icon: Icons.remove,
                  onTap: () => _changeZoom(-1),
                ),
                const SizedBox(height: 16),
                _roundButton(
                  icon: Icons.my_location,
                  onTap: _locate,
                ),
              ],
            ),
          ),
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: _bottomPanel(),
          ),
          ],
        ),
      ),
    );
  }

  Widget _roundButton({required IconData icon, required VoidCallback onTap}) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        width: 40,
        height: 40,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: AppColors.card.withValues(alpha: 0.94),
          shape: BoxShape.circle,
          boxShadow: const [
            BoxShadow(color: Colors.black12, blurRadius: 6, offset: Offset(0, 2)),
          ],
        ),
        child: Icon(icon, size: 20, color: AppColors.text),
      ),
    );
  }

  Widget _bottomPanel() {
    // 键盘弹出时面板整体上移，可用的垂直空间变少，结果列表要相应压矮，
    // 否则输入框、结果列表和确认按钮会一起超出屏幕。
    final keyboardInset = MediaQuery.viewInsetsOf(context).bottom;
    final listHeight = keyboardInset > 0 ? 140.0 : 220.0;
    return Container(
      padding: EdgeInsets.fromLTRB(16, 16, 16, 16 + keyboardInset),
      decoration: const BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        boxShadow: [
          BoxShadow(color: Colors.black12, blurRadius: 12, offset: Offset(0, -2)),
        ],
      ),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _keyword,
                    textInputAction: TextInputAction.search,
                    onChanged: _onKeywordChanged,
                    onSubmitted: (_) => _search(),
                    decoration: InputDecoration(
                      filled: true,
                      fillColor: AppColors.bg,
                      hintText: '输入店铺名称或地址',
                      hintStyle: const TextStyle(
                        fontSize: 13,
                        color: AppColors.faint,
                      ),
                      prefixIcon: const Icon(
                        Icons.search,
                        size: 20,
                        color: AppColors.muted,
                      ),
                      contentPadding: const EdgeInsets.symmetric(vertical: 12),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide.none,
                      ),
                    ),
                    style: const TextStyle(fontSize: 14, color: AppColors.text),
                  ),
                ),
                const SizedBox(width: 8),
                GestureDetector(
                  onTap: _searching ? null : _search,
                  behavior: HitTestBehavior.opaque,
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 13,
                    ),
                    decoration: BoxDecoration(
                      color: AppColors.primary,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      _searching ? '搜索中' : '搜索',
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
            if (_searching) ...[
              const SizedBox(height: 10),
              const LinearProgressIndicator(
                minHeight: 2,
                color: AppColors.primary,
                backgroundColor: AppColors.peach,
              ),
            ],
            if (_results.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(
                '找到 ${_results.length} 个相关地点：点击选中；不选则使用输入的名称',
                style: const TextStyle(fontSize: 12, color: AppColors.muted),
              ),
              const SizedBox(height: 8),
              ConstrainedBox(
                constraints: BoxConstraints(maxHeight: listHeight),
                child: ListView.separated(
                  shrinkWrap: true,
                  itemCount: _results.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 8),
                  itemBuilder: (context, index) => _resultTile(_results[index]),
                ),
              ),
            ] else if (_searched) ...[
              const SizedBox(height: 10),
              Text(
                _error ?? '地图里没找到这个店铺，确认后将直接使用你输入的名称',
                style: const TextStyle(
                  fontSize: 12,
                  color: AppColors.muted,
                  height: 1.5,
                ),
              ),
            ] else ...[
              const SizedBox(height: 10),
              const Text(
                '输入后会停顿 1 秒自动搜索，也可以直接点“搜索”。',
                style: TextStyle(fontSize: 12, color: AppColors.faint),
              ),
            ],
            const SizedBox(height: 14),
            GestureDetector(
              onTap: _confirm,
              behavior: HitTestBehavior.opaque,
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 14),
                decoration: BoxDecoration(
                  color: AppColors.primary,
                  borderRadius: BorderRadius.circular(999),
                ),
                child: const Text(
                  '确认使用',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    color: Colors.white,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
