import 'dart:async';
import 'dart:math';

import 'package:flutter/widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/api_client.dart';

/// 客户端埋点上报器。
///
/// 为什么需要它：
/// 产品要判断“看饭 → 打开饭帖 → 收藏/点赞 → 发布/问 AI”这条路径是否顺畅，
/// 但后端业务表只能看到最终结果，看不到过程。埋点就是把这些过程行为
/// 以匿名事件的形式批量送到服务端，再由管理后台聚合成看板。
///
/// 设计原则（与 PRD 4.6 节一致）：
/// 1. 埋点失败不得影响浏览、登录和发布：这里所有网络异常都被吞掉；
/// 2. 批量发送：单批最多 50 条，攒够 10 条或每 10 秒触发一次；
/// 3. eventId 由客户端生成，服务端按它去重，失败重试不会重复计数；
/// 4. 只采集行为与对象编号，不采集手机号、验证码、令牌、评语和地址原文。
class Analytics with WidgetsBindingObserver {
  Analytics._();

  /// 服务端允许单批最多 50 条，客户端不要超过这个值。
  static const int _maxBatch = 50;

  /// 攒到 10 条就立刻发送，兼顾实时性与请求数量。
  static const int _flushThreshold = 10;

  /// 即使不满 10 条，也每 10 秒清一次队列，避免长时间看不到数据。
  static const Duration _flushInterval = Duration(seconds: 10);

  /// 队列上限：断网很久时不能无限占用内存，超出部分直接丢弃。
  static const int _maxQueue = 200;

  static const String _hintShownKey = 'mealmate_ai_hint_shown';
  static const String _aiUsedKey = 'mealmate_ai_used';

  final List<Map<String, Object?>> _pending = [];
  final Random _random = Random();
  bool _flushing = false;
  bool _ready = false;
  String _sessionRef = '';

  /// 本次启动的会话编号，用于把同一次使用过程中的事件串起来。
  String get sessionRef => _sessionRef;

  /// 在 `main()` 中、`runApp` 之前调用一次。
  ///
  /// 这里要等 SharedPreferences 读完才能知道“首页 AI 提示是否已经展示过”，
  /// 所以做成异步初始化，而不是在构造函数里偷偷读。
  Future<void> bootstrap() async {
    _sessionRef =
        's-${DateTime.now().millisecondsSinceEpoch.toRadixString(36)}-${_randomToken(6)}';
    _ready = true;
    WidgetsBinding.instance.addObserver(this);
    // 不保存 Timer 引用：单例和 App 同生命周期，进程结束定时器自然消失。
    Timer.periodic(_flushInterval, (_) => flush());
  }

  /// 记录一个事件。
  ///
  /// [eventName] 必须出现在 PRD 4.6 节的白名单里，否则后端会直接丢弃。
  /// [properties] 只放对象编号、枚举、布尔值和数字，不放自由文本。
  void track(
    String eventName, {
    String? pageName,
    Map<String, Object?> properties = const {},
  }) {
    if (!_ready) return;
    final now = DateTime.now().toUtc();
    _pending.add({
      'eventId': 'e-${now.microsecondsSinceEpoch.toRadixString(36)}-${_randomToken(8)}',
      'eventName': eventName,
      'pageName': pageName,
      'platform': 'flutter',
      'appVersion': '1.0.0',
      'sessionRef': _sessionRef,
      'occurredAt': now.toIso8601String(),
      'properties': properties,
    });
    if (_pending.length >= _flushThreshold) {
      // 不等待结果：调用方通常是点击回调，不能被网络阻塞。
      flush();
    }
  }

  /// 页面曝光快捷方法，同一次进入页面只调用一次。
  void pageView(
    String pageName, {
    String? entry,
    String? targetType,
    String? targetId,
  }) {
    final properties = <String, Object?>{'pageName': pageName};
    if (entry != null) properties['entry'] = entry;
    if (targetType != null) properties['targetType'] = targetType;
    if (targetId != null) properties['targetId'] = targetId;
    track('page_view', pageName: pageName, properties: properties);
  }

  /// 打开 AI 时统一走这里：既记埋点，也把“已经用过 AI”持久化。
  void trackAiOpen({
    required String contextType,
    String? contextId,
    required String entry,
  }) {
    markAiUsed();
    final properties = <String, Object?>{
      'contextType': contextType,
      'entry': entry,
    };
    if (contextId != null) properties['contextId'] = contextId;
    track(
      'ai_open',
      pageName: contextType == 'recipe_list' ? 'recipes' : contextType,
      properties: properties,
    );
  }

  /// 可恢复异常的简版上报。错误文案、手机号、令牌都不能放进来。
  void clientError({
    required String module,
    Object? errorCode,
    String? requestId,
    String? networkState,
  }) {
    final properties = <String, Object?>{'module': module};
    if (errorCode != null) properties['errorCode'] = '$errorCode';
    if (requestId != null) properties['requestId'] = requestId;
    if (networkState != null) properties['networkState'] = networkState;
    track('client_error', properties: properties);
  }

  /// 首页 AI 轻提示是否还应该展示。
  ///
  /// 规则：按设备安装维度只提示一次；只要用户打开过 AI，也不再提示。
  Future<bool> shouldShowAiHint() async {
    final prefs = await SharedPreferences.getInstance();
    if (prefs.getBool(_aiUsedKey) == true) return false;
    return prefs.getBool(_hintShownKey) != true;
  }

  /// 提示实际展示后立刻记为“已展示”，防止切换页面后重复弹出。
  Future<void> markAiHintShown() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_hintShownKey, true);
  }

  /// 用户只要打开过 AI，就永久标记为“已用过”。
  Future<void> markAiUsed() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_aiUsedKey, true);
  }

  /// 把队列里的数据发出去。
  ///
  /// 失败时只把本批放回队首（队列没满的情况下），下一次定时器再试；
  /// 服务端按 eventId 去重，所以偶尔重复不会污染统计。
  Future<void> flush() async {
    if (!_ready || _flushing || _pending.isEmpty) return;
    _flushing = true;
    final batch = _pending.take(_maxBatch).toList(growable: false);
    _pending.removeRange(0, batch.length);
    try {
      await apiClient.reportEvents(batch);
    } catch (_) {
      if (_pending.length + batch.length <= _maxQueue) {
        _pending.insertAll(0, batch);
      }
    } finally {
      _flushing = false;
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // 进后台时尽快把队尾数据送出去，避免用户直接杀进程导致丢失。
    if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached) {
      flush();
    }
  }

  String _randomToken(int length) {
    const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
    return List.generate(
      length,
      (_) => chars[_random.nextInt(chars.length)],
    ).join();
  }
}

/// 全局单例：页面直接 `analytics.track(...)`，不需要层层传对象。
final Analytics analytics = Analytics._();
