import 'package:flutter_test/flutter_test.dart';

import 'package:mealmate/theme/app_theme.dart';

void main() {
  test('主题使用品牌主色', () {
    expect(buildAppTheme().colorScheme.primary, AppColors.primary);
  });
}
