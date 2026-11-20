import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

class AppHeader extends StatelessWidget {
  const AppHeader({
    super.key,
    this.title,
    this.subtitle,
    this.showBack = false,
    this.action,
  });

  /// 页面标题。现在各页面统一不显示大标题，默认传空；
  /// 只在确实需要区分页面时再传。
  final String? title;
  final String? subtitle;
  final bool showBack;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final hasTitle = title != null && title!.isNotEmpty;
    final hasSubtitle = subtitle != null && subtitle!.isNotEmpty;
    // 没有标题、说明和返回按钮时，整个页头不占高度。
    if (!hasTitle && !hasSubtitle && !showBack && action == null) {
      return const SizedBox.shrink();
    }
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 10, 20, 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          if (showBack) ...[
            GestureDetector(
              onTap: () => Navigator.of(context).maybePop(),
              behavior: HitTestBehavior.opaque,
              child: Container(
                width: 34,
                height: 34,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: AppColors.card,
                  borderRadius: BorderRadius.circular(17),
                  boxShadow: const [
                    BoxShadow(
                      color: Color(0x0D000000),
                      blurRadius: 8,
                      offset: Offset(0, 2),
                    ),
                  ],
                ),
                child: const Icon(
                  Icons.chevron_left,
                  size: 22,
                  color: AppColors.text,
                ),
              ),
            ),
            const SizedBox(width: 12),
          ],
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (hasTitle)
                  Text(
                    title!,
                    style: const TextStyle(
                      fontSize: 26,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 0.5,
                      color: AppColors.text,
                    ),
                  ),
                if (hasSubtitle)
                  Padding(
                    padding: EdgeInsets.only(top: hasTitle ? 2 : 0),
                    child: Text(
                      subtitle!,
                      style: const TextStyle(
                        fontSize: 13,
                        color: AppColors.muted,
                      ),
                    ),
                  ),
              ],
            ),
          ),
          if (action != null) ...[const SizedBox(width: 12), action!],
        ],
      ),
    );
  }
}
