// AuraView Fleet — minimal smoke test.
// 카메라/네트워크는 테스트 환경에서 의존성이 크므로,
// 앱이 일단 빌드되고 첫 프레임이 그려지는지만 확인합니다.

import 'package:flutter_test/flutter_test.dart';

import 'package:auraview_fleet/main.dart';

void main() {
  testWidgets('AuraViewFleetApp builds', (WidgetTester tester) async {
    await tester.pumpWidget(const AuraViewFleetApp());
    expect(find.byType(AuraViewFleetApp), findsOneWidget);
  });
}
