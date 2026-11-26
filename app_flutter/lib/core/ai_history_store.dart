import 'dart:convert';
import 'dart:math';

import 'package:shared_preferences/shared_preferences.dart';

import '../api/api_client.dart';

/// 手机本地的一条 AI 消息。
///
/// 为什么消息要有本地唯一编号：
/// 1. 本地记录先在手机上生成，用户即使断网也不会丢；
/// 2. 登录后同步上云时，后端按编号去重，网络重试不会写入两条一样的话；
/// 3. 后端返回自己的消息编号后，本地用同一个编号替换，两边能对上。
class LocalAiMessage {
  LocalAiMessage({
    required this.id,
    required this.role,
    required this.content,
    required this.createdAt,
  });

  String id;
  final String role;
  final String content;
  final DateTime createdAt;

  Map<String, dynamic> toJson() => {
    'id': id,
    'role': role,
    'content': content,
    'createdAt': createdAt.toUtc().toIso8601String(),
  };

  factory LocalAiMessage.fromJson(Map<String, dynamic> json) => LocalAiMessage(
    id: json['id'] as String? ?? '',
    role: json['role'] as String? ?? 'user',
    content: json['content'] as String? ?? '',
    createdAt:
        DateTime.tryParse(json['createdAt'] as String? ?? '')?.toLocal() ??
        DateTime.now(),
  );
}

/// 一段本地 AI 会话。
class LocalAiConversation {
  LocalAiConversation({
    required this.id,
    required this.clientId,
    required this.contextType,
    required this.title,
    required this.messages,
    required this.createdAt,
    required this.updatedAt,
    required this.synced,
  });

  /// 当前使用的会话编号。游客阶段是本地编号，登录同步后替换成云端编号。
  String id;

  /// 本地会话的稳定编号，上传云端时作为幂等键，不随云端编号变化。
  final String clientId;
  final String contextType;
  String title;
  final List<LocalAiMessage> messages;
  final DateTime createdAt;
  DateTime updatedAt;

  /// 是否已经保存到云端。游客创建、尚未合并的会话为 false。
  bool synced;

  Map<String, dynamic> toJson() => {
    'id': id,
    'clientId': clientId,
    'contextType': contextType,
    'title': title,
    'messages': messages.map((item) => item.toJson()).toList(),
    'createdAt': createdAt.toUtc().toIso8601String(),
    'updatedAt': updatedAt.toUtc().toIso8601String(),
    'synced': synced,
  };

  factory LocalAiConversation.fromJson(Map<String, dynamic> json) {
    final rawMessages = json['messages'];
    final messages = rawMessages is List
        ? rawMessages
              .whereType<Map<String, dynamic>>()
              .map(LocalAiMessage.fromJson)
              .toList()
        : <LocalAiMessage>[];
    return LocalAiConversation(
      id: json['id'] as String? ?? '',
      clientId: json['clientId'] as String? ?? '',
      contextType: json['contextType'] as String? ?? 'home',
      title: json['title'] as String? ?? '',
      messages: messages,
      createdAt:
          DateTime.tryParse(json['createdAt'] as String? ?? '')?.toLocal() ??
          DateTime.now(),
      updatedAt:
          DateTime.tryParse(json['updatedAt'] as String? ?? '')?.toLocal() ??
          DateTime.now(),
      synced: json['synced'] as bool? ?? false,
    );
  }
}

/// AI 对话的本地存储。
///
/// 产品方案是“本地为主 + 登录后合并上云”：
/// - 游客的记录只存在手机里，超过 7 天自动删除；
/// - 登录用户的记录本地保留 30 天，同时每次问答都会由服务端保存；
/// - 登录成功时把还没合并的本地记录上传，按客户端消息编号去重。
///
/// 为什么用 SharedPreferences 而不是数据库：
/// 对话数据量小、结构简单，只需要整体读写，不涉及复杂查询；
/// SharedPreferences 是 Flutter 官方提供的键值存储，接入成本最低。
/// 如果以后要做全文搜索、按标签筛选，再换成 SQLite 更合适。
class AiHistoryStore {
  static const _storageKey = 'mealmate_ai_conversations_v1';

  /// 游客本地记录保留天数。
  static const guestRetentionDays = 7;

  /// 登录用户本地记录保留天数，与服务端清理周期一致。
  static const userRetentionDays = 30;

  /// 会话空闲多少分钟后，下次打开不再自动接着聊。
  static const idleMinutes = 30;

  /// 本地最多保留多少段会话，防止 SharedPreferences 无限增长。
  static const maxConversations = 30;

  /// 每段会话最多保存多少条消息（约 100 轮），超出丢弃最早的。
  static const maxMessagesPerConversation = 200;

  final List<LocalAiConversation> _conversations = [];
  bool _loaded = false;

  /// 按最近更新时间倒序，供历史列表展示。
  List<LocalAiConversation> get conversations {
    final items = [..._conversations]
      ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    return List.unmodifiable(items);
  }

  /// 读取本地记录，并按当前身份清理过期数据。
  Future<void> load({required bool isLoggedIn}) async {
    if (!_loaded) {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_storageKey);
      if (raw != null && raw.isNotEmpty) {
        try {
          final decoded = jsonDecode(raw);
          if (decoded is List) {
            for (final item in decoded.whereType<Map<String, dynamic>>()) {
              final conversation = LocalAiConversation.fromJson(item);
              if (conversation.clientId.isNotEmpty) {
                _conversations.add(conversation);
              }
            }
          }
        } on FormatException {
          // 本地数据损坏时直接忽略：对话不是关键业务数据，
          // 不能让一段坏 JSON 导致 AI 面板打不开。
          _conversations.clear();
        }
      }
      _loaded = true;
    }
    await _prune(isLoggedIn: isLoggedIn);
  }

  /// 最近一段仍在“自动续聊”时间内的会话。
  ///
  /// 超过 30 分钟没有操作，按产品定义应该开始新会话；
  /// 旧会话不会删除，仍然可以在历史列表里打开查看。
  LocalAiConversation? latestActiveConversation() {
    final items = conversations;
    if (items.isEmpty) return null;
    final latest = items.first;
    if (DateTime.now().difference(latest.updatedAt).inMinutes >= idleMinutes) {
      return null;
    }
    return latest;
  }

  /// 新建一段本地会话（只在内存里，第一次发消息时才真正使用）。
  LocalAiConversation createConversation(String contextType) {
    final now = DateTime.now();
    final conversation = LocalAiConversation(
      id: '',
      clientId: _newLocalId('local_conv'),
      contextType: contextType,
      title: '',
      messages: [],
      createdAt: now,
      updatedAt: now,
      synced: false,
    );
    _conversations.add(conversation);
    _trimConversationCount();
    return conversation;
  }

  /// 追加一条消息并持久化。
  Future<void> appendMessage(
    LocalAiConversation conversation,
    LocalAiMessage message,
  ) async {
    conversation.messages.add(message);
    if (conversation.messages.length > maxMessagesPerConversation) {
      conversation.messages.removeRange(
        0,
        conversation.messages.length - maxMessagesPerConversation,
      );
    }
    if (conversation.title.isEmpty && message.role == 'user') {
      conversation.title = message.content.trim();
      if (conversation.title.length > 20) {
        conversation.title = '${conversation.title.substring(0, 20)}…';
      }
    }
    conversation.updatedAt = DateTime.now();
    await save();
  }

  /// 把本地记录序列化到 SharedPreferences。
  Future<void> save() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      _storageKey,
      jsonEncode(_conversations.map((item) => item.toJson()).toList()),
    );
  }

  /// 登录后把尚未合并的本地会话上传到云端。
  ///
  /// 返回值是成功合并的会话段数，失败时抛出 ApiException 由调用方决定
  /// 是否提示用户；登录流程本身不应该因为同步失败而中断。
  Future<int> syncToCloud(ApiClient api) async {
    final pending = _conversations
        .where((item) => !item.synced && item.messages.isNotEmpty)
        .toList();
    if (pending.isEmpty) return 0;

    var syncedCount = 0;
    // 后端一次最多接收 20 段会话，这里分批上传，避免登录瞬间请求体过大。
    for (var start = 0; start < pending.length; start += 20) {
      final end = min(start + 20, pending.length);
      final batch = pending.sublist(start, end);
      final data = await api.syncAiConversations([
        for (final conversation in batch)
          {
            'clientConversationId': conversation.clientId,
            'contextType': conversation.contextType,
            'createdAt': conversation.createdAt.toUtc().toIso8601String(),
            'updatedAt': conversation.updatedAt.toUtc().toIso8601String(),
            'messages': [
              for (final message in conversation.messages)
                {
                  'clientMessageId': message.id,
                  'role': message.role,
                  'content': message.content,
                  'createdAt': message.createdAt.toUtc().toIso8601String(),
                },
            ],
          },
      ]);
      final mappings = data['conversations'];
      if (mappings is List) {
        for (final mapping in mappings.whereType<Map<String, dynamic>>()) {
          final clientId = mapping['clientConversationId'] as String? ?? '';
          final cloudId = mapping['conversationId'] as String? ?? '';
          LocalAiConversation? local;
          for (final item in batch) {
            if (item.clientId == clientId) {
              local = item;
              break;
            }
          }
          if (local == null || cloudId.isEmpty) continue;
          local.id = cloudId;
          local.synced = true;
          syncedCount += 1;
        }
      }
      await save();
    }
    return syncedCount;
  }

  Future<void> _prune({required bool isLoggedIn}) async {
    final days = isLoggedIn ? userRetentionDays : guestRetentionDays;
    final cutoff = DateTime.now().subtract(Duration(days: days));
    final before = _conversations.length;
    _conversations.removeWhere(
      (item) => item.messages.isEmpty || item.updatedAt.isBefore(cutoff),
    );
    _trimConversationCount();
    if (_conversations.length != before) {
      await save();
    }
  }

  void _trimConversationCount() {
    if (_conversations.length <= maxConversations) return;
    _conversations.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    _conversations.removeRange(maxConversations, _conversations.length);
  }

  String _newLocalId(String prefix) {
    final random = Random();
    final suffix = List.generate(
      6,
      (_) => 'abcdefghijklmnopqrstuvwxyz0123456789'[random.nextInt(36)],
    ).join();
    return '${prefix}_${DateTime.now().millisecondsSinceEpoch}_$suffix';
  }
}

/// 全局单例：AI 面板和登录流程共用同一份本地记录。
final AiHistoryStore aiHistoryStore = AiHistoryStore();
