import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/api_client.dart';
import '../core/format.dart';
import '../session/session_store.dart';
import '../theme/app_theme.dart';
import '../widgets/app_header.dart';
import '../widgets/common.dart';

class LoginPage extends StatefulWidget {
  const LoginPage({super.key});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final TextEditingController _phone = TextEditingController();
  final TextEditingController _code = TextEditingController();

  String _challengeId = '';
  String _devCode = '';
  bool _agreed = false;
  bool _sending = false;
  bool _submitting = false;
  int _countdown = 0;
  Timer? _timer;

  @override
  void dispose() {
    _timer?.cancel();
    _phone.dispose();
    _code.dispose();
    super.dispose();
  }

  void _startCountdown(int seconds) {
    _timer?.cancel();
    setState(() => _countdown = seconds < 0 ? 0 : seconds);
    _timer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) {
        timer.cancel();
        return;
      }
      setState(() {
        _countdown -= 1;
        if (_countdown <= 0) {
          _countdown = 0;
          timer.cancel();
        }
      });
    });
  }

  Future<void> _sendCode() async {
    if (_sending || _countdown > 0) return;
    final phone = _phone.text.trim();
    if (!RegExp(r'^1\d{10}$').hasMatch(phone)) {
      showMessage(context, '请输入正确的手机号');
      return;
    }
    setState(() => _sending = true);
    try {
      final result = await apiClient.sendSmsCode(phone);
      if (!mounted) return;
      setState(() {
        _challengeId = result.challengeId;
        _devCode = result.devCode ?? '';
        if (result.devCode != null && result.devCode!.isNotEmpty) {
          _code.text = result.devCode!;
        }
      });
      _startCountdown(result.retryAfter);
      showMessage(context, '验证码已发送');
    } on ApiException catch (error) {
      if (!mounted) return;
      if (error.code == 'SMS_RATE_LIMITED') {
        final data = error.data;
        final retry = data is Map ? data['retryAfter'] : null;
        _startCountdown(retry is num ? retry.toInt() : 60);
      }
      showError(context, error);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _submit() async {
    if (_submitting) return;
    if (_challengeId.isEmpty) {
      showMessage(context, '请先获取验证码');
      return;
    }
    if (!RegExp(r'^\d{6}$').hasMatch(_code.text.trim())) {
      showMessage(context, '请输入 6 位验证码');
      return;
    }
    if (!_agreed) {
      showMessage(context, '请先阅读并同意用户协议与隐私说明');
      return;
    }
    setState(() => _submitting = true);
    try {
      final result = await apiClient.login(
        challengeId: _challengeId,
        code: _code.text.trim(),
        agreementAccepted: true,
      );
      await sessionStore.apply(result);
      if (!mounted) return;
      showMessage(context, result.isNewAccount ? '欢迎加入' : '登录成功');
      Navigator.of(context).pop(true);
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
              title: '手机号登录',
              subtitle: '登录后可点赞、收藏与发布',
              showBack: true,
            ),
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _hero(),
                    const SizedBox(height: 14),
                    _form(),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _hero() {
    return Container(
      padding: const EdgeInsets.fromLTRB(22, 24, 22, 24),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(AppRadius.lg),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFFFFF3EE), Colors.white],
          stops: [0.0, 0.7],
        ),
        boxShadow: const [
          BoxShadow(
            color: Color(0x0D242424),
            blurRadius: 18,
            offset: Offset(0, 6),
          ),
        ],
      ),
      child: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'MealMate',
            style: TextStyle(
              fontSize: 24,
              fontWeight: FontWeight.w700,
              color: AppColors.primaryDeep,
            ),
          ),
          SizedBox(height: 8),
          Text(
            '用手机号快速登录，未注册的号码会自动创建账号。',
            style: TextStyle(
              fontSize: 13,
              color: AppColors.muted,
              height: 1.6,
            ),
          ),
        ],
      ),
    );
  }

  Widget _form() {
    return Container(
      padding: const EdgeInsets.all(22),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        boxShadow: const [
          BoxShadow(
            color: Color(0x0D242424),
            blurRadius: 18,
            offset: Offset(0, 6),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _FieldLabel('手机号'),
          const SizedBox(height: 8),
          TextField(
            controller: _phone,
            keyboardType: TextInputType.phone,
            inputFormatters: [
              FilteringTextInputFormatter.digitsOnly,
              LengthLimitingTextInputFormatter(11),
            ],
            style: const TextStyle(fontSize: 16, color: AppColors.text),
            decoration: _inputDecoration('请输入 11 位手机号'),
          ),
          const SizedBox(height: 18),
          const _FieldLabel('验证码'),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _code,
                  keyboardType: TextInputType.number,
                  inputFormatters: [
                    FilteringTextInputFormatter.digitsOnly,
                    LengthLimitingTextInputFormatter(6),
                  ],
                  style: const TextStyle(fontSize: 16, color: AppColors.text),
                  decoration: _inputDecoration('6 位验证码'),
                ),
              ),
              const SizedBox(width: 10),
              GestureDetector(
                onTap: _sendCode,
                behavior: HitTestBehavior.opaque,
                child: Opacity(
                  opacity: _countdown > 0 || _sending ? 0.6 : 1,
                  child: Container(
                    height: 44,
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: AppColors.peach,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      _countdown > 0 ? '$_countdown s 后重试' : '获取验证码',
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: AppColors.primaryDeep,
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
          if (_devCode.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              '开发环境验证码 $_devCode，已自动填入',
              style: const TextStyle(fontSize: 12, color: AppColors.primary),
            ),
          ],
          const SizedBox(height: 18),
          GestureDetector(
            onTap: () => setState(() => _agreed = !_agreed),
            behavior: HitTestBehavior.opaque,
            child: Row(
              children: [
                Container(
                  width: 18,
                  height: 18,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: _agreed ? AppColors.primary : Colors.transparent,
                    shape: BoxShape.circle,
                    border: Border.all(
                      color: _agreed ? AppColors.primary : AppColors.line,
                    ),
                  ),
                  child: _agreed
                      ? const Icon(Icons.check, size: 12, color: Colors.white)
                      : null,
                ),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text(
                    '我已阅读并同意《用户协议》与《隐私说明》',
                    style: TextStyle(
                      fontSize: 12,
                      color: AppColors.muted,
                      height: 1.5,
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 18),
          PrimaryButton(
            label: _submitting ? '登录中…' : '登录 / 注册',
            busy: _submitting,
            onTap: _submit,
          ),
          const SizedBox(height: 12),
          const Text(
            '验证码 5 分钟内有效，连续输错 5 次需重新获取。',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 12, color: AppColors.faint),
          ),
        ],
      ),
    );
  }

  InputDecoration _inputDecoration(String hint) {
    return InputDecoration(
      filled: true,
      fillColor: AppColors.bg,
      hintText: hint,
      hintStyle: const TextStyle(fontSize: 14, color: AppColors.faint),
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      counterText: '',
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

class _FieldLabel extends StatelessWidget {
  const _FieldLabel(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(fontSize: 13, color: AppColors.muted),
    );
  }
}
