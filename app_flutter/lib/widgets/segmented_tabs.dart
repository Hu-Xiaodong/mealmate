import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

class SegmentOption<T> {
  const SegmentOption(this.value, this.label);

  final T value;
  final String label;
}

class SegmentedTabs<T> extends StatelessWidget {
  const SegmentedTabs({
    super.key,
    required this.options,
    required this.selected,
    required this.onSelected,
    this.trackColor = const Color(0xFFECECEE),
  });

  final List<SegmentOption<T>> options;
  final T selected;
  final ValueChanged<T> onSelected;
  final Color trackColor;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: trackColor,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        children: [
          for (final option in options)
            Expanded(
              child: GestureDetector(
                onTap: () => onSelected(option.value),
                behavior: HitTestBehavior.opaque,
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 160),
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  decoration: BoxDecoration(
                    color: option.value == selected
                        ? AppColors.card
                        : Colors.transparent,
                    borderRadius: BorderRadius.circular(999),
                    boxShadow: option.value == selected
                        ? const [
                            BoxShadow(
                              color: Color(0x14242424),
                              blurRadius: 8,
                              offset: Offset(0, 2),
                            ),
                          ]
                        : null,
                  ),
                  child: Text(
                    option.label,
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 13,
                      color: option.value == selected
                          ? AppColors.primaryDeep
                          : AppColors.muted,
                      fontWeight: option.value == selected
                          ? FontWeight.w600
                          : FontWeight.w400,
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
