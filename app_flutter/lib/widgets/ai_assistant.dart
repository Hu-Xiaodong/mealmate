import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../core/analytics.dart';
import '../core/format.dart';
import '../pages/recipe_detail_page.dart';
import '../theme/app_theme.dart';

/// 「问 AI」悬浮按钮的纯视觉部分，交互由 [DraggableAiFab] 负责。
class AiFabButton extends StatelessWidget {
  const AiFabButton({super.key, this.dockedSide});

  /// 贴边收起后只露出靠屏幕内侧的一小截；为空表示完整展开。
  final String? dockedSide;

  @override
  Widget build(BuildContext context) {
    final docked = dockedSide != null;
    return Container(
      width: 48,
      height: 48,
      alignment: docked
          ? (dockedSide == 'right'
                ? Alignment.centerLeft
                : Alignment.centerRight)
          : Alignment.center,
      padding: docked
          ? EdgeInsets.only(
              left: dockedSide == 'right' ? 3 : 0,
              right: dockedSide == 'left' ? 3 : 0,
            )
          : EdgeInsets.zero,
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.line),
        boxShadow: const [
          BoxShadow(
            color: Color(0x1A242424),
            blurRadius: 14,
            offset: Offset(0, 3),
          ),
        ],
      ),
      child: docked
          ? const _AiIcon()
          : const Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                _AiIcon(),
                Text(
                  '问 AI',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w500,
                    height: 1.1,
                    color: AppColors.primary,
                  ),
                ),
              ],
            ),
    );
  }
}

class _AiIcon extends StatelessWidget {
  const _AiIcon();

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 24,
      height: 23,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          const Icon(Icons.soup_kitchen, size: 23, color: AppColors.primary),
          Positioned(
            right: -4,
            top: -3,
            child: Container(
              width: 12,
              height: 12,
              decoration: const BoxDecoration(
                color: AppColors.card,
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.auto_awesome,
                size: 11,
                color: AppColors.primary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 可拖动的 AI 悬浮按钮：长按后拖动，松手时靠近左右边缘会自动收起成小把手。
class DraggableAiFab extends StatefulWidget {
  const DraggableAiFab({super.key, required this.onTap, this.onDragStart});

  final VoidCallback onTap;

  /// 开始拖动时通知外层：首页据此取消“首次 AI 提示”的等待。
  final VoidCallback? onDragStart;

  @override
  State<DraggableAiFab> createState() => _DraggableAiFabState();
}

class _DraggableAiFabState extends State<DraggableAiFab> {
  static const double _size = 48;
  static const double _peek = 30;
  static const double _margin = 12;
  static const double _dockZone = 44;

  Offset? _position;
  Offset _dragOrigin = Offset.zero;
  Offset _pointerOrigin = Offset.zero;
  bool _dragging = false;
  String? _dockedSide;

  Offset _clamp(Offset value, double maxWidth, double maxHeight) {
    // 首帧布局时父级可能还没拿到尺寸（宽高为 0），
    // 此时 maxWidth - _size 是负数，直接 clamp 会抛 ArgumentError。
    // 因此上下界都要先保证“上界不小于下界 0”。
    final maxX = maxWidth > _size ? maxWidth - _size : 0.0;
    final maxY = maxHeight > _size ? maxHeight - _size : 0.0;
    return Offset(value.dx.clamp(0.0, maxX), value.dy.clamp(0.0, maxY));
  }

  Offset _resolved(double maxWidth, double maxHeight) {
    // 纵向可移动范围同样要在尺寸不足时退化为 0，避免负数上界。
    final maxY = maxHeight > _size ? maxHeight - _size : 0.0;
    if (_dockedSide == 'left') {
      return Offset(
        _peek - _size,
        (_position?.dy ?? maxY - _margin).clamp(0.0, maxY),
      );
    }
    if (_dockedSide == 'right') {
      return Offset(
        maxWidth - _peek,
        (_position?.dy ?? maxY - _margin).clamp(0.0, maxY),
      );
    }
    return _clamp(
      _position ??
          Offset(maxWidth - _size - _margin, maxHeight - _size - _margin),
      maxWidth,
      maxHeight,
    );
  }

  void _startDrag(
    LongPressStartDetails details,
    double maxWidth,
    double maxHeight,
  ) {
    final current = _resolved(maxWidth, maxHeight);
    final expanded = _dockedSide == null
        ? current
        : _clamp(
            Offset(
              _dockedSide == 'left' ? _margin : maxWidth - _size - _margin,
              current.dy,
            ),
            maxWidth,
            maxHeight,
          );
    HapticFeedback.mediumImpact();
    widget.onDragStart?.call();
    setState(() {
      _dragging = true;
      _dockedSide = null;
      _position = expanded;
      _dragOrigin = expanded;
      _pointerOrigin = details.globalPosition;
    });
  }

  void _moveDrag(
    LongPressMoveUpdateDetails details,
    double maxWidth,
    double maxHeight,
  ) {
    if (!_dragging) return;
    final next = _dragOrigin + (details.globalPosition - _pointerOrigin);
    setState(() => _position = _clamp(next, maxWidth, maxHeight));
  }

  void _endDrag(double maxWidth, double maxHeight) {
    final position = _position;
    if (position == null) return;
    final nearLeft = position.dx <= _dockZone;
    final nearRight = position.dx >= maxWidth - _size - _dockZone;
    setState(() {
      _dragging = false;
      if (nearLeft) {
        _dockedSide = 'left';
        _position = Offset(_peek - _size, position.dy);
      } else if (nearRight) {
        _dockedSide = 'right';
        _position = Offset(maxWidth - _peek, position.dy);
      } else {
        _dockedSide = null;
        _position = _clamp(position, maxWidth, maxHeight);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final maxWidth = constraints.maxWidth;
        final maxHeight = constraints.maxHeight;
        final position = _resolved(maxWidth, maxHeight);
        return Stack(
          children: [
            AnimatedPositioned(
              duration: _dragging
                  ? Duration.zero
                  : const Duration(milliseconds: 180),
              curve: Curves.easeOutCubic,
              left: position.dx,
              top: position.dy,
              child: GestureDetector(
                onTap: widget.onTap,
                onLongPressStart: (details) =>
                    _startDrag(details, maxWidth, maxHeight),
                onLongPressMoveUpdate: (details) =>
                    _moveDrag(details, maxWidth, maxHeight),
                onLongPressEnd: (_) => _endDrag(maxWidth, maxHeight),
                onLongPressCancel: () => _endDrag(maxWidth, maxHeight),
                child: AnimatedScale(
                  scale: _dragging ? 1.08 : 1,
                  duration: const Duration(milliseconds: 120),
                  child: AiFabButton(dockedSide: _dockedSide),
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

/// 打开 AI 对话面板。
///
/// [contextType] 决定开场白和“正在聊”的对象：
/// 首页是帮你选饭，菜谱列表是帮你从现有食材里挑菜，
/// 饭帖详情是就着当前这条饭帖继续帮你补充搭配。
/// [contextId] 是可选的具体对象标识（例如饭帖主键），
/// 传给后端后可以让推荐更贴近当前内容。
Future<void> showAiChatSheet(
  BuildContext context, {
  String contextType = 'home',
  String? contextId,
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (_) =>
        _AiChatSheet(contextType: contextType, contextId: contextId),
  );
}

class _ChatMessage {
  const _ChatMessage({
    required this.text,
    this.fromUser = false,
    this.recommendations = const [],
  });

  final String text;
  final bool fromUser;
  final List<AIRecommendation> recommendations;
}

class _AiChatSheet extends StatefulWidget {
  const _AiChatSheet({required this.contextType, this.contextId});

  final String contextType;

  /// 当前对话针对的具体对象，例如饭帖详情页传入的饭帖主键。
  final String? contextId;

  @override
  State<_AiChatSheet> createState() => _AiChatSheetState();
}

class _AiChatSheetState extends State<_AiChatSheet> {
  static const _homeGreeting = '今天想吃什么？告诉我口味、预算或能用多久，我帮你缩小选择。也可以直接说家里有什么食材。';
  static const _recipeListGreeting = '想用手里的食材做点什么？告诉我食材、器具和时间，我从平台菜谱里帮你挑。';
  static const _postGreeting = '就着这条饭帖继续聊：告诉我你还缺什么、有多少时间，我从平台菜谱里帮你补几道搭配。';

  /// 三个入口的引导问题不同，避免看起来像同一个功能。
  List<String> get _prompts {
    if (widget.contextType == 'recipe_list') {
      return const ['有番茄和鸡蛋做什么', '15 分钟能搞定的菜'];
    }
    if (widget.contextType == 'post') {
      return const ['这条还能配点什么', '15 分钟能加一道菜吗'];
    }
    return const ['帮我选一顿', '家里有番茄和鸡蛋'];
  }

  String get _greeting {
    if (widget.contextType == 'recipe_list') return _recipeListGreeting;
    if (widget.contextType == 'post') return _postGreeting;
    return _homeGreeting;
  }

  String get _contextLabel {
    if (widget.contextType == 'recipe_list') return '菜谱 · 帮你挑菜';
    if (widget.contextType == 'post') return '饭帖 · 就着这条聊';
    return '首页 · 帮你选饭';
  }

  /// 埋点里的页面名：同一个面板被多个页面复用，按入口还原真实页面。
  String get _pageName {
    if (widget.contextType == 'recipe_list') return 'recipes';
    if (widget.contextType == 'post') return 'post_detail';
    return 'home';
  }

  final TextEditingController _controller = TextEditingController();
  final ScrollController _scroll = ScrollController();
  late final List<_ChatMessage> _messages = [_ChatMessage(text: _greeting)];

  bool _sending = false;
  int? _remaining;

  @override
  void dispose() {
    _controller.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _send(String raw) async {
    final message = raw.trim();
    if (message.isEmpty || _sending) return;
    _controller.clear();
    setState(() {
      _messages.add(_ChatMessage(text: message, fromUser: true));
    });
    _scrollToEnd();

    final stopwatch = Stopwatch()..start();
    setState(() => _sending = true);
    try {
      final result = await apiClient.aiChat(
        contextType: widget.contextType,
        contextId: widget.contextId,
        message: message,
      );
      if (!mounted) return;
      setState(() {
        _messages.add(
          _ChatMessage(
            text: result.message,
            recommendations: result.recommendations,
          ),
        );
        _remaining = result.quota.remaining;
      });
      analytics.track(
        'ai_message_result',
        pageName: _pageName,
        properties: {
          'inputMode': 'text',
          'contextType': widget.contextType,
          'constraintTypes': const <String>[],
          'latencyMs': stopwatch.elapsedMilliseconds,
          'resultCode': 'ok',
        },
      );
      _scrollToEnd();
    } on ApiException catch (error) {
      analytics.track(
        'ai_message_result',
        pageName: _pageName,
        properties: {
          'inputMode': 'text',
          'contextType': widget.contextType,
          'constraintTypes': const <String>[],
          'latencyMs': stopwatch.elapsedMilliseconds,
          'resultCode': '${error.code}',
        },
      );
      analytics.clientError(module: 'ai_chat', errorCode: error.code);
      if (mounted) showError(context, error);
    } finally {
      stopwatch.stop();
      if (mounted) setState(() => _sending = false);
    }
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOut,
      );
    });
  }

  void _openRecipe(String id) {
    analytics.track(
      'ai_recommendation_open',
      pageName: _pageName,
      properties: {
        'conversationRef': '${analytics.sessionRef}-${widget.contextType}',
        'targetType': 'recipe',
        'targetId': id,
      },
    );
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => RecipeDetailPage(recipeId: id, entry: 'ai'),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final media = MediaQuery.of(context);
    final keyboard = media.viewInsets.bottom;
    final preferred = media.size.height * 0.72;
    final available = media.size.height - keyboard - 20;
    return Padding(
      padding: EdgeInsets.only(bottom: keyboard),
      child: Container(
        height: preferred < available ? preferred : available,
        margin: const EdgeInsets.fromLTRB(10, 0, 10, 10),
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: AppColors.line),
          boxShadow: const [
            BoxShadow(
              color: Color(0x26242424),
              blurRadius: 24,
              offset: Offset(0, 4),
            ),
          ],
        ),
        clipBehavior: Clip.antiAlias,
        child: Column(
          children: [
            _header(),
            Expanded(child: _messageList()),
            _composer(),
          ],
        ),
      ),
    );
  }

  Widget _header() {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 10, 8, 8),
      decoration: const BoxDecoration(
        color: AppColors.card,
        border: Border(bottom: BorderSide(color: AppColors.line)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(
                child: Text(
                  '问 AI',
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w500,
                    color: AppColors.text,
                  ),
                ),
              ),
              GestureDetector(
                onTap: () => Navigator.of(context).maybePop(),
                behavior: HitTestBehavior.opaque,
                child: const SizedBox(
                  width: 44,
                  height: 44,
                  child: Icon(Icons.close, size: 18, color: AppColors.muted),
                ),
              ),
            ],
          ),
          const SizedBox(height: 2),
          Text(
            '正在聊：$_contextLabel',
            style: const TextStyle(fontSize: 12, color: AppColors.muted),
          ),
        ],
      ),
    );
  }

  Widget _messageList() {
    return Container(
      color: AppColors.bg,
      child: ListView(
        controller: _scroll,
        padding: const EdgeInsets.all(12),
        children: [
          for (final message in _messages) _bubble(message),
          if (_remaining != null)
            Padding(
              padding: const EdgeInsets.only(top: 2, bottom: 6),
              child: Text(
                '今日剩余 $_remaining 次',
                style: const TextStyle(fontSize: 11, color: AppColors.faint),
              ),
            ),
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final prompt in _prompts)
                  GestureDetector(
                    onTap: () => _send(prompt),
                    behavior: HitTestBehavior.opaque,
                    child: Container(
                      height: 38,
                      padding: const EdgeInsets.symmetric(horizontal: 10),
                      decoration: BoxDecoration(
                        color: AppColors.card,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: AppColors.line),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            prompt,
                            style: const TextStyle(
                              fontSize: 12,
                              color: AppColors.text,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _bubble(_ChatMessage message) {
    final bubble = Container(
      constraints: const BoxConstraints(maxWidth: 330),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: message.fromUser ? AppColors.peach : AppColors.card,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            message.text,
            style: const TextStyle(
              fontSize: 14,
              height: 1.55,
              color: AppColors.text,
            ),
          ),
          if (message.recommendations.isNotEmpty) ...[
            const SizedBox(height: 8),
            for (final item in message.recommendations)
              GestureDetector(
                onTap: () => _openRecipe(item.targetId),
                behavior: HitTestBehavior.opaque,
                child: Container(
                  margin: const EdgeInsets.only(top: 6),
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: AppColors.bg,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Row(
                    children: [
                      ClipRRect(
                        borderRadius: BorderRadius.circular(6),
                        child: SizedBox(
                          width: 44,
                          height: 44,
                          child: resolveMedia(item.coverImage).isEmpty
                              ? Container(
                                  color: AppColors.peach,
                                  child: const Icon(
                                    Icons.ramen_dining,
                                    size: 18,
                                    color: AppColors.primaryDeep,
                                  ),
                                )
                              : Image.network(
                                  resolveMedia(item.coverImage),
                                  fit: BoxFit.cover,
                                  errorBuilder: (_, _, _) => Container(
                                    color: AppColors.peach,
                                    child: const Icon(
                                      Icons.ramen_dining,
                                      size: 18,
                                      color: AppColors.primaryDeep,
                                    ),
                                  ),
                                ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              item.title,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontSize: 13,
                                fontWeight: FontWeight.w500,
                                color: AppColors.text,
                              ),
                            ),
                            if (item.reason.isNotEmpty)
                              Padding(
                                padding: const EdgeInsets.only(top: 2),
                                child: Text(
                                  item.reason,
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                    fontSize: 11,
                                    color: AppColors.muted,
                                  ),
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
        ],
      ),
    );

    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Align(
        alignment: message.fromUser
            ? Alignment.centerRight
            : Alignment.centerLeft,
        child: bubble,
      ),
    );
  }

  Widget _composer() {
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 8, 10, 10),
      decoration: const BoxDecoration(
        color: AppColors.card,
        border: Border(top: BorderSide(color: AppColors.line)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Padding(
            padding: EdgeInsets.only(bottom: 4),
            child: Text(
              '说说想吃什么，我帮你从平台菜谱里挑',
              style: TextStyle(fontSize: 12, color: AppColors.muted),
            ),
          ),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _controller,
                  maxLength: 240,
                  minLines: 1,
                  maxLines: 3,
                  textInputAction: TextInputAction.send,
                  onSubmitted: _send,
                  style: const TextStyle(fontSize: 14, color: AppColors.text),
                  decoration: InputDecoration(
                    counterText: '',
                    filled: true,
                    fillColor: AppColors.bg,
                    hintText: '输入要求…',
                    hintStyle: const TextStyle(
                      fontSize: 13,
                      color: AppColors.faint,
                    ),
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 11,
                    ),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: BorderSide.none,
                    ),
                    enabledBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: BorderSide.none,
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: const BorderSide(
                        color: AppColors.primary,
                        width: 1.2,
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 6),
              GestureDetector(
                onTap: _sending ? null : () => _send(_controller.text),
                behavior: HitTestBehavior.opaque,
                child: Opacity(
                  opacity: _sending ? 0.55 : 1,
                  child: Container(
                    constraints: const BoxConstraints(minHeight: 44),
                    padding: const EdgeInsets.symmetric(horizontal: 14),
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: AppColors.primary,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      _sending ? '思考中' : '发送',
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                        color: Colors.white,
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
