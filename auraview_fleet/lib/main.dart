// AuraView Fleet — Flutter client (Android + Web)
//
// 컨슈머 UX 리디자인:
//   - 풀스크린 카메라 프리뷰
//   - 상단: 브랜드 + 연결 점 + 누적 카운터 (간결)
//   - 중앙: 캡처 시 펄스 링 애니메이션 + 살짝 어둡게
//   - 하단: 단일 알약 버튼 (시작 / 정지) — 길게 누르면 1장 즉시 기여
//   - 아래로 스와이프: 상세 시트 (entropy / 교차로 / 통계 / 디바이스)
//
// 백엔드: https://auraview.allthatai.kr/fleet/contribute · /fleet/stats

import 'dart:async';
import 'dart:convert';
import 'dart:io' show File;
import 'dart:math';
import 'dart:math' as math;

import 'package:camera/camera.dart';
import 'package:camera_android_camerax/camera_android_camerax.dart' as cx;
import 'package:camera_platform_interface/camera_platform_interface.dart' show CameraPlatform;
import 'package:flutter/scheduler.dart';
import 'dart:ui' as ui show ImageFilter;
import 'dart:ui' show FontFeature;
import 'package:flutter/foundation.dart' show kIsWeb, WriteBuffer;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:image/image.dart' as img;
import 'package:permission_handler/permission_handler.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:google_mlkit_object_detection/google_mlkit_object_detection.dart';
import 'package:google_mlkit_commons/google_mlkit_commons.dart';
import 'package:google_mlkit_image_labeling/google_mlkit_image_labeling.dart';

const String kApiBase = String.fromEnvironment(
  'AURAVIEW_API_BASE',
  defaultValue: 'https://auraview.allthatai.kr',
);
const Duration kShadowInterval = Duration(seconds: 4);
const double kEntropyThreshold = 0.55;

// ── Theme tokens ──────────────────────────────────────────────────
const _bg = Color(0xFF080C14);
const _surface = Color(0xFF0D1520);
const _surface2 = Color(0xFF121D2E);
const _text = Color(0xFFE2EAF5);
const _muted = Color(0xFF5A7A9A);
const _accent = Color(0xFF00C8FF);
const _accent2 = Color(0xFF7C3AED);
const _safe = Color(0xFF00E09A);
const _danger = Color(0xFFFF3B3B);
const _warn = Color(0xFFFFB020);

late List<CameraDescription> _cameras;

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // v12.7: camera_android_camerax 강제 — Galaxy Z Fold 3 camera2 frame 콜백 안 오는 버그 회피
  if (!kIsWeb) {
    try { CameraPlatform.instance = cx.AndroidCameraCameraX(); } catch (_) {}
  }
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarIconBrightness: Brightness.light,
    systemNavigationBarColor: _bg,
    systemNavigationBarIconBrightness: Brightness.light,
  ));
  try {
    _cameras = await availableCameras();
  } catch (_) {
    _cameras = const [];
  }
  runApp(const AuraViewFleetApp());
}

class AuraViewFleetApp extends StatelessWidget {
  const AuraViewFleetApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AuraView Fleet',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        scaffoldBackgroundColor: _bg,
        colorScheme: const ColorScheme.dark(
          primary: _accent,
          surface: _surface,
          onPrimary: _bg,
          onSurface: _text,
        ),
        useMaterial3: true,
        textTheme: const TextTheme().apply(bodyColor: _text, displayColor: _text),
      ),
      home: const FleetHome(),
    );
  }
}

// ─────────────────────────────────────────────────────────────────
// Home
// ─────────────────────────────────────────────────────────────────

class FleetHome extends StatefulWidget {
  const FleetHome({super.key});
  @override
  State<FleetHome> createState() => _FleetHomeState();
}

class _FleetHomeState extends State<FleetHome>
    with WidgetsBindingObserver, SingleTickerProviderStateMixin {
  CameraController? _cam;
  bool _initing = true;
  bool _showOnboarding = false;    // v5 2026-05-17: 첫 진입 시 3장 PageView 표시
  bool _shadowOn = false;
  Timer? _ticker;
  late AnimationController _pulseAnim;

  String _deviceId = '';
  String? _intersectionId;
  Position? _pos;

  int _captures = 0;
  int _uploads = 0;
  int _failures = 0;
  double _lastEntropy = 0.0;
  String _lastReason = 'idle';
  int _serverTotal = 0;
  String _serverError = '';

  Uint8List? _lastDownsample;
  DateTime? _lastUploadAt;

  // V2V broadcast 상태
  bool _v2vEnabled = true;
  int _v2vSent = 0;
  double? _prevSpeedMps;
  DateTime? _prevSpeedTs;
  StreamSubscription<Position>? _posSub;

  // BEV 오버레이 — 도시정보(신호/VDS/TAAS) 결합 (기본 ON)
  bool _bevOpen = true;
  Map<String, dynamic>? _bev;          // ★ LIVE: 카메라 프레임 → 클라이언트 voxelize 결과 (실시간)
  Map<String, dynamic>? _serverBev;    // ★ DEMO: /occupancy/demo class_grid_flat (시나리오 데모)
  Map<String, dynamic>? _fusion;
  Map<String, dynamic>? _altSignal;       // /signals/{iid}/alternate 응답
  // v2 2026-05-15: BIS 실시간 버스 (반경 150m)
  Map<String, dynamic>? _busLive;
  String? _autoIntersectionId;            // GPS 기반 자동 감지 교차로
  String? _autoIntersectionName;
  Timer? _bevTimer;
  Timer? _scnRotateTimer;
  Timer? _pollServerTimer;        // v5 2026-05-17: leak 방지 위해 인스턴스 보관
  List<double>? _prevFrameGray;  // motion diff 용 이전 프레임

  // ★ ML Kit 객체 검출 (사람/차량 on-device 인식)
  ObjectDetector? _objDetector;
  ImageLabeler? _imgLabeler;   // v12.9: 더 광범위 카테고리 (Person/Car/Dog 등 400+ labels)
  bool _mlkitBusy = false;
  // v12.6: image stream 으로 받는 마지막 프레임 (takePicture 폐기)
  CameraImage? _lastCameraFrame;
  bool _imageStreamRunning = false;
  int _lastStreamProcessAt = 0;

  // v12.12: BEV FPS 카운터 (최근 10 프레임 평균)
  final List<int> _fpsTimes = [];
  double _detectFps = 0.0;
  // v12.12: 총 주행거리 추적 (km)
  Position? _prevPos;
  double _totalKm = 0.0;

  // v12.13: 서버 헬시 체크 — schema 버전, live source 수, 마지막 성공 시각, 재시도 backoff
  String _serverSchema = '';
  int _serverSourceCount = 0;
  int _serverLiveSourceCount = 0;
  DateTime? _lastFusionFetchOk;
  int _fusionRetryDelay = 1500;   // ms, 실패 시 exponential backoff

  // v9.2 2026-05-18: BEV WebView 컨트롤러 (검출 결과를 JS aurDetect() 로 push)
  WebViewController? _bevWvCtrl;
  // v9.3 2026-05-18: ML Kit 검출 결과 보관 (Flutter 네이티브 BEV 오버레이용)
  //   각 항목: { cls, box[x,y,w,h], score, vw, vh }
  List<Map<String, dynamic>> _bevDetections = const [];
  int _bevImgW = 1280, _bevImgH = 720;

  // v11.1 2026-05-19: 검출 파이프라인 디버그 상태 (왜 안 잡히는지 화면에 표시)
  String _detectDebug = '초기화 대기';
  int _detectRawN = 0;
  int _detectKeptN = 0;
  DateTime? _detectLastAt;

  // v12.4 2026-05-19: ML Kit raw 박스 (필터 전) — 카메라에 모두 표시
  //   { box[x,y,w,h], labels: 'A 0.9, B 0.6', kept: true/false, rejReason: '...' }
  List<Map<String, dynamic>> _rawDetections = const [];

  // ★ DEMO 시나리오 모드 — 사용자가 명시적으로 켤 때만 활성 (기본 OFF)
  // OFF: LIVE 모드 — 카메라 frame → 클라이언트 voxel (실제 환경)
  // ON:  DEMO 모드 — 서버 4 시나리오 자동 순환 (실내 시연용)
  bool _demoScenarioOn = false;
  static const _scnList = ['truck_occlusion', 'motorcycle_blindspot', 'signal_occlusion', 'rainy_intersection', 'right_turn_pedestrian', 'school_zone', 'bicycle_lane', 'night_pedestrian'];
  static const _scnLabels = {
    'truck_occlusion': '🚛 트럭 가림',
    'motorcycle_blindspot': '◀ 사각지대 이륜',
    'signal_occlusion': '🚦 버스 뒤 신호',
    'rainy_intersection': '🌧️ 우천',
    'right_turn_pedestrian': '🚸 우회전 보행자',
    'school_zone': '🏫 스쿨존',
    'bicycle_lane': '🚴 자전거 도로',
    'night_pedestrian': '🌙 야간 보행자',
  };
  int _scnIdx = 0;

  // 데모 시드와 동일 — GPS 근접 교차로 매칭용
  static const _knownIntersections = <Map<String, dynamic>>[
    {'id': '1007', 'name': '한양대역 교차로', 'lat': 37.5547, 'lon': 127.1295},
    {'id': '2024', 'name': '강남역 사거리',   'lat': 37.4979, 'lon': 127.0276},
    {'id': '3015', 'name': '광화문 사거리',   'lat': 37.5723, 'lon': 126.9769},
    {'id': '4011', 'name': '잠실역 환승센터', 'lat': 37.5133, 'lon': 127.1000},
    {'id': '5006', 'name': '신촌 로터리',     'lat': 37.5556, 'lon': 126.9367},
    {'id': '6022', 'name': '사당역 사거리',   'lat': 37.4766, 'lon': 126.9816},
    {'id': '7045', 'name': '왕십리역 광장',   'lat': 37.5611, 'lon': 127.0376},
    {'id': '8033', 'name': '건대입구 로데오', 'lat': 37.5403, 'lon': 127.0700},
  ];

  /// v12.16: GPS 좌표 기반 동적 교차로 ID — 어디서든 작동.
  /// 1순위: 800m 내 known 교차로 매칭 (이름 표시 + 정확한 좌표)
  /// 2순위: GPS 그리드 셀 ID 자동 생성 ("gps-{lat3}-{lon3}", 100m 그리드)
  /// → fusion API 항상 호출됨 + bbox 로 정확한 좌표 전달 (서버가 동적 fusion 생성)
  void _autoDetectIntersection() {
    final p = _pos;
    if (p == null) return;
    String? bestId;
    String? bestName;
    double bestDist = 0.8;
    for (final it in _knownIntersections) {
      final dKm = _haversineKm(p.latitude, p.longitude,
          (it['lat'] as num).toDouble(), (it['lon'] as num).toDouble());
      if (dKm < bestDist) {
        bestDist = dKm;
        bestId = it['id'] as String;
        bestName = it['name'] as String;
      }
    }
    // v12.16: known 매칭 실패 시 GPS 그리드 셀 ID 자동 생성 (어디서든 작동)
    if (bestId == null) {
      // 100m grid: lat*1000 / lon*1000 — 충분히 안정적인 셀 ID
      final latIdx = (p.latitude * 1000).round();
      final lonIdx = (p.longitude * 1000).round();
      bestId = 'gps-$latIdx-$lonIdx';
      bestName = '현재 위치 (GPS)';
    }
    if (bestId != _autoIntersectionId && mounted) {
      setState(() {
        _autoIntersectionId = bestId;
        _autoIntersectionName = bestName;
      });
    }
  }

  // 도심 짧은 거리 — 평면 근사로 충분 (1° lat≈111km, 1° lon@37°≈89km)
  static double _haversineKm(double lat1, double lon1, double lat2, double lon2) {
    final dx = (lat2 - lat1) * 111.0;
    final dy = (lon2 - lon1) * 89.0;
    return math.sqrt(dx * dx + dy * dy);
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _pulseAnim = AnimationController(
      vsync: this, duration: const Duration(milliseconds: 900),
    );
    // ML Kit 객체 검출기 초기화 (Android/iOS 만)
    if (!kIsWeb) {
      try {
        // v12.4: stream 모드는 ImageStream 용 — single 로 되돌림 (processImage one-shot 호환)
        _objDetector = ObjectDetector(
          options: ObjectDetectorOptions(
            mode: DetectionMode.stream,
            classifyObjects: true,
            multipleObjects: true,
          ),
        );
        // v12.9: ImageLabeler — 400+ 라벨 (Person, Car, Dog, Phone, Bottle, Plant 등 광범위)
        _imgLabeler = ImageLabeler(options: ImageLabelerOptions(confidenceThreshold: 0.4));
      } catch (_) {/* ML Kit 미지원 — 폴백 사용 */}
    }
    _bootstrap();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _ticker?.cancel();
    _bevTimer?.cancel();
    _scnRotateTimer?.cancel();
    _pollServerTimer?.cancel();
    _posSub?.cancel();
    _cam?.dispose();
    _objDetector?.close();
    _pulseAnim.dispose();
    super.dispose();
  }

  /// DEMO 시나리오 모드 토글 — 사용자가 명시적으로 ON 할 때만 서버 시나리오 사용
  /// 야외 실주행 시 OFF 유지 → 카메라 voxel 만으로 BEV 표시
  void _toggleDemoScenario() {
    HapticFeedback.mediumImpact();
    setState(() {
      _demoScenarioOn = !_demoScenarioOn;
      if (!_demoScenarioOn) _serverBev = null;
    });
    _scnRotateTimer?.cancel();
    if (_demoScenarioOn) {
      _scnIdx = 0;
      _pollDemoScene();
      // 1.5초 주기 — 시나리오 차량 movement (phase) 부드럽게 갱신
      // 8초마다 시나리오 인덱스 변경 (8/1.5 ≈ 5 ticks)
      var tick = 0;
      _scnRotateTimer = Timer.periodic(const Duration(milliseconds: 1500), (_) {
        tick++;
        if (tick % 5 == 0) {
          _scnIdx = (_scnIdx + 1) % _scnList.length;
        }
        _pollDemoScene();
      });
    }
  }

  /// DEMO 시나리오 데이터만 빠르게 폴링 (카메라 캡처 X)
  Future<void> _pollDemoScene() async {
    if (!_demoScenarioOn) return;
    try {
      final scn = _scnList[_scnIdx % _scnList.length];
      final r = await http.get(Uri.parse('$kApiBase/occupancy/demo?scenario=$scn'))
          .timeout(const Duration(seconds: 4));
      if (r.statusCode == 200) {
        final body = jsonDecode(r.body) as Map<String, dynamic>;
        if (mounted) setState(() => _serverBev = body);
      }
    } catch (_) {}
  }

  /// v12.6: takePicture 폐기 (Galaxy Z Fold 3 stuck 회피). 카메라 검출은
  /// startImageStream → _onCameraFrame → _processFrame 으로 진행.
  /// _fetchBev 는 fusion/intersection polling 만 담당.
  Future<void> _fetchBev() async {
    debugPrint('[AURAVIEW] _fetchBev() called (fusion poll only)');
    // 카메라 정보는 stream 으로 갱신되니 skip
    if (false) {  // v12.6: takePicture 경로 비활성
      try {
        final shot = await _cam!.takePicture();
        final bytes = await shot.readAsBytes();
        // 1) voxel grid (edge + motion) 생성 — 100% on-device
        final voxel = _voxelizeOnDevice(bytes);

        // 2) ★ ML Kit on-device 객체 검출 (Google ML Kit, 외부 서버 X)
        //    bbox 크기 필터로 false positive 방지 (≥4% image area)
        if (voxel != null && _objDetector != null && !_mlkitBusy) {
          _mlkitBusy = true;
          try {
            final cg = await _detectObjectsToClassGrid(shot.path, bytes, 40, 40);
            if (cg != null) voxel['class_grid_flat'] = cg;
          } catch (_) {} finally {
            _mlkitBusy = false;
          }
        }

        // 2.5) v12.3: BEV 검출 push — 항상 실행 (WebView 폐기 후 가드 제거)
        //   _pushDetectionsToBev 가 _bevDetections state 를 갱신 → _CameraBevSplit 가 받아 렌더.
        //   (이전 _bevWvCtrl != null 가드가 WebView 제거 후에도 남아있어 push 가 영원히 차단됐던 버그)
        await _pushDetectionsToBev(shot.path, bytes);

        // 3) 임시 파일 정리
        if (!kIsWeb) {
          try { final f = File(shot.path); if (await f.exists()) await f.delete(); } catch (_) {}
        }
        if (voxel != null && mounted) {
          setState(() => _bev = voxel);
        }
      } catch (e) {
        // v12.4 디버그: takePicture 또는 voxelize 예외 화면에 표시
        if (mounted) setState(() => _detectDebug =
          'fetchBev 예외: ${e.toString().substring(0, e.toString().length > 60 ? 60 : e.toString().length)}');
      }
    }
    // 도시정보 결합 (signal/VDS/TAAS) — voxel 위에 라이브 라인 표시용
    // intersection_id 우선순위: 사용자 설정값 → GPS 자동 감지값
    _autoDetectIntersection();
    final iid = (_intersectionId != null && _intersectionId!.isNotEmpty)
        ? _intersectionId!
        : _autoIntersectionId;
    if (iid != null && iid.isNotEmpty) {
      try {
        // v12.16: GPS 가 있으면 bbox 로 정확한 현재 위치 전달 → 서버가 동적 fusion 생성
        //   intersection_id 는 라벨 역할만 (서버 KNOWN_INTERSECTIONS 에 없어도 OK)
        String url = '$kApiBase/fusion/intersection/$iid';
        if (_pos != null) {
          final lat = _pos!.latitude, lon = _pos!.longitude;
          const d = 0.005;   // 약 ±550m bbox
          url += '?bbox_min_lat=${(lat - d).toStringAsFixed(5)}'
                 '&bbox_max_lat=${(lat + d).toStringAsFixed(5)}'
                 '&bbox_min_lon=${(lon - d).toStringAsFixed(5)}'
                 '&bbox_max_lon=${(lon + d).toStringAsFixed(5)}';
        }
        final r = await http.get(Uri.parse(url))
            .timeout(const Duration(seconds: 6));
        if (r.statusCode == 200) {
          final body = jsonDecode(r.body) as Map<String, dynamic>;
          if (mounted) setState(() {
            _fusion = body;
            _lastFusionFetchOk = DateTime.now();
            _fusionRetryDelay = 1500;   // v12.13: 성공 → backoff 초기화
          });
        } else {
          // v12.13: 비정상 응답 → backoff (5xx 가 흔함)
          _fusionRetryDelay = (_fusionRetryDelay * 2).clamp(1500, 30000);
        }
      } catch (_) {
        _fusionRetryDelay = (_fusionRetryDelay * 2).clamp(1500, 30000);
      }

      // 가려진 신호등 대체 안내 — voxel 분석으로 occlusion_score 추정
      try {
        final occ = _estimateOcclusionScore();
        final r = await http.get(Uri.parse(
              '$kApiBase/signals/$iid/alternate?occlusion_score=${occ.toStringAsFixed(2)}'))
            .timeout(const Duration(seconds: 6));
        if (r.statusCode == 200) {
          final body = jsonDecode(r.body) as Map<String, dynamic>;
          final newState = (body['signal_state']?.toString() ?? '').toLowerCase();
          // v12.19: "unknown" / gps-* 위치 → SignalHud 알람 띄우지 않음 (정확성)
          final iidIsGps = iid.startsWith('gps-');
          final isUnknown = newState.contains('unknown') || newState.isEmpty;
          if (iidIsGps || isUnknown) {
            if (mounted && _altSignal != null) setState(() => _altSignal = null);
          } else {
          final wasStop = ((_altSignal?['signal_state'] as String?) ?? '').toLowerCase().contains('stop');
          final isStop  = newState.contains('stop') || newState.contains('red');
          if (mounted) setState(() => _altSignal = body);
          if (isStop && !wasStop) {
            // 새로 정지 신호 감지 → 강한 햅틱 (heavyImpact 3회 burst)
            HapticFeedback.heavyImpact();
            await Future.delayed(const Duration(milliseconds: 120));
            HapticFeedback.heavyImpact();
            await Future.delayed(const Duration(milliseconds: 120));
            HapticFeedback.heavyImpact();
          }
          }  // end else (known intersection, not unknown)
        }
      } catch (_) {}
    }

    // ★ DEMO 모드일 때만 — /occupancy/demo class_grid_flat (실내 시연용)
    // LIVE 모드 (기본): 카메라 → 클라이언트 voxel 만 사용 (서버 미호출)
    if (_demoScenarioOn) {
      try {
        final scn = _scnList[_scnIdx % _scnList.length];
        final r = await http.get(Uri.parse('$kApiBase/occupancy/demo?scenario=$scn'))
            .timeout(const Duration(seconds: 6));
        if (r.statusCode == 200) {
          final body = jsonDecode(r.body) as Map<String, dynamic>;
          if (mounted) setState(() => _serverBev = body);
        }
      } catch (_) {}
    } else if (_serverBev != null) {
      // 데모 OFF 즉시 서버 BEV 비우기
      if (mounted) setState(() => _serverBev = null);
    }

    // v2 2026-05-15: BIS 실시간 버스 위치 (반경 150m) — ego GPS 가 있을 때만 5초 1회
    final p = _pos;
    if (p != null) {
      try {
        final r = await http.get(Uri.parse(
          '$kApiBase/collab/bus-live?lat=${p.latitude.toStringAsFixed(5)}&lon=${p.longitude.toStringAsFixed(5)}&radius_m=150'
        )).timeout(const Duration(seconds: 5));
        if (r.statusCode == 200) {
          final body = jsonDecode(r.body) as Map<String, dynamic>;
          if (mounted) setState(() => _busLive = body);
        }
      } catch (_) {}
    }
  }

  /// voxel grid 의 신호등 영역 (멀리·중앙) 점유율을 0~1 occlusion_score 로 변환.
  /// (보존, 사용 X) 서버 YOLO 호출 — 엣지 처리 원칙으로 미사용
  /// 향후 시연/디버그용으로만 호출 가능 — LIVE 모드 기본은 100% on-device.
  // ignore: unused_element
  Future<void> _serverObjectDetect(Uint8List bytes, Map<String, dynamic> voxel) async {
    try {
      final url = Uri.parse('$kApiBase/occupancy/infer');
      final req = http.MultipartRequest('POST', url);
      req.fields['duration'] = '0.0';
      req.fields['obstacle_type'] = 'unknown';
      req.fields['signal_state'] = '';
      req.fields['taas_nearby'] = '0';
      // 이미지를 multipart 로 추가 (memory bytes)
      req.files.add(http.MultipartFile.fromBytes('image', bytes,
          filename: 'frame.jpg'));
      final streamed = await req.send().timeout(const Duration(seconds: 8));
      if (streamed.statusCode != 200) return;
      final body = await streamed.stream.bytesToString();
      final data = jsonDecode(body) as Map<String, dynamic>;

      // hydranet detection 결과: vehicles / vrus / signals 카운트 + bbox 별 라벨
      final hydra = data['hydranet'] as Map<String, dynamic>?;
      final occupancy = data['occupancy'] as Map<String, dynamic>?;
      if (hydra == null || occupancy == null) return;

      // occupancy.grid_flat (서버 16×16 또는 다른) → 변환 필요
      // 단순화: server 가 hotspot 형태로 객체 위치 제공할 때 사용
      // 일단 hydra count 만 우상단 표시용으로 voxel 에 저장
      voxel['server_detect'] = {
        'vehicles': hydra['vehicles'] ?? 0,
        'vrus': hydra['vrus'] ?? 0,
        'signals': hydra['signals'] ?? 0,
        'p_collision': data['risk']?['p_collision'] ?? 0.0,
        'ts': DateTime.now().millisecondsSinceEpoch,
      };

      // ★ 서버 hotspot bbox → BEV class grid 매핑 (간단 휴리스틱)
      // hydra detection bbox 가 image-space (1080×1920) → BEV (40×40)
      // bbox center y 가 가까울수록 (큰 y) row 작음 (가까이)
      const rows = 40, cols = 40;
      final classGrid = List<int>.filled(rows * cols, 0);

      List<dynamic> mergeAll() {
        final out = <dynamic>[];
        // 서버 raw detections 가 detect.* 또는 hydra.* 형태로 있을 수 있음
        if (data['detections'] is List) out.addAll(data['detections']);
        return out;
      }
      // 폴백: hydra.detections 같은 구조 없으면 hydra count 만 표시 (위에서 저장)

      for (final d in mergeAll()) {
        if (d is! Map) continue;
        final cls = d['class_name'] as String?;
        final bbox = d['bbox_xyxy'] as List?;
        if (bbox == null || bbox.length != 4) continue;
        final imgSize = d['image_size'] as List?;
        if (imgSize == null || imgSize.length != 2) continue;
        final iw = (imgSize[0] as num).toDouble();
        final ih = (imgSize[1] as num).toDouble();
        final x1 = (bbox[0] as num).toDouble();
        final y1 = (bbox[1] as num).toDouble();
        final x2 = (bbox[2] as num).toDouble();
        final y2 = (bbox[3] as num).toDouble();
        final cxImg = (x1 + x2) / 2;
        final cyImg = (y1 + y2) / 2;
        // class label 매핑 (YOLOv8n COCO)
        int clsId = 0;
        if (cls == null) continue;
        if (['person'].contains(cls)) clsId = 4;
        else if (['car', 'truck', 'bus', 'motorcycle'].contains(cls)) {
          clsId = (cls == 'motorcycle') ? 2 : 1;
        }
        else if (['traffic light'].contains(cls)) clsId = 5;
        if (clsId == 0) continue;
        final bevC = (cxImg / iw * cols).round().clamp(0, cols - 1);
        final bevR = ((1 - cyImg / ih) * rows).round().clamp(0, rows - 1);
        // 박스 사이즈 → BEV cell radius (1~3)
        final wPix = (x2 - x1).abs();
        final hPix = (y2 - y1).abs();
        final pixelArea = wPix * hPix / (iw * ih);
        final radius = (math.sqrt(pixelArea) * 12).clamp(1.0, 3.0).toInt();
        for (int dr = -radius; dr <= radius; dr++) {
          for (int dc = -radius; dc <= radius; dc++) {
            final r = bevR + dr, c = bevC + dc;
            if (r < 0 || r >= rows || c < 0 || c >= cols) continue;
            classGrid[r * cols + c] = clsId;
          }
        }
      }

      // 검출된 게 1개라도 있으면 class_grid 적용
      if (classGrid.any((v) => v != 0)) {
        voxel['class_grid_flat'] = classGrid;
      }
      if (mounted) setState(() {});  // re-paint
    } catch (_) {/* 네트워크 실패 — 휴리스틱 fallback */}
  }

  /// ML Kit 객체 검출 → BEV class_grid_flat 매핑.
  /// 검출된 bbox 를 BEV 셀 (40×40) 에 마킹:
  ///   - aspect ratio h/w > 1.5 → 사람 (cls=4)
  ///   - else → 차량 (cls=1)
  /// 위치 매핑:
  ///   - col = bbox 중심 x / image_w * 40
  ///   - row = (1 - bbox 중심 y / image_h) * 40   (y=top → row 40 멀리, y=bottom → row 0 가까이)
  Future<List<int>?> _detectObjectsToClassGrid(String imagePath, Uint8List bytes, int rows, int cols) async {
    try {
      final inputImage = InputImage.fromFilePath(imagePath);
      final objects = await _objDetector!.processImage(inputImage);
      if (objects.isEmpty) return null;

      // 이미지 dimensions — 원본 byte 에서 직접 디코드 (일부 폰은 metadata 미제공)
      final src = img.decodeJpg(bytes);
      if (src == null) return null;
      final imgW = src.width.toDouble();
      final imgH = src.height.toDouble();

      final classGrid = List<int>.filled(rows * cols, 0);
      final imgArea = imgW * imgH;
      var accepted = 0;
      for (final obj in objects) {
        final box = obj.boundingBox;
        final cxImg = (box.left + box.right) / 2;
        final cyImg = (box.top + box.bottom) / 2;
        final w = (box.right - box.left).abs();
        final h = (box.bottom - box.top).abs();
        // ★ 엄격한 크기 필터 — false positive 차단
        // bbox 면적 ≥ 4% image (작은 edge 노이즈 차단)
        final pixelArea = w * h;
        final areaRatio = pixelArea / imgArea;
        if (areaRatio < 0.04) continue;        // 4% 미만 skip
        if (areaRatio > 0.65) continue;        // 65% 초과 skip (전체 화면 = 카메라 흔들림)
        // 극단 비율 (벽/바닥 같은 긴 띠) 차단
        final aspect = h / w;
        if (aspect < 0.25 || aspect > 4.0) continue;  // 너무 가늘면 skip
        if (w < 30 || h < 30) continue;              // 절대 크기 너무 작으면 skip
        // 분류
        final cls = aspect > 1.4 ? 4 : 1;  // 4=person (세로 긴), 1=vehicle (가로/정사각)
        // BEV 셀 매핑
        final bevC = (cxImg / imgW * cols).round().clamp(0, cols - 1);
        final bevR = ((1 - cyImg / imgH) * rows).round().clamp(0, rows - 1);
        final radius = (math.sqrt(areaRatio) * 12).clamp(1.0, 3.0).toInt();
        for (int dr = -radius; dr <= radius; dr++) {
          for (int dc = -radius; dc <= radius; dc++) {
            final r = bevR + dr;
            final c = bevC + dc;
            if (r < 0 || r >= rows || c < 0 || c >= cols) continue;
            classGrid[r * cols + c] = cls;
          }
        }
        accepted++;
      }
      if (accepted == 0) return null;
      return classGrid;
    } catch (_) {
      return null;
    }
  }

  // v9.2 2026-05-18: ML Kit 검출 → Flutter 네이티브 BEV 오버레이용 state + (옵션) WebView push.
  //   사람/차량 bbox 를 저장 → _LiveBevTilted 가 perspective transform 위에 박스 그림.
  Future<void> _pushDetectionsToBev(String imagePath, Uint8List bytes) async {
    if (_objDetector == null) {
      if (mounted) setState(() => _detectDebug = 'ML Kit 초기화 실패');
      return;
    }
    try {
      final inputImage = InputImage.fromFilePath(imagePath);
      final objects = await _objDetector!.processImage(inputImage);
      // v11.1 디버그: raw count 기록
      final rawN = objects.length;
      final src = img.decodeJpg(bytes);
      if (src == null) {
        if (mounted) setState(() => _detectDebug = 'JPEG 디코드 실패');
        return;
      }
      final imgW = src.width, imgH = src.height;
      final imgArea = (imgW * imgH).toDouble();
      final dets = <Map<String, dynamic>>[];
      final raws = <Map<String, dynamic>>[];   // v12.4: ALL raw boxes for visual debug
      int rejTooSmall = 0, rejTooLarge = 0, rejAspect = 0, rejMinSize = 0;
      for (final obj in objects) {
        final box = obj.boundingBox;
        final w = (box.right - box.left).abs();
        final h = (box.bottom - box.top).abs();
        final pixelArea = w * h;
        final areaRatio = pixelArea / imgArea;
        // 라벨 정보 — classifyObjects=true 시 의미 있는 라벨
        final labelStr = obj.labels.isEmpty
          ? 'unlabeled'
          : obj.labels.take(2).map((l) => '${l.text}:${(l.confidence * 100).toInt()}%').join(',');
        // v12.4: raw 박스 모두 기록 (필터 결과와 사유 포함)
        String? rejReason;
        bool kept = true;
        // v12: filter 더 완화 (0.4% → 0.15%) - 실내 작은 물체도 잡음
        if (areaRatio < 0.0015) { rejTooSmall++; kept=false; rejReason='small ${(areaRatio*100).toStringAsFixed(2)}%'; }
        else if (areaRatio > 0.88) { rejTooLarge++; kept=false; rejReason='big ${(areaRatio*100).toStringAsFixed(0)}%'; }
        else if (w < 10 || h < 10) { rejMinSize++; kept=false; rejReason='<10px'; }
        else {
          final aspectCheck = h / w;
          if (aspectCheck < 0.10 || aspectCheck > 8.0) { rejAspect++; kept=false; rejReason='aspect ${aspectCheck.toStringAsFixed(2)}'; }
        }
        raws.add({
          'box': [box.left.toInt(), box.top.toInt(), w.toInt(), h.toInt()],
          'labels': labelStr,
          'kept': kept,
          'rej': rejReason,
        });
        if (!kept) continue;
        final aspect = h / w;
        // aspect 기반: 세로 긴 = 사람, 그 외 = 차량/물체
        final cls = aspect > 1.4 ? 'person' : 'car';
        double score = 0.6;
        if (obj.labels.isNotEmpty) {
          score = obj.labels.first.confidence;
        }
        dets.add({
          'cls': cls,
          'box': [box.left.toInt(), box.top.toInt(), w.toInt(), h.toInt()],
          'score': score,
        });
      }
      // Flutter 네이티브 BEV 오버레이용 state 저장
      if (mounted) {
        setState(() {
          _bevDetections = dets;
          _rawDetections = raws;   // v12.4: 카메라 위 raw 박스 표시용
          _bevImgW = imgW; _bevImgH = imgH;
          _detectRawN = rawN;
          _detectKeptN = dets.length;
          _detectLastAt = DateTime.now();
          if (rawN == 0) {
            _detectDebug = 'ML Kit raw=0 (객체 미발견)';
          } else {
            // 거부 사유 detail
            final rej = <String>[];
            if (rejTooSmall > 0) rej.add('${rejTooSmall}small');
            if (rejTooLarge > 0) rej.add('${rejTooLarge}big');
            if (rejMinSize > 0) rej.add('${rejMinSize}<10px');
            if (rejAspect > 0)  rej.add('${rejAspect}aspect');
            final rejStr = rej.isEmpty ? '' : ' rej[${rej.join(',')}]';
            _detectDebug = 'raw=$rawN kept=${dets.length}$rejStr';
          }
        });
      }
      // (옵션) WebView 가 살아있을 때 push 도 진행 (legacy WebView BEV 화면 호환)
      final wv = _bevWvCtrl;
      if (wv != null) {
        final payload = jsonEncode({'detections': dets, 'vw': imgW, 'vh': imgH});
        try {
          await wv.runJavaScript('window.aurDetect && window.aurDetect($payload)');
        } catch (_) {}
      }
    } catch (e) {
      if (mounted) setState(() => _detectDebug = 'detect 예외: ${e.toString().substring(0, e.toString().length > 60 ? 60 : e.toString().length)}');
    }
  }

  double _estimateOcclusionScore() {
    final flat = _bev?['grid_flat'];
    if (flat is! List || flat.length != 1600) return 0.30;
    const ROWS = 40, COLS = 40;
    double upperCenter = 0;
    int cells = 0;
    for (int r = 25; r < 38; r++) {
      for (int c = 14; c < 26; c++) {
        upperCenter += (flat[r * COLS + c] as num).toDouble();
        cells++;
      }
    }
    final ratio = upperCenter / cells;
    return (ratio * 1.6).clamp(0.10, 0.95);
  }

  /// 엣지 voxel 생성 — 카메라 프레임을 40×40 grayscale 로 다운샘플 후
  /// (수직 에지) + (이전 프레임 대비 motion diff) 로 점유 확률 계산.
  /// → 카메라 흔들림/물체 이동에 voxel 이 반응.
  Map<String, dynamic>? _voxelizeOnDevice(Uint8List jpeg) {
    try {
      final src = img.decodeJpg(jpeg);
      if (src == null) return null;
      final w = src.width, h = src.height;
      const ROWS = 40, COLS = 40;
      // 1) 다운샘플 grayscale (44×40 — 위쪽 4 row 는 에지 계산 padding)
      final grays = List<double>.filled(ROWS * COLS, 0.0);
      final yStart = (h * 0.05).toInt();
      final yEnd = (h * 0.95).toInt();
      final cellH = (yEnd - yStart) / ROWS;
      final cellW = w / COLS;
      // 각 cell 의 평균 밝기 (3×3 샘플)
      for (int r = 0; r < ROWS; r++) {
        // r=0 화면 아래(ego), r=39 화면 위(멀리)
        final yMid = (yEnd - (r + 0.5) * cellH).toInt();
        if (yMid < 2 || yMid >= h - 2) continue;
        for (int c = 0; c < COLS; c++) {
          final xMid = ((c + 0.5) * cellW).toInt();
          if (xMid < 2 || xMid >= w - 2) continue;
          double sum = 0; int cnt = 0;
          for (int dy = -1; dy <= 1; dy++) {
            for (int dx = -1; dx <= 1; dx++) {
              final p = src.getPixel(xMid + dx, yMid + dy);
              sum += 0.299 * p.r + 0.587 * p.g + 0.114 * p.b;
              cnt++;
            }
          }
          grays[r * COLS + c] = sum / cnt / 255.0;
        }
      }

      // 2) 수직 에지 + 좌우 에지 + motion diff (분리 저장)
      final flat = List<double>.filled(ROWS * COLS, 0.0);
      final motionFlat = List<double>.filled(ROWS * COLS, 0.0);  // ★ 움직임만
      for (int r = 0; r < ROWS; r++) {
        for (int c = 0; c < COLS; c++) {
          final cur = grays[r * COLS + c];
          if (cur < 0.05) continue;
          final up = (r < ROWS - 1) ? grays[(r + 1) * COLS + c] : cur;
          final left = (c > 0) ? grays[r * COLS + (c - 1)] : cur;
          final right = (c < COLS - 1) ? grays[r * COLS + (c + 1)] : cur;
          final vEdge = (cur - up).abs();
          final hEdge = ((cur - left).abs() + (cur - right).abs()) * 0.5;
          double motion = 0;
          if (_prevFrameGray != null && _prevFrameGray!.length == ROWS * COLS) {
            motion = (cur - _prevFrameGray![r * COLS + c]).abs();
          }
          motionFlat[r * COLS + c] = motion.clamp(0.0, 1.0);
          // 결합 — 정지 가구/벽 false positive 줄이기 위해 motion 가중 ↑
          final occ = (vEdge * 2.0 + hEdge * 0.8 + motion * 4.0).clamp(0.0, 1.0);
          flat[r * COLS + c] = occ;
        }
      }
      // 3) 이전 프레임 저장 (motion diff 용)
      _prevFrameGray = List<double>.from(grays);

      // 8-근방 합산으로 hotspot Top-4 추출
      final cells = <List<num>>[];
      for (int r = 1; r < ROWS - 1; r++) {
        for (int c = 1; c < COLS - 1; c++) {
          if (flat[r * COLS + c] < 0.45) continue;
          double sum = 0;
          for (int dr = -1; dr <= 1; dr++) {
            for (int dc = -1; dc <= 1; dc++) {
              sum += flat[(r + dr) * COLS + (c + dc)];
            }
          }
          cells.add([r, c, sum]);
        }
      }
      cells.sort((a, b) => (b[2] as num).compareTo(a[2] as num));
      final hotspots = <Map<String, dynamic>>[];
      for (int i = 0; i < cells.length && hotspots.length < 4; i++) {
        final r = cells[i][0] as int;
        final c = cells[i][1] as int;
        // 중복 제거 (가까운 이웃)
        bool tooClose = false;
        for (final h in hotspots) {
          if (((h['_r'] as int) - r).abs() < 4 && ((h['_c'] as int) - c).abs() < 4) {
            tooClose = true; break;
          }
        }
        if (tooClose) continue;
        final dist = r * 1.0;
        String kind, label;
        if (c < 12) {
          kind = 'object'; label = '좌측 객체';
        } else if (c > 28) {
          kind = 'object'; label = '우측 객체';
        } else if (r > 22) {
          kind = 'occluded_shadow'; label = '전방 가림';
        } else {
          kind = 'object'; label = '전방 객체';
        }
        hotspots.add({
          '_r': r, '_c': c,
          'row': r * 2, 'col': c * 2,
          'kind': kind, 'label': label,
          'distance_m': dist.round(),
        });
      }

      // 위험도 — 가까운 12m × 차로 중앙 14~26
      double risk = 0;
      for (int r = 0; r < 12; r++) {
        for (int c = 14; c < 26; c++) {
          risk += flat[r * COLS + c];
        }
      }
      final pColl = (risk / 60.0).clamp(0.0, 0.95);

      return {
        'shape': [80, 80],
        'grid_flat': flat,
        'motion_flat': motionFlat,
        'grid_shape_flat': [ROWS, COLS],
        'grid_cell_m_flat': 1.0,
        'forward_m': 40.0,
        'lateral_m': 20.0,
        'hotspots': hotspots,
        'occluded_mass': flat.fold<double>(0.0, (a, b) => a + b),
        'risk_summary': {
          'p_collision': pColl,
          'lead_time_s': 0.0,
          'recommended_action': pColl > 0.5 ? '감속' : '정상',
        },
        '_source': 'edge',
      };
    } catch (_) {
      return null;
    }
  }

  /// 실시간 위치 스트림 — heading/speed 를 V2V broadcast 에 사용
  void _startLocationStream() {
    if (kIsWeb) return;
    try {
      _posSub = Geolocator.getPositionStream(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          distanceFilter: 3,
        ),
      ).listen((p) {
        if (!mounted) return;
        // v12.12: 직전 위치와 거리 누적 → 총 주행 km (큰 점프 200m+ 는 GPS jitter 로 skip)
        double addKm = 0;
        if (_prevPos != null) {
          final m = Geolocator.distanceBetween(
            _prevPos!.latitude, _prevPos!.longitude, p.latitude, p.longitude);
          if (m < 200) addKm = m / 1000.0;
        }
        _prevPos = p;
        setState(() {
          _pos = p;
          _totalKm += addKm;
        });
        // v12.13: 영속화 (10m 단위로만 저장 — 너무 잦은 쓰기 방지)
        if (addKm > 0.01) {
          SharedPreferences.getInstance().then((sp) => sp.setDouble('total_km', _totalKm));
        }
      }, onError: (_) {});
    } catch (_) {}
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused || state == AppLifecycleState.inactive) {
      _ticker?.cancel();
      _bevTimer?.cancel();
      _pollServerTimer?.cancel();
      // v12.1: 백그라운드 진입 시 카메라 HW 해제 (zombie 카메라 점유 방지)
      try {
        if (_imageStreamRunning) {
          _cam?.stopImageStream();
          _imageStreamRunning = false;
        }
        _cam?.dispose();
      } catch (_) {}
      _cam = null;
    } else if (state == AppLifecycleState.resumed) {
      // 백그라운드에서 돌아왔을 때 타이머 재시작 + 카메라 재초기화
      if (_cam == null) {
        _initCamera();   // v12.1: 백그라운드 복귀 시 카메라 다시 열기
      }
      if (_shadowOn) {
        _ticker ??= Timer.periodic(kShadowInterval, (_) => _shadowTick());
      }
      _bevTimer ??= Timer.periodic(const Duration(milliseconds: 1500), (_) => _fetchBev());
      _pollServerTimer ??= Timer.periodic(const Duration(seconds: 30), (_) => _pollServer());
      _refreshLocation();
    }
  }

  // v12.6: 카메라 초기화 + startImageStream (takePicture 폐기 — Galaxy Z Fold 3 stuck 회피)
  Future<void> _initCamera() async {
    if (_cameras.isEmpty) {
      try { _cameras = await availableCameras(); } catch (_) {}
    }
    if (_cameras.isEmpty) {
      if (mounted) setState(() => _detectDebug = '카메라 없음 (availableCameras=0)');
      return;
    }
    final preferred = _cameras.firstWhere(
      (c) => c.lensDirection == CameraLensDirection.back,
      orElse: () => _cameras.first,
    );
    for (int attempt = 0; attempt < 3; attempt++) {
      // v12.8: nv21 포맷 직접 시도 (ML Kit Android 가 NV21 expect)
      final controller = CameraController(preferred, ResolutionPreset.medium,
        enableAudio: false, imageFormatGroup: ImageFormatGroup.nv21);
      try {
        await controller.initialize();
        _cam = controller;
        debugPrint('[AURAVIEW] CameraController.initialize() OK, previewSize=${controller.value.previewSize}');
        // v12.6: startImageStream — 매 프레임 _onCameraFrame() 호출
        await controller.startImageStream(_onCameraFrame);
        _imageStreamRunning = true;
        debugPrint('[AURAVIEW] startImageStream() OK');
        if (mounted) setState(() => _detectDebug = '카메라 stream OK (${attempt+1}/3)');
        return;
      } catch (e, st) {
        debugPrint('[AURAVIEW] camera init exception: $e\n$st');
        try { await controller.dispose(); } catch (_) {}
        if (mounted) setState(() {
          _detectDebug = '카메라 시도 ${attempt+1}/3 실패: ${e.toString().split(":").first}';
        });
        await Future.delayed(const Duration(milliseconds: 1500));
      }
    }
    if (mounted) setState(() => _detectDebug = '카메라 3회 시도 실패 — 다른 앱이 점유 중');
  }

  // v12.8: YUV_420_888 → NV21 변환 (ML Kit 가 정확히 받을 수 있게)
  //   Y plane 그대로 + V/U byte interleave (VU 순서)
  Uint8List _yuv420ToNv21(CameraImage img) {
    final int ySize = img.planes[0].bytes.length;
    final int uSize = img.planes[1].bytes.length;
    final int vSize = img.planes[2].bytes.length;
    final out = Uint8List(ySize + uSize + vSize);
    // Y plane
    out.setRange(0, ySize, img.planes[0].bytes);
    // VU interleave (NV21 = Y...YVUVU...VU)
    final uBytes = img.planes[1].bytes;
    final vBytes = img.planes[2].bytes;
    final uvPixelStride = img.planes[1].bytesPerPixel ?? 1;
    int oi = ySize;
    // V/U bytes are interleaved if pixelStride==2 (most cases on Android)
    if (uvPixelStride == 2) {
      // Plane 2 (V) is the source — VU 인터리브를 위해 V[i] U[i] 페어로
      // pixelStride=2 인 경우 plane 데이터가 이미 interleaved 형태 (every 2 bytes = V,U or U,V).
      // Android Camera2 에서는 plane[2] 가 V 먼저 인터리브된 byte buffer 인 경우가 흔함.
      // 단순화: V plane 을 그대로 (이미 VU interleaved 버퍼) 복사 + 1바이트 더
      final vLen = math.min(vBytes.length, out.length - oi);
      out.setRange(oi, oi + vLen, vBytes);
    } else {
      // pixelStride=1 인 경우 V/U 각각 분리 — 수동으로 interleave
      final pairs = math.min(uBytes.length, vBytes.length);
      for (int i = 0; i < pairs && oi + 1 < out.length; i++) {
        out[oi++] = vBytes[i];
        out[oi++] = uBytes[i];
      }
    }
    return out;
  }

  // v12.6: ImageStream 콜백 — 매 프레임 호출됨 (높은 빈도)
  //   throttle 해서 ~3 FPS 만 처리 + ML Kit InputImage.fromBytes 로 직접 변환
  int _camFrameCount = 0;
  void _onCameraFrame(CameraImage frame) {
    _camFrameCount++;
    if (_camFrameCount <= 3 || _camFrameCount % 30 == 0) {
      debugPrint('[AURAVIEW] _onCameraFrame #$_camFrameCount, ${frame.width}x${frame.height} planes=${frame.planes.length}');
    }
    _lastCameraFrame = frame;
    final now = DateTime.now().millisecondsSinceEpoch;
    if (now - _lastStreamProcessAt < 330) return;   // ~3 FPS throttle
    _lastStreamProcessAt = now;
    _processFrame(frame);
  }

  // v12.8: stream 프레임 → ML Kit 검출 (NV21 format direct)
  bool _logFirstFrameOnce = false;
  Future<void> _processFrame(CameraImage frame) async {
    if (_objDetector == null || _mlkitBusy) return;
    // v12.12: FPS 계산 (최근 10 처리 시각 기록)
    final nowMs = DateTime.now().millisecondsSinceEpoch;
    _fpsTimes.add(nowMs);
    if (_fpsTimes.length > 10) _fpsTimes.removeAt(0);
    if (_fpsTimes.length >= 2) {
      final span = (_fpsTimes.last - _fpsTimes.first) / 1000.0;
      if (span > 0.01) _detectFps = (_fpsTimes.length - 1) / span;
    }
    _mlkitBusy = true;
    try {
      final imgW = frame.width, imgH = frame.height;
      // v12.8: NV21 format 직접 — 변환 없이 plane[0].bytes 사용
      //   ImageFormatGroup.nv21 시 plane[0] = 전체 NV21 buffer (Y + VU)
      final Uint8List nv21 = frame.planes.length == 1
        ? frame.planes[0].bytes
        : _yuv420ToNv21(frame);
      if (!_logFirstFrameOnce) {
        _logFirstFrameOnce = true;
        debugPrint('[AURAVIEW] First frame: planes=${frame.planes.length}, W=$imgW H=$imgH, byte0=${nv21[0]}, byte1k=${nv21.length > 1000 ? nv21[1000] : "?"}, byteN=${nv21[nv21.length - 1]}');
      }
      final inputImage = InputImage.fromBytes(
        bytes: nv21,
        metadata: InputImageMetadata(
          size: Size(imgW.toDouble(), imgH.toDouble()),
          rotation: InputImageRotation.rotation90deg,
          format: InputImageFormat.nv21,
          bytesPerRow: frame.planes[0].bytesPerRow,
        ),
      );
      final objects = await _objDetector!.processImage(inputImage);
      // v12.9: ImageLabeler 추가 호출 — frame 전체 라벨 (Person/Car 같은 광범위 카테고리)
      List<ImageLabel> labelerResults = const [];
      if (_imgLabeler != null) {
        try {
          labelerResults = await _imgLabeler!.processImage(inputImage);
        } catch (_) {}
      }
      final rawN = objects.length;
      final imgArea = (imgW * imgH).toDouble();
      final dets = <Map<String, dynamic>>[];
      final raws = <Map<String, dynamic>>[];
      int rejTooSmall = 0, rejTooLarge = 0, rejAspect = 0, rejMinSize = 0;
      for (final obj in objects) {
        final box = obj.boundingBox;
        final w = (box.right - box.left).abs();
        final h = (box.bottom - box.top).abs();
        final pixelArea = w * h;
        final areaRatio = pixelArea / imgArea;
        final labelStr = obj.labels.isEmpty
          ? 'unlabeled'
          : obj.labels.take(2).map((l) => '${l.text}:${(l.confidence * 100).toInt()}%').join(',');
        String? rejReason; bool kept = true;
        if (areaRatio < 0.0015) { rejTooSmall++; kept=false; rejReason='small ${(areaRatio*100).toStringAsFixed(2)}%'; }
        else if (areaRatio > 0.88) { rejTooLarge++; kept=false; rejReason='big ${(areaRatio*100).toStringAsFixed(0)}%'; }
        else if (w < 10 || h < 10) { rejMinSize++; kept=false; rejReason='<10px'; }
        else {
          final ac = h / w;
          if (ac < 0.10 || ac > 8.0) { rejAspect++; kept=false; rejReason='aspect ${ac.toStringAsFixed(2)}'; }
        }
        raws.add({
          'box': [box.left.toInt(), box.top.toInt(), w.toInt(), h.toInt()],
          'labels': labelStr, 'kept': kept, 'rej': rejReason,
        });
        if (!kept) continue;
        final aspect = h / w;
        final cls = aspect > 1.4 ? 'person' : 'car';
        double score = 0.6;
        if (obj.labels.isNotEmpty) score = obj.labels.first.confidence;
        dets.add({'cls': cls, 'box': [box.left.toInt(), box.top.toInt(), w.toInt(), h.toInt()], 'score': score});
      }
      if (mounted) {
        setState(() {
          _bevDetections = dets;
          _rawDetections = raws;
          _bevImgW = imgW; _bevImgH = imgH;
          _detectRawN = rawN;
          _detectKeptN = dets.length;
          _detectLastAt = DateTime.now();
          // v12.9: ImageLabeler 결과 포함 디버그
          final labStr = labelerResults.isEmpty
            ? ''
            : ' lab[' + labelerResults.take(3).map((l) => '${l.label}:${(l.confidence*100).toInt()}%').join(',') + ']';
          if (rawN == 0 && labelerResults.isEmpty) {
            _detectDebug = 'raw=0 lab=0 (둘 다 미검출)';
          } else if (rawN == 0) {
            _detectDebug = 'obj=0$labStr';
          } else {
            final rej = <String>[];
            if (rejTooSmall > 0) rej.add('${rejTooSmall}small');
            if (rejTooLarge > 0) rej.add('${rejTooLarge}big');
            if (rejMinSize > 0) rej.add('${rejMinSize}<10px');
            if (rejAspect > 0)  rej.add('${rejAspect}aspect');
            final rejStr = rej.isEmpty ? '' : ' rej[${rej.join(',')}]';
            _detectDebug = 'obj=$rawN/${dets.length}$rejStr$labStr';
          }
        });
      }
    } catch (e) {
      if (mounted) setState(() => _detectDebug =
        'frame 예외: ${e.toString().substring(0, e.toString().length > 60 ? 60 : e.toString().length)}');
    } finally {
      _mlkitBusy = false;
    }
  }

  Future<void> _bootstrap() async {
    final sp = await SharedPreferences.getInstance();
    var id = sp.getString('device_id');
    if (id == null) {
      id = 'fleet-${DateTime.now().millisecondsSinceEpoch}-${Random().nextInt(1 << 32).toRadixString(16)}';
      await sp.setString('device_id', id);
    }
    // v12.15: 실제 운영은 GPS 기반 자동 교차로 감지 (_autoIntersectionId).
    //   intersection_id 는 사용자가 설정 시트에서 명시 입력했을 때만 사용.
    //   데모 모드는 명시적 옵트인 (sp 'demo_mode' true 일 때만 "1007" 강제).
    _intersectionId = sp.getString('intersection_id');
    final demoMode = sp.getBool('demo_mode') ?? false;
    if (demoMode && (_intersectionId == null || _intersectionId!.isEmpty)) {
      _intersectionId = '1007';
    }
    // v5 2026-05-17: 첫 실행 온보딩 플래그
    _showOnboarding = !(sp.getBool('onboarding_done') ?? false);
    setState(() => _deviceId = id!);

    if (!kIsWeb) {
      await Permission.camera.request();
      await Permission.locationWhenInUse.request();
    }

    // v12.1: 카메라 재시도 가능 초기화 (ERROR_MAX_CAMERAS_IN_USE 회복)
    await _initCamera();

    _refreshLocation();
    _startLocationStream();
    _pollServer();
    _checkFusionHealth();   // v12.13: 서버 schema/live source 헬시 1회
    _pollServerTimer = Timer.periodic(const Duration(seconds: 30), (_) {
      _pollServer();
      _checkFusionHealth();
    });

    // v12.13: 저장된 누적 주행거리 복원 (영속화)
    _totalKm = sp.getDouble('total_km') ?? 0.0;

    // v9.2: BEV 자동 시작 (1.5초 주기 — WebView 3D 빌보드 라이브 갱신 위해 단축)
    _fetchBev();
    _bevTimer = Timer.periodic(const Duration(milliseconds: 1500), (_) => _fetchBev());
    // 시나리오 회전 타이머는 demoScenario 토글 시에만 시작 (_toggleDemoScenario)

    if (mounted) setState(() => _initing = false);
  }

  Future<void> _refreshLocation() async {
    try {
      if (await Geolocator.isLocationServiceEnabled()) {
        final p = await Geolocator.getCurrentPosition(
          locationSettings: const LocationSettings(
            accuracy: LocationAccuracy.high, timeLimit: Duration(seconds: 8),
          ),
        );
        if (mounted) setState(() => _pos = p);
      }
    } catch (_) {}
  }

  Future<void> _pollServer() async {
    try {
      final r = await http.get(Uri.parse('$kApiBase/fleet/stats'))
          .timeout(const Duration(seconds: 6));
      if (r.statusCode == 200) {
        final body = r.body;
        // 단순 파싱: "total":N
        final match = RegExp(r'"total"\s*:\s*(\d+)').firstMatch(body);
        if (mounted) {
          setState(() {
            _serverTotal = match != null ? int.parse(match.group(1)!) : 0;
            _serverError = '';
          });
        }
      }
    } catch (e) {
      if (mounted) setState(() => _serverError = '연결 안 됨');
    }
  }

  /// v12.13: /fusion/sources 헬시 체크 (schema 버전 / N/21 live 소스 카운트)
  ///   bootstrap 1회 + _pollServer 와 함께 주기적으로 호출.
  ///   v12.14: schema 불일치 경고 추가 (네이티브 expectedSchema vs 서버 응답)
  static const String _expectedSchemaPrefix = 'fusion.v9-23src';
  bool _schemaMismatch = false;
  Future<void> _checkFusionHealth() async {
    try {
      final r = await http.get(Uri.parse('$kApiBase/fusion/sources'))
          .timeout(const Duration(seconds: 5));
      if (r.statusCode != 200) return;
      final j = jsonDecode(r.body) as Map<String, dynamic>;
      final cnt = (j['count'] as num?)?.toInt() ?? 0;
      final schema = j['schema_version']?.toString() ?? '';
      final sources = j['sources'] as List? ?? [];
      int live = 0;
      for (final s in sources) {
        if (s is Map && s['mode'] == 'live') live++;
      }
      final mismatch = !schema.startsWith(_expectedSchemaPrefix);
      if (mounted) setState(() {
        _serverSourceCount = cnt;
        _serverLiveSourceCount = live;
        _serverSchema = schema;
        _schemaMismatch = mismatch;
      });
    } catch (_) {/* 무시 */}
  }

  void _toggleShadow() {
    HapticFeedback.lightImpact();
    setState(() => _shadowOn = !_shadowOn);
    if (_shadowOn) {
      _ticker = Timer.periodic(kShadowInterval, (_) => _shadowTick());
      _shadowTick();
    } else {
      _ticker?.cancel();
      _ticker = null;
    }
  }

  Future<void> _shadowTick() async {
    if (_cam == null || !_cam!.value.isInitialized) return;
    if (_cam!.value.isTakingPicture) return;
    try {
      final shot = await _cam!.takePicture();
      final bytes = await shot.readAsBytes();
      _captures++;
      final feat = _entropyAndMotion(bytes);
      _lastEntropy = feat.entropy;
      final reason = _classifyReason(feat);

      // V2V broadcast — intersection ID 가 있고 토글 ON 이면 매 틱 위치/heading/속도 송신
      if (_v2vEnabled && _intersectionId != null && _intersectionId!.isNotEmpty) {
        unawaited(_broadcastV2V(entropy: feat.entropy));
      }

      if (reason != null) {
        _lastReason = reason;
        await _upload(bytes, feat.entropy, reason);
      } else {
        _lastReason = 'ok';
      }
      if (mounted) setState(() {});
      if (!kIsWeb) {
        try { final f = File(shot.path); if (await f.exists()) await f.delete(); } catch (_) {}
      }
    } catch (_) {}
  }

  /// 같은 교차로의 다른 AuraView 차량들에게 내 위치·heading·속도·entropy 를 broadcast.
  /// 마주오는 차들이 이 메시지로 자기 사각지대 점유 격자를 보강함.
  Future<void> _broadcastV2V({required double entropy}) async {
    if (_pos == null) return;
    final p = _pos!;
    final speedMps = p.speed.isFinite && p.speed >= 0 ? p.speed : 0.0;
    final headingDeg = (p.heading.isFinite && speedMps > 1.0) ? p.heading : 0.0;

    // 감속 g 계산
    double decelG = 0.0;
    final now = DateTime.now();
    if (_prevSpeedMps != null && _prevSpeedTs != null) {
      final dt = now.difference(_prevSpeedTs!).inMilliseconds / 1000.0;
      if (dt > 0.1 && dt < 10.0) {
        final dv = _prevSpeedMps! - speedMps;
        decelG = (dv / dt) / 9.81;
        if (decelG < 0) decelG = 0;
      }
    }
    _prevSpeedMps = speedMps;
    _prevSpeedTs = now;

    // entropy 가 높으면 "뭔가 봤음" 신호 (TFLite 통합 전 임시 detection)
    final List<Map<String, Object>> dets = [];
    if (entropy >= 0.65) {
      dets.add({
        "class": "anomaly",
        "conf": entropy,
        "rel_lat": 0.0,
        "rel_lon": 0.0,
        "width_m": 0.6,
      });
    }

    final body = jsonEncode({
      "device_id": _deviceId,
      "intersection_id": _intersectionId,
      "lat": p.latitude,
      "lon": p.longitude,
      "heading_deg": headingDeg,
      "speed_kmh": speedMps * 3.6,
      "decel_g": double.parse(decelG.toStringAsFixed(3)),
      "detections": dets,
      "occluded_mass": entropy * 200.0,
      "ttl_s": 8,
    });

    try {
      final res = await http.post(
        Uri.parse('$kApiBase/collab/v2v/broadcast'),
        headers: const {"Content-Type": "application/json"},
        body: body,
      ).timeout(const Duration(seconds: 6));
      if (res.statusCode >= 200 && res.statusCode < 300) {
        if (mounted) setState(() => _v2vSent++);
      }
    } catch (_) {}
  }

  Future<void> _upload(Uint8List jpg, double entropy, String reason) async {
    final uri = Uri.parse('$kApiBase/fleet/contribute');
    final req = http.MultipartRequest('POST', uri);
    req.fields['device_id'] = _deviceId;
    req.fields['entropy'] = entropy.toStringAsFixed(3);
    req.fields['reason'] = reason;
    if (_intersectionId != null && _intersectionId!.isNotEmpty) {
      req.fields['intersection_id'] = _intersectionId!;
    }
    if (_pos != null) {
      req.fields['lat'] = _pos!.latitude.toStringAsFixed(5);
      req.fields['lon'] = _pos!.longitude.toStringAsFixed(5);
    }
    req.files.add(http.MultipartFile.fromBytes('image', jpg, filename: 'fleet.jpg'));
    try {
      final res = await req.send().timeout(const Duration(seconds: 12));
      if (res.statusCode >= 200 && res.statusCode < 300) {
        _uploads++;
        _lastUploadAt = DateTime.now();
        _pulseAnim.forward(from: 0);
      } else {
        _failures++;
      }
      if (mounted) setState(() {});
      Future.delayed(const Duration(seconds: 1), _pollServer);
    } catch (_) {
      _failures++;
      if (mounted) setState(() {});
    }
  }

  String _reasonKo(String r) => const {
    'signal_occluded':    '🚦 신호등 가림 기록',
    'crosswalk_blocked':  '🚛 횡단보도 가림 기록',
    'blind_spot_left':    '◀ 좌측 사각지대 기록',
    'blind_spot_right':   '▶ 우측 사각지대 기록',
    'high_uncertainty':   '⚠ 시야 불확실 기록',
    'low_confidence':     '· 시야 흐림 기록',
  }[r] ?? '· 자동 기록 ($r)';

  /// AuraView 컨셉 trigger — 신호 가림 / 횡단보도 가림 / 사각지대 감지.
  /// voxel grid (_bev) 가 있으면 occlusion 패턴 우선,
  /// 없으면 entropy/motion 폴백.
  String? _classifyReason(_FrameFeat feat) {
    final flat = _bev?['grid_flat'];
    if (flat is List && flat.length == 1600) {
      // 화면 영역 분석 (40×40 그리드, row 0=ego 가까이, row 39=멀리)
      const ROWS = 40, COLS = 40;
      double upperCenter = 0;   // 신호등이 있을 위치 (멀리·중앙)
      double leftEdge = 0;      // 좌측 사각지대
      double rightEdge = 0;     // 우측 사각지대
      double bigBlobCenter = 0; // 트럭/버스 같은 큰 객체
      for (int r = 25; r < 38; r++) {           // 멀리 (10~15m)
        for (int c = 14; c < 26; c++) {         // 중앙 차로
          upperCenter += (flat[r * COLS + c] as num).toDouble();
        }
      }
      for (int r = 5; r < 25; r++) {            // 가까이~중간
        for (int c = 0; c < 8; c++) {           // 좌측
          leftEdge += (flat[r * COLS + c] as num).toDouble();
        }
        for (int c = 32; c < 40; c++) {         // 우측
          rightEdge += (flat[r * COLS + c] as num).toDouble();
        }
      }
      for (int r = 8; r < 22; r++) {            // 가까이~중간 차로 중앙
        for (int c = 12; c < 28; c++) {
          bigBlobCenter += (flat[r * COLS + c] as num).toDouble();
        }
      }

      // 임계값 — 대략 cell ≥ 0.4 일 때 채워진 걸로 본다
      // 신호 가림: 전방 멀리 중앙 점유 누적 ≥ 30
      if (upperCenter >= 30) return 'signal_occluded';
      // 횡단보도 가림 (큰 객체 중앙 점유): bigBlob ≥ 60
      if (bigBlobCenter >= 60) return 'crosswalk_blocked';
      // 사각지대: 좌/우 측면 누적 ≥ 25
      if (leftEdge >= 25)  return 'blind_spot_left';
      if (rightEdge >= 25) return 'blind_spot_right';
    }
    // 폴백 (voxel 정보 없을 때) — 일반 entropy/motion
    if (feat.entropy >= 0.75 || feat.motion >= 0.7) return 'high_uncertainty';
    if (feat.entropy >= kEntropyThreshold) return 'low_confidence';
    return null;
  }

  _FrameFeat _entropyAndMotion(Uint8List jpg) {
    final decoded = img.decodeImage(jpg);
    if (decoded == null) return const _FrameFeat(0.0, 0.0);
    final small = img.copyResize(decoded, width: 64, height: 64);
    final gray = img.grayscale(small);
    final n = gray.width * gray.height;
    final hist = List<int>.filled(32, 0);
    final flat = Uint8List(n);
    var i = 0;
    for (final px in gray) {
      final v = px.r.toInt();
      flat[i++] = v;
      hist[(v >> 3).clamp(0, 31)] += 1;
    }
    double H = 0.0;
    for (final c in hist) {
      if (c == 0) continue;
      final p = c / n;
      H -= p * (log(p) / ln2);
    }
    final norm = (H / 5.0).clamp(0.0, 1.0);
    double motion = 0.0;
    if (_lastDownsample != null && _lastDownsample!.length == n) {
      var diff = 0;
      for (var j = 0; j < n; j += 4) {
        diff += (flat[j] - _lastDownsample![j]).abs();
      }
      motion = ((diff / (n / 4)) / 40.0).clamp(0.0, 1.0);
    }
    _lastDownsample = flat;
    return _FrameFeat(norm, motion);
  }

  void _toast(String msg, {Color color = _accent}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Row(children: [
        Container(width: 6, height: 6, decoration: BoxDecoration(color: color, shape: BoxShape.circle, boxShadow: [BoxShadow(color: color, blurRadius: 8)])),
        const SizedBox(width: 12),
        Text(msg, style: const TextStyle(color: _text, fontWeight: FontWeight.w700)),
      ]),
      backgroundColor: _surface2,
      behavior: SnackBarBehavior.floating,
      duration: const Duration(milliseconds: 1600),
      margin: const EdgeInsets.all(20),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
    ));
  }

  void _openDetailSheet() {
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      isScrollControlled: true,
      builder: (_) => _DetailSheet(
        deviceId: _deviceId,
        captures: _captures, uploads: _uploads, failures: _failures,
        serverTotal: _serverTotal, serverError: _serverError,
        intersectionId: _intersectionId, pos: _pos,
        lastEntropy: _lastEntropy, lastReason: _lastReason,
        lastUploadAt: _lastUploadAt,
        v2vEnabled: _v2vEnabled, v2vSent: _v2vSent,
        onIntersectionChanged: (v) async {
          final sp = await SharedPreferences.getInstance();
          await sp.setString('intersection_id', v);
          if (mounted) setState(() => _intersectionId = v);
        },
        onV2VChanged: (v) {
          if (mounted) setState(() => _v2vEnabled = v);
        },
      ),
    );
  }

  // ── UI ──────────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    // v5 2026-05-17: 첫 진입 온보딩 (3장 PageView, 한 번만)
    if (_showOnboarding) {
      return _OnboardingScreen(onDone: () async {
        final sp = await SharedPreferences.getInstance();
        await sp.setBool('onboarding_done', true);
        if (mounted) setState(() => _showOnboarding = false);
      });
    }
    if (_initing) {
      return Scaffold(
        backgroundColor: _bg,
        body: Container(
          decoration: const BoxDecoration(
            gradient: RadialGradient(
              center: Alignment(0, -0.1), radius: 1.2,
              colors: [Color(0xFF003E5C), _bg],
            ),
          ),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // 큰 AuraView 브랜드 로고
              Container(
                width: 140, height: 140,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: const RadialGradient(
                    colors: [Color(0xFFE8F8FF), _accent, _accent2],
                    stops: [0.0, 0.5, 1.0],
                  ),
                  boxShadow: [
                    BoxShadow(color: _accent.withValues(alpha: 0.55), blurRadius: 50, spreadRadius: 4),
                    BoxShadow(color: _accent2.withValues(alpha: 0.30), blurRadius: 80, spreadRadius: 8),
                  ],
                ),
                child: const Center(
                  child: Text('A',
                    style: TextStyle(
                      fontSize: 64, fontWeight: FontWeight.w900,
                      color: _bg, letterSpacing: -2,
                      shadows: [Shadow(color: Color(0x66FFFFFF), blurRadius: 6)],
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 28),
              const Text('Aura',
                style: TextStyle(color: _muted, fontSize: 32, fontWeight: FontWeight.w300, letterSpacing: 4),
              ),
              Text('VIEW',
                style: TextStyle(color: _accent, fontSize: 32, fontWeight: FontWeight.w900, letterSpacing: 8,
                                 shadows: [Shadow(color: _accent.withValues(alpha:0.5), blurRadius: 16)]),
              ),
              const SizedBox(height: 32),
              SizedBox(
                width: 24, height: 24,
                child: CircularProgressIndicator(color: _accent, strokeWidth: 2),
              ),
              const SizedBox(height: 14),
              Text('K-Perception 시작 중…',
                style: TextStyle(color: _muted, fontSize: 11, letterSpacing: 2,
                                 fontFamily: 'monospace')),
            ],
          ),
        ),
      );
    }

    return Scaffold(
      backgroundColor: _bg,
      body: GestureDetector(
        onVerticalDragEnd: (d) {
          if (d.primaryVelocity != null && d.primaryVelocity! < -100) {
            _openDetailSheet();
          }
        },
        child: Stack(
          fit: StackFit.expand,
          children: [
            // 배경 그라디언트 (BEV 위로 통과)
            Container(
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topCenter, end: Alignment.bottomCenter,
                  colors: [Color(0xFF0A0F18), Color(0xFF04080E)],
                ),
              ),
            ),

            // ─── 메인 레이아웃: 상단 status / BEV 메인 / 카메라 PiP / 드라이브 버튼 ───
            SafeArea(
              child: Column(
                children: [
                  // v11 2026-05-19: 전면 디자인 개편 — _IdleStatusCard 폐기, 단일 slim 헤더
                  //   1줄 헤더: AuraView · speed · 검출 · uploads · 위험알림 · ⚙
                  Padding(
                    padding: const EdgeInsets.fromLTRB(12, 10, 12, 0),
                    child: _UnifiedStatusBar(
                      shadowOn: _shadowOn,
                      uploads: _uploads,
                      online: _serverError.isEmpty,
                      pos: _pos,
                      totalKm: _totalKm,
                      onSettingsTap: _openDetailSheet,
                    ),
                  ),
                  // 위험 신호가 있을 때만 SignalHud 컴팩트 표시
                  if (_altSignal != null) Padding(
                    padding: const EdgeInsets.fromLTRB(12, 6, 12, 0),
                    child: _SignalHud(
                      altSignal: _altSignal!,
                      intersectionName: _autoIntersectionName ??
                          (_intersectionId != null ? '교차로 $_intersectionId' : ''),
                      pulse: _lastReason == 'signal_occluded',
                    ),
                  ),
                  // v12.10: HUD chips (TAAS/우천/ER/스쿨존/BIS/DTG/119) — 데이터 있을 때만
                  //   v12.11: _fusion summary 가 비어있으면 strip 자체 안 보임
                  if (_fusion?['fusion_summary'] != null) Padding(
                    padding: const EdgeInsets.fromLTRB(12, 6, 12, 0),
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        color: Colors.black.withValues(alpha: 0.42),
                        border: Border.all(color: _accent.withValues(alpha: 0.20), width: 0.6),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: _CityInfoLine(fusion: _fusion!, busLive: _busLive),
                    ),
                  ),
                  const SizedBox(height: 6),

                  // BEV split — 화면 거의 전체 사용 (하단 floating REC 자리만 비움)
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(8, 0, 8, 56),
                      child: _CameraBevSplit(
                        camera: _cam,
                        detections: _bevDetections,
                        rawDetections: _rawDetections,
                        imgW: _bevImgW,
                        imgH: _bevImgH,
                        fps: _detectFps,
                        serverLiveSources: _serverLiveSourceCount,
                        serverTotalSources: _serverSourceCount,
                        serverSchema: _serverSchema,
                        lastFusionOk: _lastFusionFetchOk,
                      ),
                    ),
                  ),
                  const SizedBox(height: 0),
                ],
              ),
            ),

            // 4) 카메라 PiP — 좌하단 (140×100). 권한 없으면 _CameraPlaceholder.
            // v10: 별도 PiP 제거 — 카메라가 _CameraBevSplit 상단에 메인으로 들어감

            // 5) 캡처 펄스 링 (BEV 위에 깜빡)
            AnimatedBuilder(
              animation: _pulseAnim,
              builder: (_, __) {
                if (_pulseAnim.value == 0) return const SizedBox.shrink();
                final t = _pulseAnim.value;
                return IgnorePointer(
                  child: Align(
                    alignment: const Alignment(0, -0.05),
                    child: Container(
                      width: 200 + 240 * t,
                      height: 200 + 240 * t,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        border: Border.all(
                          color: _safe.withValues(alpha: (1 - t) * 0.55),
                          width: 2,
                        ),
                      ),
                    ),
                  ),
                );
              },
            ),

            // 6) 자동 캡처 reason 배지 (캡처 직후)
            if (_shadowOn && _lastReason != 'ok' && _lastReason != 'idle')
              Positioned(
                top: 200, left: 0, right: 0,
                child: Center(child: _LiveBadge(reason: _reasonKo(_lastReason))),
              ),

            // v11 2026-05-19: 큰 _DriveButton 폐기 → 하단 floating REC pill (소형)
            SafeArea(
              minimum: const EdgeInsets.only(bottom: 6),
              child: Align(
                alignment: Alignment.bottomCenter,
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: _RecPill(on: _shadowOn, onTap: _toggleShadow),
                ),
              ),
            ),

            // v11.1 2026-05-19: 검출 디버그 pill (왜 안 잡히는지 표시)
            Positioned(
              left: 10, bottom: 56,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: const Color(0xDD000000),
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(
                    color: (_detectRawN > 0 ? _safe : _warn).withValues(alpha: 0.5),
                    width: 0.8),
                ),
                child: Text(
                  '🔍 $_detectDebug${_detectLastAt != null ? " · ${DateTime.now().difference(_detectLastAt!).inSeconds}s ago" : ""}',
                  style: TextStyle(
                    color: _detectRawN > 0 ? _safe : _warn,
                    fontSize: 9, fontFamily: 'monospace', fontWeight: FontWeight.w800),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────
// Widgets
// ─────────────────────────────────────────────────────────────────

class _FrameFeat {
  final double entropy;
  final double motion;
  const _FrameFeat(this.entropy, this.motion);
}

class _FullCameraPreview extends StatelessWidget {
  final CameraController controller;
  const _FullCameraPreview({required this.controller});

  @override
  Widget build(BuildContext context) {
    // v12.3: 카메라가 좁은 세로 띠로 보이는 문제 수정 — FittedBox.cover 로 카드 전체 채움
    //   카메라 native preview 는 보통 landscape sensor (e.g., 1280×720).
    //   portrait 화면에 cover 시키려면 가로/세로 비율 뒤집고 BoxFit.cover 로 crop fit.
    if (!controller.value.isInitialized) return const SizedBox.shrink();
    final previewSize = controller.value.previewSize;
    if (previewSize == null) return const SizedBox.shrink();
    return LayoutBuilder(builder: (ctx, c) {
      // sensor 가 landscape (가로 길이 > 세로) 인 경우 ar 반전
      final sensorAR = previewSize.width / previewSize.height;   // > 1 means landscape sensor
      // portrait 화면 (c.maxWidth < c.maxHeight) 에 보여줄 땐 90° 회전되어 좁은 세로로 보임 → ar 반전
      final displayAR = 1.0 / sensorAR;   // = h/w of sensor = w/h on screen after rotation
      return ClipRect(
        child: SizedBox.expand(
          child: FittedBox(
            fit: BoxFit.cover,
            child: SizedBox(
              width: displayAR < 1
                ? c.maxHeight * displayAR
                : c.maxWidth,
              height: displayAR < 1
                ? c.maxHeight
                : c.maxWidth / displayAR,
              child: CameraPreview(controller),
            ),
          ),
        ),
      );
    });
  }
}

// ─────────────────────────────────────────────────────────────────
// 통합 상태 배지 + 큰 주행 버튼 (개편: 모든 chip 합침)
// ─────────────────────────────────────────────────────────────────

class _UnifiedStatusBar extends StatelessWidget {
  final bool shadowOn;
  final int uploads;
  final bool online;
  final Position? pos;
  final double totalKm;   // v12.12: 총 주행거리 km
  final VoidCallback? onSettingsTap;
  const _UnifiedStatusBar({
    required this.shadowOn,
    required this.uploads,
    required this.online,
    required this.pos,
    this.totalKm = 0,
    this.onSettingsTap,
  });

  @override
  Widget build(BuildContext context) {
    final hasGps = pos != null;
    final speedKmh = hasGps ? (pos!.speed * 3.6) : 0.0;
    final speedStr = speedKmh < 0.5 ? '정지' : speedKmh.toStringAsFixed(0);
    final speedIsStop = speedKmh < 0.5;
    final brandCol = shadowOn ? _danger : _accent;
    // Tesla 스타일: pure black glass + 큰 숫자 + uppercase tracking + thin divider
    return ClipRRect(
      borderRadius: BorderRadius.circular(18),
      child: BackdropFilter(
        filter: ui.ImageFilter.blur(sigmaX: 16, sigmaY: 16),
        child: Container(
          padding: const EdgeInsets.fromLTRB(14, 8, 8, 8),
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topLeft, end: Alignment.bottomRight,
              colors: [
                Colors.black.withValues(alpha: 0.55),
                Colors.black.withValues(alpha: 0.30),
              ],
            ),
            border: Border.all(color: Colors.white.withValues(alpha: 0.06), width: 0.8),
            borderRadius: BorderRadius.circular(18),
          ),
          child: Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
            // 브랜드 dot — 글로우 (status indicator)
            Container(
              width: 10, height: 10,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: brandCol,
                boxShadow: [BoxShadow(color: brandCol, blurRadius: 8)],
              ),
            ),
            const SizedBox(width: 10),
            // 브랜드 로고
            const Text('AURAVIEW',
              style: TextStyle(
                color: Colors.white, fontSize: 13, fontWeight: FontWeight.w900,
                letterSpacing: 2.5, height: 1.0,
              )),
            const SizedBox(width: 14),
            Container(width: 1, height: 22, color: Colors.white.withValues(alpha: 0.10)),
            const SizedBox(width: 14),
            // 속도 — Tesla 시그니처 큰 숫자 (0이면 "정지")
            Text(speedStr,
              style: TextStyle(
                color: speedIsStop ? Colors.white.withValues(alpha: 0.55) : Colors.white,
                fontSize: speedIsStop ? 18 : 28, fontWeight: FontWeight.w900,
                fontFeatures: const [FontFeature.tabularFigures()],
                letterSpacing: -1, height: 1.0,
              )),
            if (!speedIsStop) ...[
              const SizedBox(width: 4),
              Text('KM/H',
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.45), fontSize: 10,
                  fontWeight: FontWeight.w800, letterSpacing: 1.5, height: 1.0,
                )),
            ],
            // v12.12: 총 주행거리 chip (km, 누적)
            if (totalKm > 0.05) ...[
              const SizedBox(width: 10),
              Container(width: 1, height: 18, color: Colors.white.withValues(alpha: 0.10)),
              const SizedBox(width: 10),
              Icon(Icons.route_rounded, size: 12, color: _accent.withValues(alpha: 0.65)),
              const SizedBox(width: 4),
              Text(totalKm < 10 ? totalKm.toStringAsFixed(2) : totalKm.toStringAsFixed(1),
                style: TextStyle(color: _accent.withValues(alpha: 0.85), fontSize: 13,
                  fontWeight: FontWeight.w800, fontFeatures: const [FontFeature.tabularFigures()],
                  letterSpacing: -0.2, height: 1.0)),
              const SizedBox(width: 3),
              Text('km',
                style: TextStyle(color: Colors.white.withValues(alpha: 0.35), fontSize: 9,
                  fontWeight: FontWeight.w800, letterSpacing: 1, height: 1.0)),
            ],
            const Spacer(),
            // 우측 chip — 명확한 한글 라벨
            _TeslaChip(
              icon: shadowOn ? Icons.fiber_manual_record_rounded : Icons.fiber_manual_record_outlined,
              label: shadowOn ? 'REC' : '대기',
              color: shadowOn ? _danger : Colors.white.withValues(alpha: 0.40),
              filled: shadowOn,
            ),
            const SizedBox(width: 6),
            _TeslaChip(
              icon: Icons.upload_rounded,
              label: '기여 $uploads',
              color: uploads > 0 ? _safe : Colors.white.withValues(alpha: 0.40),
              filled: false,
            ),
            const SizedBox(width: 6),
            _TeslaChip(
              icon: online ? Icons.cloud_done_rounded : Icons.cloud_off_rounded,
              label: online ? '서버' : '오프라인',
              color: online ? _safe : _danger,
              filled: false,
            ),
            const SizedBox(width: 8),
            // v12.11: ★ 버튼 제거 — 웹 페이지 wrap 이라 네이티브 기능 아님 (사용자 지적)
            //   심사 페이지 보고 싶으면 브라우저로 https://auraview.allthatai.kr/scorecard/
            // ⚙ 설정
            GestureDetector(
              onTap: onSettingsTap,
              behavior: HitTestBehavior.opaque,
              child: Container(
                width: 40, height: 40,
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.08),
                  border: Border.all(color: Colors.white.withValues(alpha: 0.18), width: 1),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(Icons.tune_rounded, size: 19, color: Colors.white.withValues(alpha: 0.85)),
              ),
            ),
          ]),
        ),
      ),
    );
  }
  static Color _border() => const Color(0x2200C8FF);
}

// v11.2 2026-05-19: Tesla 스타일 작은 인포 chip
class _TeslaChip extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  final bool filled;
  const _TeslaChip({required this.icon, required this.label, required this.color, this.filled = false});
  @override
  Widget build(BuildContext context) {
    return Container(
      height: 26,
      padding: const EdgeInsets.symmetric(horizontal: 8),
      decoration: BoxDecoration(
        color: filled ? color.withValues(alpha: 0.18) : Colors.white.withValues(alpha: 0.04),
        border: Border.all(color: color.withValues(alpha: filled ? 0.55 : 0.18), width: 0.8),
        borderRadius: BorderRadius.circular(99),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, size: 11, color: color),
        const SizedBox(width: 4),
        Text(label,
          style: TextStyle(color: color, fontSize: 10, fontWeight: FontWeight.w900,
            letterSpacing: 1.0, height: 1.0)),
      ]),
    );
  }
}

class _DriveButton extends StatelessWidget {
  final bool on;
  final VoidCallback onTap;
  const _DriveButton({required this.on, required this.onTap});

  @override
  Widget build(BuildContext context) {
    // v6 2026-05-18: 디자인 개선 — 모니터링 중 (녹색·펄스 dot), 정지 시 (안내 cyan)
    final activeStartColor  = const Color(0xFF00E09A);   // 안전 녹
    final activeEndColor    = const Color(0xFF00A872);
    final inactiveStartColor = const Color(0xFF00C8FF);
    final inactiveEndColor  = const Color(0xFF0080B0);
    final startColor = on ? activeStartColor : inactiveStartColor;
    final endColor   = on ? activeEndColor   : inactiveEndColor;
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 240),
        width: 260, height: 64,
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft, end: Alignment.bottomRight,
            colors: [startColor, endColor],
          ),
          borderRadius: BorderRadius.circular(34),
          border: Border.all(color: Colors.white.withValues(alpha: 0.18), width: 1.2),
          boxShadow: [
            BoxShadow(color: startColor.withValues(alpha: 0.55), blurRadius: 28, spreadRadius: 1),
            BoxShadow(color: Colors.black.withValues(alpha: 0.35), blurRadius: 12, offset: const Offset(0, 6)),
          ],
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (on) ...[
              // 모니터링 중 — 펄스 dot
              Container(
                width: 10, height: 10,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: Colors.white,
                  boxShadow: [BoxShadow(color: Colors.white.withValues(alpha: 0.85), blurRadius: 8)],
                ),
              ),
              const SizedBox(width: 12),
            ] else
              const Icon(Icons.play_arrow_rounded, size: 28, color: Colors.white),
            if (!on) const SizedBox(width: 6),
            Text(on ? '주행 모니터링 중' : '주행 시작',
                 style: const TextStyle(color: Colors.white, fontSize: 17,
                                        fontWeight: FontWeight.w900, letterSpacing: 1.0)),
          ],
        ),
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────
// BEV 오버레이 — 도시정보 결합 (Tesla-style 단안 카메라 + signal/VDS/TAAS)
// ─────────────────────────────────────────────────────────────────

class _BevPanel extends StatefulWidget {
  final Map<String, dynamic>? bev;
  final Map<String, dynamic>? fusion;
  final Map<String, dynamic>? busLive;   // v2 2026-05-15: BIS 실시간 버스
  final bool demoMode;            // ★ true 면 DEMO 시나리오 표시
  final String? scenarioLabel;    // 활성 시나리오 명 (DEMO 모드일 때만)
  final VoidCallback? onToggleDemo;
  final bool fillScreen;          // ★ true: Tesla 모니터 모드 (Expanded 부모, 큰 화면)
  const _BevPanel({this.bev, this.fusion, this.busLive, this.demoMode = false, this.scenarioLabel, this.onToggleDemo, this.fillScreen = false});

  @override
  State<_BevPanel> createState() => _BevPanelState();
}

class _BevPanelState extends State<_BevPanel>
    with SingleTickerProviderStateMixin {
  late Ticker _ticker;

  // ── 사용자 컨트롤 상태 (drag/pinch) ──
  double _zoom = 1.0;          // 1.0 = 기본, 0.5 ~ 2.5
  double _baseZoom = 1.0;
  double _yawDeg = 0;          // -45 ~ 45 (좌우 회전)
  double _baseYaw = 0;
  Offset _baseFocal = Offset.zero;
  // FPS 추적
  final List<double> _frameTimes = [];
  double _fps = 0;

  void _resetView() {
    setState(() { _zoom = 1.0; _yawDeg = 0; });
  }

  @override
  void initState() {
    super.initState();
    // v5 2026-05-17 최적화: setState 매 프레임 X
    // → 30 FPS 캡 (33ms 간격) + RepaintBoundary 안의 painter 만 repaint
    // 부모 위젯 rebuild 차단으로 배터리·발열 대폭 감소
    double lastT = 0;
    _ticker = Ticker((d) {
      final now = d.inMilliseconds / 1000.0;
      // 30 FPS 캡: 33ms 미만이면 skip
      if ((now - lastT) < 0.033) return;
      lastT = now;
      // FPS 추적
      _frameTimes.add(now);
      while (_frameTimes.isNotEmpty && now - _frameTimes.first > 0.5) {
        _frameTimes.removeAt(0);
      }
      _fps = _frameTimes.length * 2.0;
      // setState 대신 ValueNotifier 변경만 — RepaintBoundary 안의 CustomPaint 만 repaint
      _tNotifier.value = now;
    })..start();
  }
  late final ValueNotifier<double> _tNotifier = ValueNotifier<double>(0);

  @override
  void dispose() {
    _ticker.dispose();
    _tNotifier.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isDemo = widget.demoMode;
    final modeColor = isDemo ? _warn : _safe;
    final modeLabel = isDemo ? 'DEMO' : 'LIVE';

    // BEV 캔버스 — Expanded 로 가용 공간 모두 사용 (Size.infinite 명시)
    // 사용자 컨트롤: 핀치 → zoom, 드래그 좌우 → yaw, 더블탭 → 리셋
    final bevCanvas = ClipRRect(
      borderRadius: BorderRadius.circular(10),
      child: GestureDetector(
        onScaleStart: (d) {
          _baseZoom = _zoom;
          _baseYaw = _yawDeg;
          _baseFocal = d.focalPoint;
        },
        onScaleUpdate: (d) {
          setState(() {
            if (d.pointerCount >= 2) {
              // 핀치 (2 손가락) → 줌만
              _zoom = (_baseZoom * d.scale).clamp(0.5, 2.5);
            } else {
              // 단일 손가락 드래그 → yaw 회전만
              final dx = d.focalPoint.dx - _baseFocal.dx;
              _yawDeg = (_baseYaw + dx * 0.25).clamp(-60.0, 60.0);
            }
          });
        },
        onDoubleTap: _resetView,
        child: ColoredBox(
          color: const Color(0xFF0A1018),
          child: Stack(fit: StackFit.expand, children: [
            // v5 2026-05-17: RepaintBoundary + ValueListenableBuilder
            // → BEV CustomPaint 만 repaint, 부모 위젯 rebuild 차단 (배터리·발열 감소)
            RepaintBoundary(
              child: ValueListenableBuilder<double>(
                valueListenable: _tNotifier,
                builder: (_, t, __) => CustomPaint(
                  size: Size.infinite,
                  painter: _Bev3DVoxelPainter(bev: widget.bev, t: t, zoom: _zoom, yawDeg: _yawDeg, fps: _fps),
                ),
              ),
            ),
            // v2 2026-05-15: BIS 라이브 버스 작은 마커 오버레이 (상단 우측)
            if (widget.busLive != null &&
                ((widget.busLive!['count'] is num) ? (widget.busLive!['count'] as num).toInt() : 0) > 0)
              Positioned(top: 8, right: 8, child: _BisBusBadge(busLive: widget.busLive!)),
          ]),
        ),
      ),
    );

    final header = Row(children: [
      Icon(Icons.view_in_ar, size: 14, color: _accent),
      const SizedBox(width: 4),
      Text('BEV · 3D OCCUPANCY',
           style: TextStyle(color: _accent, fontSize: 11,
                            fontWeight: FontWeight.w800, letterSpacing: 1.5)),
      const Spacer(),
      // 모드 토글
      GestureDetector(
        onTap: widget.onToggleDemo,
        behavior: HitTestBehavior.opaque,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
          decoration: BoxDecoration(
            color: modeColor.withValues(alpha: 0.22),
            borderRadius: BorderRadius.circular(99),
          ),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Container(
              width: 7, height: 7,
              decoration: BoxDecoration(
                color: modeColor, shape: BoxShape.circle,
                boxShadow: [BoxShadow(color: modeColor, blurRadius: 6)],
              ),
            ),
            const SizedBox(width: 5),
            Text(modeLabel,
                 style: TextStyle(color: modeColor, fontSize: 10,
                                  fontWeight: FontWeight.w900, letterSpacing: 0.8)),
          ]),
        ),
      ),
    ]);

    final subtitle = Padding(
      padding: const EdgeInsets.only(top: 3, left: 19),
      child: Row(children: [
        Expanded(
          child: Text(
            isDemo ? (widget.scenarioLabel ?? 'DEMO 시나리오') : '카메라 voxel · 실시간',
            style: TextStyle(
              color: modeColor.withValues(alpha: 0.85),
              fontSize: 9.5,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.4,
            ),
          ),
        ),
        // 줌/리셋 힌트 (탭 가능한 텍스트)
        if (_zoom != 1.0 || _yawDeg != 0)
          GestureDetector(
            onTap: _resetView,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: _accent.withValues(alpha: 0.18),
                borderRadius: BorderRadius.circular(99),
              ),
              child: Text(
                '⟲ ${_zoom.toStringAsFixed(1)}× ${_yawDeg.toStringAsFixed(0)}°',
                style: TextStyle(color: _accent, fontSize: 8, fontWeight: FontWeight.w800),
              ),
            ),
          )
        else
          Text('핀치/드래그/더블탭', style: TextStyle(color: _muted, fontSize: 8, fontWeight: FontWeight.w600)),
      ]),
    );

    if (widget.fillScreen) {
      // 테슬라 모니터 모드: 부모 Expanded → 가용 공간 모두 BEV 캔버스
      return Container(
        padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
        decoration: BoxDecoration(
          color: _bg.withValues(alpha: 0.55),
          borderRadius: BorderRadius.circular(16),
          boxShadow: [BoxShadow(color: modeColor.withValues(alpha: 0.30), blurRadius: 24, spreadRadius: 1)],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            header,
            subtitle,
            const SizedBox(height: 8),
            Expanded(child: bevCanvas),
            const SizedBox(height: 6),
            if (widget.bev != null) _BevStatLine(bev: widget.bev!),
            if (widget.fusion != null) _CityInfoLine(fusion: widget.fusion!, busLive: widget.busLive),
          ],
        ),
      );
    }

    // (legacy) 코너 미니 모드 — 사용 안 함
    final screenW = MediaQuery.of(context).size.width;
    final panelW = (screenW * 0.42).clamp(220.0, 320.0);
    return Container(
      width: panelW,
      padding: const EdgeInsets.fromLTRB(8, 6, 8, 8),
      decoration: BoxDecoration(
        color: _bg.withValues(alpha: 0.78),
        borderRadius: BorderRadius.circular(14),
        boxShadow: [BoxShadow(color: modeColor.withValues(alpha: 0.35), blurRadius: 18, spreadRadius: 1)],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          header,
          subtitle,
          AspectRatio(aspectRatio: 1.0, child: bevCanvas),
          const SizedBox(height: 6),
          if (widget.bev != null) _BevStatLine(bev: widget.bev!),
          if (widget.fusion != null) _CityInfoLine(fusion: widget.fusion!, busLive: widget.busLive),
        ],
      ),
    );
  }
}

class _BevStatLine extends StatelessWidget {
  final Map<String, dynamic> bev;
  const _BevStatLine({required this.bev});
  @override
  Widget build(BuildContext context) {
    final rs = bev['risk_summary'] as Map<String, dynamic>?;
    if (rs == null) return const SizedBox.shrink();
    final p = ((rs['p_collision'] ?? 0) as num).toDouble();
    final lead = ((rs['lead_time_s'] ?? 0) as num).toDouble();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(children: [
        Text('${(p * 100).toStringAsFixed(0)}% 충돌',
             style: const TextStyle(color: _danger, fontSize: 11,
                                    fontWeight: FontWeight.w700)),
        const SizedBox(width: 8),
        Text('·', style: TextStyle(color: _muted)),
        const SizedBox(width: 8),
        Text('${lead.toStringAsFixed(1)}s 선행',
             style: const TextStyle(color: _safe, fontSize: 11,
                                    fontWeight: FontWeight.w700)),
      ]),
    );
  }
}

class _CityInfoLine extends StatelessWidget {
  final Map<String, dynamic> fusion;
  final Map<String, dynamic>? busLive;   // v2 2026-05-15: BIS 실시간 버스
  const _CityInfoLine({required this.fusion, this.busLive});
  @override
  Widget build(BuildContext context) {
    final src = fusion['sources'] as Map<String, dynamic>?;
    final summary = fusion['fusion_summary'] as Map<String, dynamic>?;
    String sigState = '?', vdsKmh = '?', taas = '?';
    try {
      // v12.19: stub 신호 정확성 — "unknown" 은 chip 미표시 (집/임의 위치)
      final sig = src?['signal']?['body']?['items']?['item']?['stPdsgSttsNm'];
      if (sig is String && sig != 'unknown') {
        if (sig.toLowerCase().contains('stop')) sigState = '정지';
        else if (sig.toLowerCase().contains('warn')) sigState = '주의';
        else if (sig == 'go') sigState = '진행';
        else sigState = sig;
      }
      final vds = src?['vds']?['list'];
      if (vds is List && vds.isNotEmpty) {
        final v = vds[0];
        if (v is Map && v['speed'] != null) vdsKmh = '${v['speed']}km/h';
      }
      // v12.20: 정확한 경로 — summary.taas_accidents_nearby (fusion 계산 결과)
      // 0건이면 chip 자체 미표시 (집/임의 위치 거짓 알람 차단)
      final acc = summary?['taas_accidents_nearby'];
      if (acc is num && acc > 0) taas = '$acc';
    } catch (_) {}

    // ── v2 2026-05-15: 9-source 신호 (기상/응급실/자전거) ──
    final bool isRaining = (summary?['weather_raining'] == true);
    final double wetBoost = (summary?['wet_road_risk_boost'] is num) ? (summary!['wet_road_risk_boost'] as num).toDouble() : 0.0;
    final double erLoad   = (summary?['nearest_ER_load'] is num) ? (summary!['nearest_ER_load'] as num).toDouble() : 0.0;
    final double severityMul = (summary?['severity_multiplier'] is num) ? (summary!['severity_multiplier'] as num).toDouble() : 1.0;
    final double bikeBoost = (summary?['bike_lane_risk_boost'] is num) ? (summary!['bike_lane_risk_boost'] as num).toDouble() : 0.0;
    final int sourcesFused = (summary?['sources_fused'] is num) ? (summary!['sources_fused'] as num).toInt() : 0;

    final showWeather = isRaining || wetBoost > 0.05;
    final showER = erLoad >= 0.6;            // 응급실 포화 60%↑ 이상일 때 노출
    final showBike = bikeBoost > 0.05;

    // ── v3 2026-05-16: 12-source (스쿨존/결빙/보행자 다발) ──
    final bool inSchoolZone = (summary?['in_school_zone'] == true);
    final double szMul = (summary?['school_zone_multiplier'] is num) ? (summary!['school_zone_multiplier'] as num).toDouble() : 1.0;
    final bool blackIce = (summary?['black_ice_risk'] == true);
    final double freezeBoost = (summary?['freeze_risk_boost'] is num) ? (summary!['freeze_risk_boost'] as num).toDouble() : 0.0;
    final bool inPedHotspot = (summary?['in_pedestrian_hotspot'] == true);
    final double pedBoost = (summary?['ped_hotspot_boost'] is num) ? (summary!['ped_hotspot_boost'] as num).toDouble() : 0.0;

    // ── v4 2026-05-16: 15-source (미세먼지/통학로/EV) ──
    final double pm10 = (summary?['pm10_avg'] is num) ? (summary!['pm10_avg'] as num).toDouble() : 0.0;
    final double airBoost = (summary?['air_quality_risk_boost'] is num) ? (summary!['air_quality_risk_boost'] as num).toDouble() : 0.0;
    final bool onSchoolRoute = (summary?['on_school_route'] == true);
    final double walkBoost = (summary?['walk_route_boost'] is num) ? (summary!['walk_route_boost'] as num).toDouble() : 0.0;
    final bool nearEv = (summary?['near_ev_station'] == true);
    final double evDwelling = (summary?['ev_dwelling_likelihood'] is num) ? (summary!['ev_dwelling_likelihood'] as num).toDouble() : 0.0;

    // v5 2026-05-18: 17-source (도로 노면 + KOTSA 자동차검사)
    final String roadSurface = (summary?['road_surface']?.toString() ?? 'dry');
    final double surfaceBoost = (summary?['surface_risk_boost'] is num) ? (summary!['surface_risk_boost'] as num).toDouble() : 0.0;
    final bool lowVis = (summary?['low_visibility_flag'] == true);
    final double inspBoost = (summary?['inspection_risk_boost'] is num) ? (summary!['inspection_risk_boost'] as num).toDouble() : 0.0;
    final double inspFailRate = (summary?['inspection_fail_rate_district'] is num) ? (summary!['inspection_fail_rate_district'] as num).toDouble() : 0.0;

    // v6 2026-05-18: 19-source (KOTSA DTG + 소방청 119 출동)
    final double dtgBoost = (summary?['dtg_risk_boost'] is num) ? (summary!['dtg_risk_boost'] as num).toDouble() : 0.0;
    final double dtgDanger = (summary?['dtg_danger_score'] is num) ? (summary!['dtg_danger_score'] as num).toDouble() : 0.0;
    final double nfaSeverityMul = (summary?['nfa_severity_multiplier'] is num) ? (summary!['nfa_severity_multiplier'] as num).toDouble() : 1.0;
    final bool goldenAtRisk = (summary?['golden_time_at_risk'] == true);

    final showSchoolZone = inSchoolZone && szMul > 1.0;
    final showBlackIce = blackIce || freezeBoost > 0.05;
    final showPedHotspot = inPedHotspot && pedBoost > 0.05;
    final showAir = pm10 >= 80 || airBoost > 0.04;
    final showWalkRoute = onSchoolRoute && walkBoost > 0.05;
    final showEv = nearEv && evDwelling >= 0.7;
    final showSurface = surfaceBoost > 0.05 || lowVis;
    final showInsp = inspBoost > 0.02;
    final showDtg = dtgBoost > 0.03 || dtgDanger > 0.6;
    final showGolden = goldenAtRisk || nfaSeverityMul > 1.10;

    // v12.13: v7 21-source 신규 필드 추출 + 표시 조건
    final double roadAgeBoost = (summary?['road_age_risk_boost'] is num) ? (summary!['road_age_risk_boost'] as num).toDouble() : 0.0;
    final double agedPct      = (summary?['road_aged_15y_plus_pct'] is num) ? (summary!['road_aged_15y_plus_pct'] as num).toDouble() : 0.0;
    final double avConfidence = (summary?['av_confidence'] is num) ? (summary!['av_confidence'] as num).toDouble() : 0.0;
    final double avRiskReduce = (summary?['av_risk_reduce'] is num) ? (summary!['av_risk_reduce'] as num).toDouble() : 0.0;
    final bool highV2xZone    = (summary?['high_v2x_zone'] == true);
    final bool showRoadAge    = roadAgeBoost > 0.03 || agedPct > 0.40;
    final bool showAvHub      = highV2xZone || avRiskReduce > 0.02;

    // v12.21: v8 22-source — 경찰청 교통단속 CCTV (사고다발 prior + 운전 주의)
    final int enfCamCount     = (summary?['enforcement_cam_count'] is num) ? (summary!['enforcement_cam_count'] as num).toInt() : 0;
    final double enfBoost     = (summary?['enforcement_risk_boost'] is num) ? (summary!['enforcement_risk_boost'] as num).toDouble() : 0.0;
    final bool isEnfHotzone   = (summary?['is_enforcement_hotzone'] == true);
    final bool showEnfCam     = enfCamCount >= 1 || isEnfHotzone;

    // v12.23: v9 23-source — 국토부 횡단보도 GIS (보행자 안전 + 50m 접근 알림)
    final int cwCount         = (summary?['crosswalk_count_within_radius'] is num) ? (summary!['crosswalk_count_within_radius'] as num).toInt() : 0;
    final bool approachingCw  = (summary?['approaching_crosswalk'] == true);
    final int cwSchoolCount   = (summary?['school_zone_crosswalk_count'] is num) ? (summary!['school_zone_crosswalk_count'] as num).toInt() : 0;
    final bool showCrosswalk  = approachingCw || cwCount >= 2 || cwSchoolCount >= 1;

    // v12.13: 종합 위험 점수 (대표 표시용)
    final double fusionRisk   = (summary?['fusion_risk_score'] is num) ? (summary!['fusion_risk_score'] as num).toDouble() : 0.0;
    final String riskLevel    = summary?['risk_level']?.toString() ?? 'UNKNOWN';

    // v12.11: "?" chip 숨김 — 데이터 있을 때만 표시 (비활성 아이콘 제거)
    final hasSig  = sigState != '?';
    final hasVds  = vdsKmh   != '?';
    final hasTaas = taas     != '?';
    // v12.20: 임의 GPS (gps-*) 위치 인식 배지 — 데이터 출처 투명성
    final iidStr = fusion['intersection_id']?.toString() ?? '';
    final isGpsMode = iidStr.startsWith('gps-');
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Wrap(
        spacing: 10, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          // v12.20: 위치 인식 모드 표시 (gps-* iid → 실제 GPS 기반)
          if (isGpsMode)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
              decoration: BoxDecoration(
                color: const Color(0xFF202A38),
                border: Border.all(color: _accent.withValues(alpha: 0.4), width: 0.6),
                borderRadius: BorderRadius.circular(99),
              ),
              child: Text('GPS', style: TextStyle(color: _accent, fontSize: 9, fontWeight: FontWeight.w800, letterSpacing: 0.4)),
            ),
          // v12.13: 종합 위험 점수 chip (가장 먼저 — 운전자가 즉시 보게)
          if (fusionRisk > 0)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: riskLevel == 'HIGH' ? _danger.withValues(alpha: 0.22)
                       : riskLevel == 'MEDIUM' ? _warn.withValues(alpha: 0.22)
                       : _safe.withValues(alpha: 0.18),
                  border: Border.all(
                    color: (riskLevel == 'HIGH' ? _danger
                          : riskLevel == 'MEDIUM' ? _warn : _safe).withValues(alpha: 0.55),
                    width: 0.8),
                  borderRadius: BorderRadius.circular(99),
                ),
                child: Text('위험 ${fusionRisk.toStringAsFixed(2)}',
                  style: TextStyle(
                    color: riskLevel == 'HIGH' ? _danger
                         : riskLevel == 'MEDIUM' ? _warn : _safe,
                    fontSize: 11, fontWeight: FontWeight.w900, letterSpacing: 0.3)),
              ),
            ]),
          if (hasSig) Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.traffic, size: 13, color: _accent), const SizedBox(width: 4),
            Text(sigState, style: const TextStyle(color: _text, fontSize: 12, fontWeight: FontWeight.w700)),
          ]),
          if (hasVds) Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.speed, size: 11, color: _accent), const SizedBox(width: 3),
            Text(vdsKmh, style: const TextStyle(color: _text, fontSize: 10)),
          ]),
          if (hasTaas) Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.warning_amber, size: 11, color: _warn), const SizedBox(width: 3),
            Text('TAAS $taas', style: const TextStyle(color: _text, fontSize: 10)),
          ]),
          // v2: 기상 (비/시정)
          if (showWeather)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.water_drop, size: 11, color: const Color(0xFF6BAEFF)), const SizedBox(width: 3),
              Text(isRaining ? '우천 +${(wetBoost*100).toStringAsFixed(0)}%' : '시정↓',
                style: const TextStyle(color: Color(0xFF6BAEFF), fontSize: 10, fontWeight: FontWeight.w700)),
            ]),
          // v2: 응급실 포화
          if (showER)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.local_hospital, size: 11, color: const Color(0xFFFF6B6B)), const SizedBox(width: 3),
              Text('ER ${(erLoad*100).toStringAsFixed(0)}% ×${severityMul.toStringAsFixed(2)}',
                style: const TextStyle(color: Color(0xFFFF6B6B), fontSize: 10, fontWeight: FontWeight.w700)),
            ]),
          // v2: 자전거도로 prior
          if (showBike)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.directions_bike, size: 11, color: const Color(0xFFFFB020)), const SizedBox(width: 3),
              Text('자전거 +${(bikeBoost*100).toStringAsFixed(0)}%',
                style: const TextStyle(color: Color(0xFFFFB020), fontSize: 10, fontWeight: FontWeight.w700)),
            ]),
          // v3: 스쿨존 multiplier (등하교 시 ×1.5)
          if (showSchoolZone)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.school, size: 11, color: const Color(0xFFA095FF)), const SizedBox(width: 3),
              Text('스쿨존 ×${szMul.toStringAsFixed(1)}',
                style: const TextStyle(color: Color(0xFFA095FF), fontSize: 10, fontWeight: FontWeight.w800)),
            ]),
          // v3: 블랙아이스/결빙
          if (showBlackIce)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.ac_unit, size: 11, color: const Color(0xFF6BE3FF)), const SizedBox(width: 3),
              Text('${blackIce ? "결빙" : "노면"} +${(freezeBoost*100).toStringAsFixed(0)}%',
                style: const TextStyle(color: Color(0xFF6BE3FF), fontSize: 10, fontWeight: FontWeight.w800)),
            ]),
          // v3: 보행자 다발지역
          if (showPedHotspot)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.directions_walk, size: 11, color: const Color(0xFFFF8866)), const SizedBox(width: 3),
              Text('보행다발 +${(pedBoost*100).toStringAsFixed(0)}%',
                style: const TextStyle(color: Color(0xFFFF8866), fontSize: 10, fontWeight: FontWeight.w700)),
            ]),
          // v4: 미세먼지
          if (showAir)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.air, size: 11, color: const Color(0xFFAAB0BC)), const SizedBox(width: 3),
              Text('PM10 ${pm10.toStringAsFixed(0)}',
                style: const TextStyle(color: Color(0xFFAAB0BC), fontSize: 10, fontWeight: FontWeight.w700)),
            ]),
          // v4: 어린이 통학로
          if (showWalkRoute)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.backpack, size: 11, color: const Color(0xFFFFCB6B)), const SizedBox(width: 3),
              Text('통학로 +${(walkBoost*100).toStringAsFixed(0)}%',
                style: const TextStyle(color: Color(0xFFFFCB6B), fontSize: 10, fontWeight: FontWeight.w800)),
            ]),
          // v4: EV 충전소 정차 가능성
          if (showEv)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.ev_station, size: 11, color: const Color(0xFF7CE4B0)), const SizedBox(width: 3),
              Text('EV ${(evDwelling*100).toStringAsFixed(0)}%',
                style: const TextStyle(color: Color(0xFF7CE4B0), fontSize: 10, fontWeight: FontWeight.w700)),
            ]),
          // v5: 도로 노면 (RWIS)
          if (showSurface)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(roadSurface == 'frost' || roadSurface == 'ice' ? Icons.ac_unit
                   : roadSurface == 'snow' ? Icons.cloudy_snowing
                   : roadSurface == 'wet'  ? Icons.water
                   : Icons.opacity,
                size: 11, color: const Color(0xFF6BE3FF)), const SizedBox(width: 3),
              Text('${({"frost":"결빙","ice":"결빙","snow":"적설","wet":"습윤","dry":"건조"}[roadSurface] ?? roadSurface)} +${(surfaceBoost*100).toStringAsFixed(0)}%',
                style: const TextStyle(color: Color(0xFF6BE3FF), fontSize: 10, fontWeight: FontWeight.w800)),
            ]),
          // v5: 자동차검사 부적합률 (KOTSA)
          if (showInsp)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.build_circle_outlined, size: 11, color: const Color(0xFFA095FF)), const SizedBox(width: 3),
              Text('검사부적합 ${(inspFailRate*100).toStringAsFixed(1)}%',
                style: const TextStyle(color: Color(0xFFA095FF), fontSize: 10, fontWeight: FontWeight.w700)),
            ]),
          // v6: KOTSA DTG 사업용 차량 위험운전 (택시·버스·화물 ▲평균)
          if (showDtg)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.local_taxi, size: 11, color: const Color(0xFFFFB020)), const SizedBox(width: 3),
              Text('DTG ${dtgDanger.toStringAsFixed(2)} +${(dtgBoost*100).toStringAsFixed(0)}%',
                style: const TextStyle(color: Color(0xFFFFB020), fontSize: 10, fontWeight: FontWeight.w800)),
            ]),
          // v6: 119 골든타임 (평균 도착 > 7분)
          if (showGolden)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.emergency, size: 11, color: const Color(0xFFFF6B6B)), const SizedBox(width: 3),
              Text('119 ×${nfaSeverityMul.toStringAsFixed(2)}',
                style: const TextStyle(color: Color(0xFFFF6B6B), fontSize: 10, fontWeight: FontWeight.w800)),
            ]),
          // v12.13: v7 신규 — 도로 노후도 (행안부)
          if (showRoadAge)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.construction, size: 11, color: const Color(0xFFAAB0BC)), const SizedBox(width: 3),
              Text('노후 ${(agedPct*100).toStringAsFixed(0)}% +${(roadAgeBoost*100).toStringAsFixed(0)}%',
                style: const TextStyle(color: Color(0xFFAAB0BC), fontSize: 10, fontWeight: FontWeight.w700)),
            ]),
          // v12.13: v7 신규 — 자율주행 V2X (KOTSA)
          if (showAvHub)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.smart_toy, size: 11, color: const Color(0xFF7CE4B0)), const SizedBox(width: 3),
              Text('V2X ${(avConfidence*100).toStringAsFixed(0)}% −${(avRiskReduce*100).toStringAsFixed(0)}%',
                style: const TextStyle(color: Color(0xFF7CE4B0), fontSize: 10, fontWeight: FontWeight.w800)),
            ]),
          // v12.21: v8 신규 — 경찰청 교통단속 CCTV (사고다발 + 단속존 주의)
          if (showEnfCam)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.videocam, size: 11, color: isEnfHotzone ? _danger : _warn), const SizedBox(width: 3),
              Text(isEnfHotzone ? '단속존 ${enfCamCount}대' : '단속 ${enfCamCount}대 +${(enfBoost*100).toStringAsFixed(0)}%',
                style: TextStyle(color: isEnfHotzone ? _danger : _warn, fontSize: 10, fontWeight: FontWeight.w800)),
            ]),
          // v12.23: v9 신규 — 횡단보도 GIS (50m 접근 알림 + 스쿨존 횡단보도)
          if (showCrosswalk)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(approachingCw ? Icons.warning : Icons.crisis_alert,
                size: 11, color: approachingCw ? _danger : const Color(0xFFFF8866)), const SizedBox(width: 3),
              Text(approachingCw
                ? '횡단보도 50m'
                : (cwSchoolCount >= 1 ? '스쿨횡단 ${cwSchoolCount}' : '횡단 ${cwCount}'),
                style: TextStyle(color: approachingCw ? _danger : const Color(0xFFFF8866),
                  fontSize: 10, fontWeight: FontWeight.w800)),
            ]),
          // v9 배지: N종 융합 (23까지 확장)
          if (sourcesFused >= 7)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
              decoration: BoxDecoration(
                color: _safe.withValues(alpha: 0.15),
                border: Border.all(color: _safe.withValues(alpha: 0.45), width: 0.8),
                borderRadius: BorderRadius.circular(4),
              ),
              child: Text('${sourcesFused}src v${sourcesFused >= 23 ? "9" : (sourcesFused >= 22 ? "8" : (sourcesFused >= 21 ? "7" : (sourcesFused >= 19 ? "6" : (sourcesFused >= 17 ? "5" : (sourcesFused >= 15 ? "4" : (sourcesFused >= 12 ? "3" : "2"))))))}',
                style: TextStyle(color: _safe, fontSize: 9, fontWeight: FontWeight.w900, letterSpacing: 0.5)),
            ),
          // v2: BIS 실시간 버스 표시 (반경 150m 내 차량 수)
          if (busLive != null && ((busLive!['count'] is num) ? (busLive!['count'] as num).toInt() : 0) > 0)
            Builder(builder: (_) {
              final c = (busLive!['count'] as num).toInt();
              final mode = busLive!['mode']?.toString() ?? 'stub';
              final firstBus = ((busLive!['buses'] as List?)?.isNotEmpty == true) ? (busLive!['buses'] as List).first as Map : null;
              final routeName = firstBus?['routeName']?.toString() ?? '';
              final stopFlag = (firstBus?['stopFlag'] is num) ? (firstBus!['stopFlag'] as num).toInt() : 0;
              final stateBadge = stopFlag == 1 ? '정차' : '주행';
              final badgeColor = mode == 'live' ? _safe : const Color(0xFFFFB020);
              return Row(mainAxisSize: MainAxisSize.min, children: [
                Icon(Icons.directions_bus, size: 11, color: badgeColor), const SizedBox(width: 3),
                Text('BIS ${c}대${routeName.isNotEmpty ? ' · $routeName $stateBadge' : ''}',
                  style: TextStyle(color: badgeColor, fontSize: 10, fontWeight: FontWeight.w700)),
              ]);
            }),
        ],
      ),
    );
  }
}

/// v2 2026-05-15: BIS 실시간 버스 작은 배지 위젯 (BEV 우상단).
/// stopFlag=1 정차 → 안전색, 주행 → 경고색. mode=live 시 글로우 강화.
class _BisBusBadge extends StatelessWidget {
  final Map<String, dynamic> busLive;
  const _BisBusBadge({required this.busLive});
  @override
  Widget build(BuildContext context) {
    final int count = (busLive['count'] is num) ? (busLive['count'] as num).toInt() : 0;
    final String mode = busLive['mode']?.toString() ?? 'stub';
    final List buses = (busLive['buses'] as List?) ?? const [];
    final Map? first = buses.isNotEmpty ? buses.first as Map : null;
    final String routeName = first?['routeName']?.toString() ?? '';
    final int stopFlag = (first?['stopFlag'] is num) ? (first!['stopFlag'] as num).toInt() : 0;
    final double dist = (first?['distance_m'] is num) ? (first!['distance_m'] as num).toDouble() : 0;
    final isLive = mode == 'live';
    final isStopped = stopFlag == 1;
    final main = isStopped ? const Color(0xFFFFB020) : const Color(0xFF00E09A);
    return Container(
      padding: const EdgeInsets.fromLTRB(8, 5, 9, 6),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft, end: Alignment.bottomRight,
          colors: [
            const Color(0xEE0D1520),
            main.withValues(alpha: 0.18),
          ],
        ),
        border: Border.all(color: main.withValues(alpha: isLive ? 0.85 : 0.50), width: 1.0),
        borderRadius: BorderRadius.circular(10),
        boxShadow: [
          BoxShadow(color: main.withValues(alpha: isLive ? 0.40 : 0.20), blurRadius: 10),
        ],
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(Icons.directions_bus, size: 13, color: main),
        const SizedBox(width: 5),
        Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Text(
            'BIS $count대${isLive ? " · LIVE" : ""}',
            style: TextStyle(color: main, fontSize: 10.5, fontWeight: FontWeight.w900, letterSpacing: 0.5),
          ),
          if (routeName.isNotEmpty)
            Text(
              '$routeName · ${dist.toStringAsFixed(0)}m · ${isStopped ? "정차" : "주행"}',
              style: TextStyle(color: main.withValues(alpha: 0.85), fontSize: 8.5,
                               fontFamily: 'monospace', fontWeight: FontWeight.w700),
            ),
        ]),
      ]),
    );
  }
}

/// Tesla-style 3D voxel — 자동 회전 카메라 + perspective 투영.
class _Bev3DVoxelPainter extends CustomPainter {
  final Map<String, dynamic>? bev;
  final double t;
  final double zoom;          // 1.0 = 기본, 0.5~2.5
  final double yawDeg;        // -60 ~ 60 (좌우 회전)
  final double fps;           // 화면 갱신 fps
  _Bev3DVoxelPainter({this.bev, required this.t, this.zoom = 1.0, this.yawDeg = 0, this.fps = 0});

  // 3D 점 → 2D 화면 (Tesla-style 살짝 기울어진 top-down — 3D 깊이감 살림)
  // 캔버스 fit + perspective tilt + 사용자 zoom/yaw 컨트롤
  Offset _project(double x, double y, double z, double cx, double cz, Size size) {
    final w = size.width, h = size.height;
    // yaw 회전 (Y축 기준 좌우 돌리기) — 사용자 드래그 컨트롤
    final yaw = yawDeg * math.pi / 180.0;
    final yawCos = math.cos(yaw), yawSin = math.sin(yaw);
    // 회전 후 좌표 (z 축 중심 회전)
    final rx = (x - cx) * yawCos - z * yawSin;
    final rz = (x - cx) * yawSin + z * yawCos;
    // 카메라 tilt 18° 가정 — 위에서 내려다 보되 약간 forward
    const tiltCos = 0.951;  // cos(18°)
    const tiltSin = 0.309;  // sin(18°)
    // 캔버스 fit — 가로 36m (-18~18), 세로 60m forward · 사용자 zoom 적용
    final scaleX = (w - 24) / 36.0 * zoom;
    final scaleZ = (h - 70) / 60.0 * zoom;
    // ★ X-axis 원근감 제거 — 순수 orthographic (좌로 슬라이딩 효과 방지)
    // 멀리 있는 차량이 ego 쪽으로 다가올 때 옆으로 흐르지 않고 정직하게 forward 이동
    final screenX = w / 2 + rx * scaleX;
    // 화면 Y: 멀리 객체 위로 (tiltCos), 높이 객체 위로 (tiltSin)
    final screenY = h - 32 - rz * scaleZ * tiltCos - y * scaleX * tiltSin * 4.0;
    return Offset(screenX, screenY);
  }

  void _drawVoxel(Canvas canvas, Size size, double x, double z, double height, Color color, double cx, double cz) {
    // voxel 6면체 — 4 개 면 (top, front, right, back) 그림 (밑면 안 보임)
    final p000 = _project(x - 0.5, 0,      z - 0.5, cx, cz, size);
    final p100 = _project(x + 0.5, 0,      z - 0.5, cx, cz, size);
    final p110 = _project(x + 0.5, 0,      z + 0.5, cx, cz, size);
    final p010 = _project(x - 0.5, 0,      z + 0.5, cx, cz, size);
    final p001 = _project(x - 0.5, height, z - 0.5, cx, cz, size);
    final p101 = _project(x + 0.5, height, z - 0.5, cx, cz, size);
    final p111 = _project(x + 0.5, height, z + 0.5, cx, cz, size);
    final p011 = _project(x - 0.5, height, z + 0.5, cx, cz, size);

    // top (밝게)
    final topP = Path()
      ..moveTo(p001.dx, p001.dy)
      ..lineTo(p101.dx, p101.dy)
      ..lineTo(p111.dx, p111.dy)
      ..lineTo(p011.dx, p011.dy)
      ..close();
    canvas.drawPath(topP, Paint()
      ..color = Color.fromRGBO(
        ((color.r * 255).round() * 1.3).clamp(0, 255).round(),
        ((color.g * 255).round() * 1.3).clamp(0, 255).round(),
        ((color.b * 255).round() * 1.3).clamp(0, 255).round(),
        0.95,
      ));

    // front (보통)
    final frontP = Path()
      ..moveTo(p000.dx, p000.dy)
      ..lineTo(p100.dx, p100.dy)
      ..lineTo(p101.dx, p101.dy)
      ..lineTo(p001.dx, p001.dy)
      ..close();
    canvas.drawPath(frontP, Paint()..color = color.withValues(alpha: 0.85));

    // right (어둡게)
    final rightP = Path()
      ..moveTo(p100.dx, p100.dy)
      ..lineTo(p110.dx, p110.dy)
      ..lineTo(p111.dx, p111.dy)
      ..lineTo(p101.dx, p101.dy)
      ..close();
    canvas.drawPath(rightP, Paint()
      ..color = Color.fromRGBO(
        ((color.r * 255).round() * 0.65).round(),
        ((color.g * 255).round() * 0.65).round(),
        ((color.b * 255).round() * 0.65).round(),
        0.85,
      ));

    // outline (시안)
    canvas.drawPath(topP, Paint()
      ..color = const Color.fromRGBO(255, 255, 255, 0.20)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 0.5);
  }

  /// 차량 — 차체 (steel blue) + 캐빈 + outline (cluster bounding box 기반 1개 객체)
  void _drawVehicle(Canvas canvas, Size size, double cxM, double czM,
                    double lengthM, double widthM, double cameraX, double cameraZ) {
    final color = const Color(0xFF3A8FFF);
    final w = widthM, l = lengthM;
    final isLargeVehicle = w > 2.4 || l > 6.0;  // 트럭/버스
    final bodyH = isLargeVehicle ? 2.4 : 1.4;

    // 차체 박스 (4 vertex bottom + 4 vertex top)
    final p000 = _project(cxM - w/2, 0,    czM - l/2, cameraX, cameraZ, size);
    final p100 = _project(cxM + w/2, 0,    czM - l/2, cameraX, cameraZ, size);
    final p110 = _project(cxM + w/2, 0,    czM + l/2, cameraX, cameraZ, size);
    final p010 = _project(cxM - w/2, 0,    czM + l/2, cameraX, cameraZ, size);
    final p001 = _project(cxM - w/2, bodyH, czM - l/2, cameraX, cameraZ, size);
    final p101 = _project(cxM + w/2, bodyH, czM - l/2, cameraX, cameraZ, size);
    final p111 = _project(cxM + w/2, bodyH, czM + l/2, cameraX, cameraZ, size);
    final p011 = _project(cxM - w/2, bodyH, czM + l/2, cameraX, cameraZ, size);

    // 옆면 (어둡게)
    final lightCol = Color.fromRGBO(((color.r * 255).round() * 1.25).clamp(0,255).round(),
                                     ((color.g * 255).round() * 1.25).clamp(0,255).round(),
                                     ((color.b * 255).round() * 1.25).clamp(0,255).round(), 0.92);
    final darkCol = Color.fromRGBO(((color.r * 255).round() * 0.55).round(),
                                    ((color.g * 255).round() * 0.55).round(),
                                    ((color.b * 255).round() * 0.55).round(), 0.85);

    // 후면 (z 큰 쪽 = 화면 위)
    canvas.drawPath(Path()
      ..moveTo(p010.dx, p010.dy)..lineTo(p110.dx, p110.dy)
      ..lineTo(p111.dx, p111.dy)..lineTo(p011.dx, p011.dy)..close(),
      Paint()..color = darkCol);
    // 우측면
    canvas.drawPath(Path()
      ..moveTo(p100.dx, p100.dy)..lineTo(p110.dx, p110.dy)
      ..lineTo(p111.dx, p111.dy)..lineTo(p101.dx, p101.dy)..close(),
      Paint()..color = darkCol);
    // 전면 (z 작은 쪽)
    canvas.drawPath(Path()
      ..moveTo(p000.dx, p000.dy)..lineTo(p100.dx, p100.dy)
      ..lineTo(p101.dx, p101.dy)..lineTo(p001.dx, p001.dy)..close(),
      Paint()..color = Color.fromRGBO((color.r * 255).round(), (color.g * 255).round(), (color.b * 255).round(), 0.92));
    // 윗면
    canvas.drawPath(Path()
      ..moveTo(p001.dx, p001.dy)..lineTo(p101.dx, p101.dy)
      ..lineTo(p111.dx, p111.dy)..lineTo(p011.dx, p011.dy)..close(),
      Paint()..color = lightCol);

    // 캐빈 (작은 박스 위, 큰 트럭 아닌 경우만)
    if (!isLargeVehicle) {
      final cabH = bodyH * 0.55;
      final cw = w * 0.85, cl = l * 0.55;
      final cab000 = _project(cxM - cw/2, bodyH,        czM - cl*0.45 - 0.05, cameraX, cameraZ, size);
      final cab100 = _project(cxM + cw/2, bodyH,        czM - cl*0.45 - 0.05, cameraX, cameraZ, size);
      final cab110 = _project(cxM + cw/2, bodyH,        czM + cl*0.55 - 0.05, cameraX, cameraZ, size);
      final cab010 = _project(cxM - cw/2, bodyH,        czM + cl*0.55 - 0.05, cameraX, cameraZ, size);
      final cab001 = _project(cxM - cw/2, bodyH + cabH, czM - cl*0.45 - 0.05, cameraX, cameraZ, size);
      final cab101 = _project(cxM + cw/2, bodyH + cabH, czM - cl*0.45 - 0.05, cameraX, cameraZ, size);
      final cab111 = _project(cxM + cw/2, bodyH + cabH, czM + cl*0.55 - 0.05, cameraX, cameraZ, size);
      final cab011 = _project(cxM - cw/2, bodyH + cabH, czM + cl*0.55 - 0.05, cameraX, cameraZ, size);
      canvas.drawPath(Path()..moveTo(cab001.dx, cab001.dy)..lineTo(cab101.dx, cab101.dy)..lineTo(cab111.dx, cab111.dy)..lineTo(cab011.dx, cab011.dy)..close(),
        Paint()..color = const Color(0xCC0D1520));
      // 캐빈 옆면 (어둡게)
      canvas.drawPath(Path()..moveTo(cab100.dx, cab100.dy)..lineTo(cab110.dx, cab110.dy)..lineTo(cab111.dx, cab111.dy)..lineTo(cab101.dx, cab101.dy)..close(),
        Paint()..color = const Color(0x99081420));
    }

    // 시그니처 wireframe (시안 발광 outline)
    final wirePaint = Paint()
      ..color = const Color.fromRGBO(170, 230, 255, 0.55)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0;
    final outline = Path()
      ..moveTo(p001.dx, p001.dy)..lineTo(p101.dx, p101.dy)
      ..lineTo(p111.dx, p111.dy)..lineTo(p011.dx, p011.dy)..close();
    canvas.drawPath(outline, wirePaint);
    // 수직 모서리
    for (final pair in [[p000, p001], [p100, p101], [p110, p111], [p010, p011]]) {
      canvas.drawLine(pair[0], pair[1], wirePaint);
    }
  }

  /// 오토바이 — 작은 차체 + 라이더 + 주황 펄스 링
  void _drawMotoBike(Canvas canvas, Size size, double cxM, double czM,
                     double lengthM, double widthM, double cameraX, double cameraZ) {
    final color = const Color(0xFFFF8C00);
    final l = lengthM, w = widthM;

    // 바닥 펄스 링 (사각지대 alert)
    final ringR = math.max(l * 0.5, 0.8);
    final ringCenter = _project(cxM, 0, czM, cameraX, cameraZ, size);
    final ringEdge = _project(cxM + ringR, 0, czM, cameraX, cameraZ, size);
    canvas.drawCircle(ringCenter, (ringEdge.dx - ringCenter.dx).abs(), Paint()
      ..color = color.withValues(alpha: 0.30)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.0);

    // 차체 (좁은 박스 0.5×0.7×lengthM)
    final h = 0.7;
    final p000 = _project(cxM - w*0.3, 0, czM - l/2, cameraX, cameraZ, size);
    final p100 = _project(cxM + w*0.3, 0, czM - l/2, cameraX, cameraZ, size);
    final p110 = _project(cxM + w*0.3, 0, czM + l/2, cameraX, cameraZ, size);
    final p010 = _project(cxM - w*0.3, 0, czM + l/2, cameraX, cameraZ, size);
    final p001 = _project(cxM - w*0.3, h, czM - l/2, cameraX, cameraZ, size);
    final p101 = _project(cxM + w*0.3, h, czM - l/2, cameraX, cameraZ, size);
    final p111 = _project(cxM + w*0.3, h, czM + l/2, cameraX, cameraZ, size);
    final p011 = _project(cxM - w*0.3, h, czM + l/2, cameraX, cameraZ, size);
    canvas.drawPath(Path()..moveTo(p001.dx, p001.dy)..lineTo(p101.dx, p101.dy)..lineTo(p111.dx, p111.dy)..lineTo(p011.dx, p011.dy)..close(),
      Paint()..color = color.withValues(alpha: 0.92));
    canvas.drawPath(Path()..moveTo(p000.dx, p000.dy)..lineTo(p100.dx, p100.dy)..lineTo(p101.dx, p101.dy)..lineTo(p001.dx, p001.dy)..close(),
      Paint()..color = color.withValues(alpha: 0.75));
    canvas.drawPath(Path()..moveTo(p100.dx, p100.dy)..lineTo(p110.dx, p110.dy)..lineTo(p111.dx, p111.dy)..lineTo(p101.dx, p101.dy)..close(),
      Paint()..color = Color.fromRGBO(120, 60, 0, 0.85));

    // 라이더 (타원/구체) 위
    final riderTop = _project(cxM, h + 0.85, czM, cameraX, cameraZ, size);
    canvas.drawCircle(riderTop, 4.0, Paint()..color = const Color(0xFFFFD54A));
    // 헬멧 (빨강)
    final helmTop = _project(cxM, h + 1.4, czM, cameraX, cameraZ, size);
    canvas.drawCircle(helmTop, 3.5, Paint()
      ..color = const Color(0xFFFF5A5A)
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 2));
    canvas.drawCircle(helmTop, 2.8, Paint()..color = const Color(0xFFFF5A5A));
  }

  /// 가려진/사각지대 영역 — 바닥에 보라 안개
  void _drawOcclusion(Canvas canvas, Size size, double x1, double z1, double x2, double z2,
                      double cameraX, double cameraZ) {
    final p1 = _project(x1, 0, z1, cameraX, cameraZ, size);
    final p2 = _project(x2, 0, z1, cameraX, cameraZ, size);
    final p3 = _project(x2, 0, z2, cameraX, cameraZ, size);
    final p4 = _project(x1, 0, z2, cameraX, cameraZ, size);
    canvas.drawPath(Path()..moveTo(p1.dx, p1.dy)..lineTo(p2.dx, p2.dy)..lineTo(p3.dx, p3.dy)..lineTo(p4.dx, p4.dy)..close(),
      Paint()..color = const Color.fromRGBO(124, 58, 237, 0.30));
    // 윤곽선 (보라)
    canvas.drawPath(Path()..moveTo(p1.dx, p1.dy)..lineTo(p2.dx, p2.dy)..lineTo(p3.dx, p3.dy)..lineTo(p4.dx, p4.dy)..close(),
      Paint()
        ..color = const Color(0xFFA995FF)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.2);
  }

  /// EGO 차량을 임의 위치/회전각으로 그리기 (우회전 애니메이션용)
  /// brakeOn: 브레이크 등 빨갛게 (정지 표시)
  void _drawEgoAtAngle(Canvas canvas, Size size, double xM, double zM, double yawDeg,
                        double cameraX, double cameraZ, {bool brakeOn = false}) {
    const w = 1.8;  // 차폭
    const l = 4.0;  // 차장
    const h = 1.4;  // 차높이
    final rad = yawDeg * math.pi / 180.0;
    final cosY = math.cos(rad), sinY = math.sin(rad);
    // 차체 4 모서리 (ego 진행방향 기준 회전)
    Offset corner(double dx, double dz, double y) {
      // local → world (rotate around y-axis)
      final wx = xM + dx * cosY + dz * sinY;
      final wz = zM + dx * -sinY + dz * cosY;
      return _project(wx, y, wz, cameraX, cameraZ, size);
    }
    final p000 = corner(-w/2, -l/2, 0);
    final p100 = corner( w/2, -l/2, 0);
    final p110 = corner( w/2,  l/2, 0);
    final p010 = corner(-w/2,  l/2, 0);
    final p001 = corner(-w/2, -l/2, h);
    final p101 = corner( w/2, -l/2, h);
    final p111 = corner( w/2,  l/2, h);
    final p011 = corner(-w/2,  l/2, h);
    const color = Color(0xFF00C8FF);
    // 차체 (윗면 가장 밝게)
    canvas.drawPath(Path()..moveTo(p001.dx, p001.dy)..lineTo(p101.dx, p101.dy)..lineTo(p111.dx, p111.dy)..lineTo(p011.dx, p011.dy)..close(),
      Paint()..color = color);
    // 옆면 (전방)
    canvas.drawPath(Path()..moveTo(p010.dx, p010.dy)..lineTo(p110.dx, p110.dy)..lineTo(p111.dx, p111.dy)..lineTo(p011.dx, p011.dy)..close(),
      Paint()..color = const Color(0xFF0080A0));
    // 옆면 (우)
    canvas.drawPath(Path()..moveTo(p100.dx, p100.dy)..lineTo(p110.dx, p110.dy)..lineTo(p111.dx, p111.dy)..lineTo(p101.dx, p101.dy)..close(),
      Paint()..color = const Color(0xFF005570));
    // 옆면 (후방)
    canvas.drawPath(Path()..moveTo(p000.dx, p000.dy)..lineTo(p100.dx, p100.dy)..lineTo(p101.dx, p101.dy)..lineTo(p001.dx, p001.dy)..close(),
      Paint()..color = const Color(0xFF003c50));
    // 윤곽선 (시안 발광)
    final outline = Paint()
      ..color = const Color(0xFF80EEFF)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5;
    canvas.drawPath(Path()..moveTo(p001.dx, p001.dy)..lineTo(p101.dx, p101.dy)..lineTo(p111.dx, p111.dy)..lineTo(p011.dx, p011.dy)..close(), outline);
    // 진행방향 forward 화살표 (차 앞 헤드라이트)
    final headlight = corner(0, l/2 + 0.3, h * 0.6);
    canvas.drawCircle(headlight, 3.5, Paint()..color = const Color(0xFFFFF7C0));
    // 정지 시 후미등 (빨강) 표시
    if (brakeOn) {
      final brakeL = corner(-w*0.4, -l/2 - 0.1, h * 0.6);
      final brakeR = corner( w*0.4, -l/2 - 0.1, h * 0.6);
      final pulse = (math.sin(this.t * 4) + 1) * 0.5;
      final brakePaint = Paint()
        ..color = const Color(0xFFFF3030).withValues(alpha: 0.6 + pulse * 0.4)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 3);
      canvas.drawCircle(brakeL, 5, brakePaint);
      canvas.drawCircle(brakeR, 5, brakePaint);
      canvas.drawCircle(brakeL, 3, Paint()..color = const Color(0xFFFF5050));
      canvas.drawCircle(brakeR, 3, Paint()..color = const Color(0xFFFF5050));
    }
  }

  /// 우회전 시나리오 — 핵심 로직만:
  ///   ego 우회전 시 우측 사각지대에 보행자 → 검출되면 정지 권고
  void _drawRightTurnAids(Canvas canvas, Size size, double cameraX, double cameraZ) {
    // ego 우측 A필러 사각지대 영역 (cone 형 강조) — class_grid cls=3 가 이미 그려짐
    // 추가: 사각지대 영역에 "⚠️ A필러 사각" 라벨

    // 1) 사각지대 라벨 — 우측 A필러 영역 가운데
    final blindCenter = _project(8.5, 0, 18, cameraX, cameraZ, size);
    canvas.drawCircle(blindCenter, 22, Paint()
      ..color = const Color(0xFF7C3AED).withValues(alpha: 0.20)
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 8));
    final tpBlind = TextPainter(
      text: const TextSpan(text: '⚠️ A필러 사각',
        style: TextStyle(color: Color(0xFFA995FF), fontSize: 11, fontWeight: FontWeight.w900,
                         shadows: [Shadow(color: Colors.black, blurRadius: 4)])),
      textDirection: TextDirection.ltr,
    )..layout();
    tpBlind.paint(canvas, Offset(blindCenter.dx - tpBlind.width/2, blindCenter.dy - 6));

    // 2) ⛔ 큰 정지 안내 라벨 — 화면 상단 가운데 (보행자 검출됨 가정)
    final stopBg = Rect.fromLTWH((size.width - 240) / 2, size.height * 0.20, 240, 56);
    canvas.drawRRect(
      RRect.fromRectAndRadius(stopBg, const Radius.circular(12)),
      Paint()
        ..color = const Color(0xFFFF3030).withValues(alpha: 0.92)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 4),
    );
    canvas.drawRRect(
      RRect.fromRectAndRadius(stopBg, const Radius.circular(12)),
      Paint()..color = const Color(0xFFFF3030),
    );
    // 펄스 효과
    final pulseT = (t * 1.5) % 1.0;
    canvas.drawRRect(
      RRect.fromRectAndRadius(stopBg.inflate(4 + pulseT * 6), const Radius.circular(14)),
      Paint()
        ..color = const Color(0xFFFF5A5A).withValues(alpha: (1 - pulseT) * 0.55)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.5,
    );
    final tpStop = TextPainter(
      text: const TextSpan(children: [
        TextSpan(text: '⛔ 정지\n',
          style: TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w900, height: 1.1)),
        TextSpan(text: '우측 사각지대 보행자 검출',
          style: TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w700)),
      ]),
      textDirection: TextDirection.ltr,
      textAlign: TextAlign.center,
    )..layout(maxWidth: 240);
    tpStop.paint(canvas, Offset(stopBg.left + (stopBg.width - tpStop.width) / 2, stopBg.top + 6));
  }

  /// 보행자 — 시안 원기둥 (몸통) + 작은 구 (머리) + 바닥 펄스 링
  void _drawPedestrianMarker(Canvas canvas, Size size, double x, double z, double cx, double cz) {
    const color = Color(0xFF00D8FF);
    final base = _project(x, 0, z, cx, cz, size);
    final mid = _project(x, 0.9, z, cx, cz, size);
    final top = _project(x, 1.5, z, cx, cz, size);

    // 바닥 펄스 링
    canvas.drawCircle(base, 4.5, Paint()
      ..color = color.withValues(alpha: 0.30)
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 3));
    canvas.drawCircle(base, 3.0, Paint()
      ..color = color.withValues(alpha: 0.55)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0);
    // 몸통 (선)
    canvas.drawLine(base, mid, Paint()
      ..color = color
      ..strokeWidth = 3.0
      ..strokeCap = StrokeCap.round);
    // 머리 (구)
    canvas.drawCircle(top, 2.6, Paint()
      ..color = color
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 2));
    canvas.drawCircle(top, 1.8, Paint()..color = color);
  }

  /// 신호등 — 회색 폴 + 적색 라이트 (높이 4.2m)
  void _drawSignalMarker(Canvas canvas, Size size, double x, double z, double cx, double cz) {
    final base = _project(x, 0, z, cx, cz, size);
    final lightBase = _project(x, 3.5, z, cx, cz, size);
    final lightTop = _project(x, 4.2, z, cx, cz, size);
    // 폴 (회색)
    canvas.drawLine(base, lightBase, Paint()
      ..color = const Color(0xFF4A5566)
      ..strokeWidth = 2.0);
    // 라이트 박스 (검정)
    final boxRect = Rect.fromPoints(lightBase, lightTop).inflate(2.5);
    canvas.drawRect(boxRect, Paint()..color = const Color(0xFF1A2030));
    // 적색 발광
    final lightCenter = Offset((lightBase.dx + lightTop.dx) / 2, (lightBase.dy + lightTop.dy) / 2);
    canvas.drawCircle(lightCenter, 3.5, Paint()
      ..color = const Color(0xFFFF3030)
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 3));
    canvas.drawCircle(lightCenter, 2.2, Paint()..color = const Color(0xFFFF5050));
  }

  @override
  void paint(Canvas canvas, Size size) {
    // 배경
    canvas.drawRect(Offset.zero & size, Paint()..color = const Color(0xFF0A1018));

    // 카메라 고정 — Tesla 모니터식 위에서 약간 뒤로 (ego 안정적 시점)
    final cx = math.sin(t * 0.4) * 0.8;
    const cz = -3.0;

    // ★ DEMO 모드 판단 — scenario_id 가 있으면 가짜 도로 인프라 표시 (시연용)
    //   LIVE 모드 (scenario_id 없음) → 도로 X · ML Kit 객체 검출 결과만 형상 표시
    final flatPre = bev?['grid_flat'];
    final shapePre = bev?['grid_shape_flat'];
    final classPre = bev?['class_grid_flat'];
    final hasShapePre = flatPre is List && shapePre is List && shapePre.length == 2;
    final hasClassPre = hasShapePre && classPre is List && classPre.length == (shapePre[0] as num) * (shapePre[1] as num);
    final scnIdPre = bev?['scenario_id'] as String?;
    final isDemoScene = scnIdPre != null && scnIdPre.isNotEmpty;

    if (!isDemoScene) {
      // ─────── LIVE 모드: 도로 인프라 X · 단순 reference grid 만 ───────
      // 사용자가 실제 환경에서 카메라로 보는 raw voxel 활성화
      final w = size.width, h = size.height;
      // 옅은 reference grid (10m 단위)
      final refPaint = Paint()
        ..color = const Color.fromRGBO(0, 60, 120, 0.20)
        ..strokeWidth = 0.6;
      for (int dz = 0; dz <= 50; dz += 10) {
        canvas.drawLine(_project(-15, 0, dz.toDouble(), cx, cz, size),
                        _project(15,  0, dz.toDouble(), cx, cz, size), refPaint);
      }
      for (int dx = -15; dx <= 15; dx += 5) {
        canvas.drawLine(_project(dx.toDouble(), 0, 0,  cx, cz, size),
                        _project(dx.toDouble(), 0, 50, cx, cz, size), refPaint);
      }
      // 거리 라벨 (10/20/30m)
      for (final d in [10, 20, 30, 40]) {
        final p = _project(-15, 0, d.toDouble(), cx, cz, size);
        final tp = TextPainter(
          text: TextSpan(text: '${d}m',
            style: TextStyle(color: _muted.withValues(alpha: 0.5), fontSize: 8, fontWeight: FontWeight.w700)),
          textDirection: TextDirection.ltr,
        )..layout();
        tp.paint(canvas, Offset(p.dx + 4, p.dy - 6));
      }
      // ego 차량만 그리고 끝 — 도로 X
      _drawVoxel(canvas, size, 0, 0, 1.4, const Color(0xFF00C8FF), cx, cz);
    } else {
      // ─────── DEMO 모드: 도심 4지 교차로 (시나리오 시각화) ───────
    // ego 진행 +z. 자차 도로 폭 12m (-6~+6), 정지선 z=24m, 교차로 본체 z=24~32m
    // 가로 도로 폭 8m (z=24~32), x= -25~25
    final asphaltPaint = Paint()..color = const Color(0xFF1F242E);  // 밝은 아스팔트
    final swPaint = Paint()..color = const Color(0xFF3A4252);        // 밝은 인도

    // 1) ego 도로 (-10 ~ 24)
    Path rectPath(double x1, double z1, double x2, double z2) {
      return Path()
        ..moveTo(_project(x1, 0, z1, cx, cz, size).dx, _project(x1, 0, z1, cx, cz, size).dy)
        ..lineTo(_project(x2, 0, z1, cx, cz, size).dx, _project(x2, 0, z1, cx, cz, size).dy)
        ..lineTo(_project(x2, 0, z2, cx, cz, size).dx, _project(x2, 0, z2, cx, cz, size).dy)
        ..lineTo(_project(x1, 0, z2, cx, cz, size).dx, _project(x1, 0, z2, cx, cz, size).dy)
        ..close();
    }
    canvas.drawPath(rectPath(-6, -10, 6, 24), asphaltPaint);
    // 2) 가로 도로 (x=-25~25, z=24~32)
    canvas.drawPath(rectPath(-25, 24, 25, 32), asphaltPaint);
    // 3) ego 도로 너머 (32 ~ 46)
    canvas.drawPath(rectPath(-6, 32, 6, 46), asphaltPaint);

    // 4) 4 모서리 인도 (교차로 코너)
    canvas.drawPath(rectPath(-18, -10, -6, 24), swPaint);  // SW (좌하)
    canvas.drawPath(rectPath(6, -10, 18, 24), swPaint);    // SE (우하)
    canvas.drawPath(rectPath(-18, 32, -6, 46), swPaint);   // NW (좌상)
    canvas.drawPath(rectPath(6, 32, 18, 46), swPaint);     // NE (우상)
    // 가로 도로 양 끝 인도
    canvas.drawPath(rectPath(-25, 22, -18, 24), swPaint);
    canvas.drawPath(rectPath(18, 22, 25, 24), swPaint);
    canvas.drawPath(rectPath(-25, 32, -18, 34), swPaint);
    canvas.drawPath(rectPath(18, 32, 25, 34), swPaint);

    // 5) 중앙 노란 점선 (ego 도로 z=-10~24)
    final centerPaint = Paint()
      ..color = const Color(0xFFFACC15)
      ..strokeWidth = 2.5
      ..strokeCap = StrokeCap.round;
    for (double dz = -10; dz < 24; dz += 1.0) {
      if ((dz * 10).floor() % 12 < 8) {
        final p1 = _project(0, 0, dz, cx, cz, size);
        final p2 = _project(0, 0, dz + 0.45, cx, cz, size);
        canvas.drawLine(p1, p2, centerPaint);
      }
    }
    // 교차로 너머
    for (double dz = 32; dz < 46; dz += 1.0) {
      if ((dz * 10).floor() % 12 < 8) {
        final p1 = _project(0, 0, dz, cx, cz, size);
        final p2 = _project(0, 0, dz + 0.45, cx, cz, size);
        canvas.drawLine(p1, p2, centerPaint);
      }
    }
    // 가로 도로 중앙 노란선 (x=-24~24, z=28)
    for (double dx = -24; dx < 24; dx += 1.0) {
      if ((dx * 10).floor() % 12 < 8) {
        final p1 = _project(dx, 0, 28, cx, cz, size);
        final p2 = _project(dx + 0.45, 0, 28, cx, cz, size);
        canvas.drawLine(p1, p2, centerPaint);
      }
    }

    // 6) 차선 흰 점선 — ego 도로 ±3 (양방향 2차선)
    final lanePaint = Paint()
      ..color = const Color(0xFFEEF0F4)
      ..strokeWidth = 2.0
      ..strokeCap = StrokeCap.round;
    for (final lx in [-3.0, 3.0]) {
      for (double dz = -10; dz < 24; dz += 3.5) {
        canvas.drawLine(
          _project(lx, 0, dz, cx, cz, size),
          _project(lx, 0, dz + 1.8, cx, cz, size),
          lanePaint,
        );
      }
      for (double dz = 32; dz < 46; dz += 3.5) {
        canvas.drawLine(
          _project(lx, 0, dz, cx, cz, size),
          _project(lx, 0, dz + 1.8, cx, cz, size),
          lanePaint,
        );
      }
    }
    // 가로 도로 차선 (z = 26, 30)
    for (final lz in [26.0, 30.0]) {
      for (double dx = -24; dx < 24; dx += 3.5) {
        canvas.drawLine(
          _project(dx, 0, lz, cx, cz, size),
          _project(dx + 1.8, 0, lz, cx, cz, size),
          lanePaint,
        );
      }
    }

    // 7) 정지선 4개 (ego 진입, 반대편, 좌가로, 우가로)
    final stopPaint = Paint()
      ..color = const Color(0xFFEEF0F4)
      ..strokeWidth = 4.0
      ..strokeCap = StrokeCap.square;
    canvas.drawLine(_project(-6, 0, 23.5, cx, cz, size), _project(6, 0, 23.5, cx, cz, size), stopPaint);
    canvas.drawLine(_project(-6, 0, 32.5, cx, cz, size), _project(6, 0, 32.5, cx, cz, size), stopPaint);
    canvas.drawLine(_project(-6, 0, 24, cx, cz, size), _project(-6, 0, 32, cx, cz, size), stopPaint);
    canvas.drawLine(_project(6, 0, 24, cx, cz, size), _project(6, 0, 32, cx, cz, size), stopPaint);

    // 8) 횡단보도 zebra — 가로 도로 양쪽 (우회전 보행자 시나리오 핵심)
    //   ★ ego 가 우회전 후 진입할 가로 도로의 횡단보도 — 보행자가 여기를 건넘
    final zebraPaint = Paint()..color = const Color(0xFFEEF0F4);
    Path zebra(double x1, double z1, double x2, double z2) =>
        rectPath(x1, z1, x2, z2);
    // 좌측 가로 도로 횡단 (x=-7m, z 24.5~32)
    for (int i = 0; i < 5; i++) {
      final lz = 24.8 + i * 1.6;
      canvas.drawPath(zebra(-7.7, lz - 0.3, -6.3, lz + 0.3), zebraPaint);
    }
    // 우측 가로 도로 횡단 (x=+7m) — ★ 우회전 시 보행자 마주치는 핵심 횡단보도
    for (int i = 0; i < 5; i++) {
      final lz = 24.8 + i * 1.6;
      canvas.drawPath(zebra(6.3, lz - 0.3, 7.7, lz + 0.3), zebraPaint);
    }

    // 8.5) ★ 신호등 폴 — 교차로 4 코너 (횡단보도와 일치)
    final polePaint = Paint()
      ..color = const Color(0xFF4A5566)
      ..strokeWidth = 2.5;
    final lightBoxPaint = Paint()..color = const Color(0xFF1A2030);
    final redLightPaint = Paint()..color = const Color(0xFFFF3030);
    for (final corner in [
      [-7.0, 23.0], [7.0, 23.0],   // 남쪽 코너
      [-7.0, 33.0], [7.0, 33.0],   // 북쪽 코너
    ]) {
      final poleX = corner[0], poleZ = corner[1];
      // 폴 (수직선) — 0~5m 높이
      canvas.drawLine(
        _project(poleX, 0, poleZ, cx, cz, size),
        _project(poleX, 5, poleZ, cx, cz, size),
        polePaint,
      );
      // 라이트 박스 + 적색 라이트
      final lightBoxCenter = _project(poleX, 5.2, poleZ, cx, cz, size);
      canvas.drawRect(Rect.fromCenter(center: lightBoxCenter, width: 8, height: 14), lightBoxPaint);
      canvas.drawCircle(lightBoxCenter.translate(0, -2), 3.5, Paint()
        ..color = const Color(0xFFFF3030)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 3));
      canvas.drawCircle(lightBoxCenter.translate(0, -2), 2.2, redLightPaint);
    }

    // 9) 진행 화살표 (ego 차로 중앙 z=8, 18)
    final arrowPaint = Paint()..color = const Color.fromRGBO(238, 240, 244, 0.55);
    for (final az in [8.0, 18.0]) {
      final stem1 = _project(-0.25, 0, az, cx, cz, size);
      final stem2 = _project(0.25,  0, az + 1.6, cx, cz, size);
      canvas.drawRect(Rect.fromPoints(stem1, stem2), arrowPaint);
      final tip = _project(0, 0, az + 2.4, cx, cz, size);
      final left = _project(-0.6, 0, az + 1.6, cx, cz, size);
      final right = _project(0.6, 0, az + 1.6, cx, cz, size);
      final headP = Path()..moveTo(tip.dx, tip.dy)..lineTo(left.dx, left.dy)..lineTo(right.dx, right.dy)..close();
      canvas.drawPath(headP, arrowPaint);
    }

    // 10) 자차 차로 시안 발광 strip
    final egoLanePaint = Paint()
      ..color = const Color.fromRGBO(0, 200, 255, 0.55)
      ..strokeWidth = 1.5;
    for (final lx in [-1.5, 1.5]) {
      canvas.drawLine(
        _project(lx, 0, 0, cx, cz, size),
        _project(lx, 0, 23, cx, cz, size),
        egoLanePaint,
      );
    }

      // ── EGO 차량 (DEMO 시나리오) — 모든 시나리오 wall-clock sync 통일
      // wall-clock 10s cycle 로 backend 와 동일 기준
      final scnIdForEgo = bev?['scenario_id'] as String?;
      final wallSecAll = DateTime.now().millisecondsSinceEpoch / 1000.0;
      final cycleAll = (wallSecAll % 10.0) / 10.0;
      const laneX = 1.5;   // Korean RHT 우측 차로 중앙

      if (scnIdForEgo == 'right_turn_pedestrian') {
        // 10초 cycle: 접근 → 정지(보행자 대기) → 회전 → 동쪽 진행 → 화면 밖
        double egoX, egoZ, egoYawDeg;
        bool isStopped = false;
        bool egoVisible = true;
        if (cycleAll < 0.16) {
          final p = cycleAll / 0.16;
          egoX = laneX; egoZ = p * 22; egoYawDeg = 0;
        } else if (cycleAll < 0.44) {
          egoX = laneX; egoZ = 22; egoYawDeg = 0; isStopped = true;
        } else if (cycleAll < 0.68) {
          final p = (cycleAll - 0.44) / 0.24;
          egoX = laneX + (18 - laneX) * p * p;
          egoZ = 22 + 10 * p;
          egoYawDeg = 90 * p;
        } else if (cycleAll < 0.88) {
          final p = (cycleAll - 0.68) / 0.20;
          egoX = 18 + p * 32; egoZ = 32; egoYawDeg = 90;
          if (p > 0.7) egoVisible = false;
        } else {
          egoVisible = false; egoX = laneX; egoZ = 0; egoYawDeg = 0;
        }
        if (egoVisible) {
          _drawEgoAtAngle(canvas, size, egoX, egoZ, egoYawDeg, cx, cz, brakeOn: isStopped);
        }
      } else if (scnIdForEgo == 'school_zone') {
        // 스쿨존: 진입 → 점진 감속 → 정지(어린이 출현) → 천천히 통과
        // backend child_visible 0.30~0.55 동안 정지
        double egoZ, egoYawDeg = 0;
        bool isStopped = false;
        if (cycleAll < 0.20) {
          final p = cycleAll / 0.20;
          egoZ = p * 14;   // 0 → 14m 진입 (35km/h 가정)
        } else if (cycleAll < 0.30) {
          final p = (cycleAll - 0.20) / 0.10;
          egoZ = 14 + p * 4;   // 14 → 18m (감속 — 스쿨존 진입)
        } else if (cycleAll < 0.55) {
          // 어린이 출현 → 정지
          egoZ = 18; isStopped = true;
        } else if (cycleAll < 0.85) {
          final p = (cycleAll - 0.55) / 0.30;
          egoZ = 18 + p * 22;   // 18 → 40m 천천히 통과 (20km/h)
        } else {
          egoZ = 40; isStopped = false;
        }
        _drawEgoAtAngle(canvas, size, laneX, egoZ, egoYawDeg, cx, cz, brakeOn: isStopped);
      } else if (scnIdForEgo == 'bicycle_lane') {
        // 자전거 도로: 정지선 접근 → 우회전 신호 대기(자전거 후방 접근 감지) → 보류
        // backend bike_visible 0.20~0.80 동안 자전거 가속
        double egoX, egoZ, egoYawDeg;
        bool isStopped = false;
        if (cycleAll < 0.20) {
          final p = cycleAll / 0.20;
          egoX = laneX; egoZ = p * 22; egoYawDeg = 0;
        } else if (cycleAll < 0.80) {
          // ★ 자전거 후방 접근 → 우회전 보류 (정지)
          egoX = laneX; egoZ = 22; egoYawDeg = 0; isStopped = true;
        } else if (cycleAll < 0.95) {
          final p = (cycleAll - 0.80) / 0.15;
          egoX = laneX + (12 - laneX) * p * p;
          egoZ = 22 + 8 * p;
          egoYawDeg = 60 * p;
        } else {
          // sluggish exit
          egoX = 12; egoZ = 30; egoYawDeg = 60;
        }
        _drawEgoAtAngle(canvas, size, egoX, egoZ, egoYawDeg, cx, cz, brakeOn: isStopped);
      } else if (scnIdForEgo == 'night_pedestrian') {
        // 야간: 고속(42km/h) 진행 → 보행자 감지(0.15~0.65) → 급제동 → 재출발
        double egoZ, egoYawDeg = 0;
        bool isStopped = false;
        if (cycleAll < 0.15) {
          final p = cycleAll / 0.15;
          egoZ = p * 12;   // 0 → 12m 고속 진입
        } else if (cycleAll < 0.30) {
          final p = (cycleAll - 0.15) / 0.15;
          egoZ = 12 + p * 4;   // 12 → 16m 급감속
        } else if (cycleAll < 0.65) {
          // 보행자 횡단 대기
          egoZ = 16; isStopped = true;
        } else if (cycleAll < 0.95) {
          final p = (cycleAll - 0.65) / 0.30;
          egoZ = 16 + p * 24;   // 16 → 40m 재가속
        } else {
          egoZ = 40;
        }
        _drawEgoAtAngle(canvas, size, laneX, egoZ, egoYawDeg, cx, cz, brakeOn: isStopped);
      } else {
        // 기타 시나리오 (truck/moto/signal/rainy): ego 정지선 직전 정지 (감속·경계 시연)
        _drawEgoAtAngle(canvas, size, laneX, 8, 0, cx, cz, brakeOn: true);
      }
    }  // end DEMO 도로 인프라 분기

    // ── voxel 렌더링: LIVE (class 없음 → 점유 dot) / DEMO (class 있음 → 객체 형상)
    final flat = flatPre;
    final shape = shapePre;
    final classFlat = classPre;
    final hasShape = hasShapePre;
    // 객체 형상 렌더링 조건: class_grid 가 존재하면 (DEMO든 LIVE+MLKit이든)
    final hasClass = hasClassPre;

    if (hasShape && !hasClass) {
      // ── LIVE 모드 (Tesla-style): voxel dots + 클러스터 → 객체 silhouette ──
      final rows = (shape[0] as num).toInt();
      final cols = (shape[1] as num).toInt();
      final cellM = 40.0 / cols;
      final motionFlat = bev?['motion_flat'];
      final hasMotion = motionFlat is List && motionFlat.length == rows * cols;

      // ★ 글로벌 모션 ratio — 카메라 흔들림 감지
      // 너무 많은 셀이 동시에 움직이면 = 카메라 shake → silhouette 억제
      double cameraShakeRatio = 0.0;
      if (hasMotion) {
        var movingCells = 0, totalActive = 0;
        for (int i = 0; i < rows * cols; i++) {
          final m = ((motionFlat[i] ?? 0) as num).toDouble();
          if (m > 0.05) movingCells++;
          totalActive++;
        }
        cameraShakeRatio = movingCells / totalActive;
      }
      final isCameraShake = cameraShakeRatio > 0.45;  // 45% 이상 cell 움직임 = shake

      // 1) 두 가지 mask:
      //   - motionMask: motion ≥ 0.15 → 움직이는 객체 (고신뢰)
      //   - staticMask: edge 강 + motion 낮음 → 정지 객체 (저신뢰)
      final motionMask = List<bool>.filled(rows * cols, false);
      final staticMask = List<bool>.filled(rows * cols, false);
      if (!isCameraShake) {
        for (int r = 0; r < rows; r++) {
          for (int c = 0; c < cols; c++) {
            final p = ((flat[r * cols + c] ?? 0) as num).toDouble();
            if (p < 0.50) continue;
            final m = hasMotion ? ((motionFlat[r * cols + c] ?? 0) as num).toDouble() : 0.0;
            if (m >= 0.15) {
              motionMask[r * cols + c] = true;  // 움직임 객체 (사람/차량)
            } else if (p >= 0.65 && m < 0.05) {
              staticMask[r * cols + c] = true;  // 정지 객체 (가만히 있는 사람/차)
            }
          }
        }
      }
      // alias for downstream code
      final mask = motionMask;

      // 2) 8-connected 컴포넌트 클러스터링 (BFS)
      final visited = List<bool>.filled(rows * cols, false);
      const dirs8 = [
        [-1, -1], [-1, 0], [-1, 1],
        [0, -1],           [0, 1],
        [1, -1],  [1, 0],  [1, 1],
      ];
      final blobs = <Map<String, num>>[];  // {minR, maxR, minC, maxC, count, sumP}
      for (int r = 0; r < rows; r++) {
        for (int c = 0; c < cols; c++) {
          final idx = r * cols + c;
          if (visited[idx] || !mask[idx]) { visited[idx] = true; continue; }
          final queue = <List<int>>[[r, c]];
          visited[idx] = true;
          int minR = r, maxR = r, minC = c, maxC = c, count = 0;
          double sumP = 0;
          while (queue.isNotEmpty) {
            final p = queue.removeLast();
            final cr = p[0], cc = p[1];
            count++;
            sumP += ((flat[cr * cols + cc] ?? 0) as num).toDouble();
            if (cr < minR) minR = cr; if (cr > maxR) maxR = cr;
            if (cc < minC) minC = cc; if (cc > maxC) maxC = cc;
            for (final d in dirs8) {
              final nr = cr + d[0], nc = cc + d[1];
              if (nr < 0 || nr >= rows || nc < 0 || nc >= cols) continue;
              final ni = nr * cols + nc;
              if (visited[ni] || !mask[ni]) continue;
              visited[ni] = true;
              queue.add([nr, nc]);
            }
          }
          // 최소 4 cells 필요 (작은 노이즈 cluster 차단)
          if (count >= 4) {
            blobs.add({
              'minR': minR, 'maxR': maxR, 'minC': minC, 'maxC': maxC,
              'count': count, 'avgP': sumP / count,
            });
          }
        }
      }

      // 3) 클러스터 → silhouette: aspect ratio 로 사람/차량/물체 분류
      blobs.sort((a, b) => ((b['avgP'] as num) * (b['count'] as num))
                              .compareTo((a['avgP'] as num) * (a['count'] as num)));
      final topBlobs = blobs.take(8).toList();  // 상위 8개만 silhouette

      var personHint = 0, vehicleHint = 0;
      for (final b in topBlobs) {
        final minR = (b['minR'] as num).toDouble();
        final maxR = (b['maxR'] as num).toDouble();
        final minC = (b['minC'] as num).toDouble();
        final maxC = (b['maxC'] as num).toDouble();
        final avgP = (b['avgP'] as num).toDouble();

        final wM = (maxC - minC + 1) * cellM;
        final lM = (maxR - minR + 1) * cellM;
        final cxM = (((minC + maxC) / 2 + 0.5) - cols / 2) * cellM;
        final czM = ((minR + maxR) / 2 + 0.5) * cellM;
        final aspect = lM / (wM + 0.001);  // length(forward) / width(lateral)

        // 분류 (휴리스틱):
        //  - aspect > 1.4 (forward 으로 길쭉, 차로 방향 정렬) → 차량 후보
        //  - 작고 일정한 (3~7 cells, 1×2~2×2) → 사람 후보
        //  - 큰 wide blob → 차량 (옆에서 본 차)
        //  - 그 외 → 일반 물체
        final cellCount = (b['count'] as num).toInt();
        final isPerson = cellCount <= 6 && wM <= 1.5 && lM <= 2.0;
        final isVehicle = !isPerson && (aspect > 1.3 || wM > 2.0);

        if (isPerson) {
          personHint++;
          // 사람 silhouette — 시안 작은 직사각형 + 머리 원
          final base = _project(cxM, 0, czM, cx, cz, size);
          final top = _project(cxM, 1.7, czM, cx, cz, size);
          // 몸통
          canvas.drawLine(base, top, Paint()
            ..color = const Color(0xFF00D8FF)
            ..strokeWidth = 5.0
            ..strokeCap = StrokeCap.round);
          // 머리
          canvas.drawCircle(top, 4, Paint()..color = const Color(0xFF00D8FF));
          // 바닥 펄스 링
          canvas.drawCircle(base, 8, Paint()
            ..color = const Color(0xFF00D8FF).withValues(alpha: 0.35)
            ..style = PaintingStyle.stroke
            ..strokeWidth = 2);
        } else if (isVehicle) {
          vehicleHint++;
          _drawVehicle(canvas, size, cxM, czM, lM.clamp(2.5, 8.0), wM.clamp(1.6, 3.0), cx, cz);
        } else {
          // 일반 물체 — 노란 outline 박스
          final p1 = _project(cxM - wM/2, 0, czM - lM/2, cx, cz, size);
          final p2 = _project(cxM + wM/2, 0, czM - lM/2, cx, cz, size);
          final p3 = _project(cxM + wM/2, 0, czM + lM/2, cx, cz, size);
          final p4 = _project(cxM - wM/2, 0, czM + lM/2, cx, cz, size);
          canvas.drawPath(Path()..moveTo(p1.dx, p1.dy)..lineTo(p2.dx, p2.dy)
                                  ..lineTo(p3.dx, p3.dy)..lineTo(p4.dx, p4.dy)..close(),
            Paint()
              ..color = const Color(0xFFFFB020).withValues(alpha: 0.30)
              ..style = PaintingStyle.fill);
          canvas.drawPath(Path()..moveTo(p1.dx, p1.dy)..lineTo(p2.dx, p2.dy)
                                  ..lineTo(p3.dx, p3.dy)..lineTo(p4.dx, p4.dy)..close(),
            Paint()
              ..color = const Color(0xFFFFB020)
              ..style = PaintingStyle.stroke
              ..strokeWidth = 1.5);
        }
      }

      // ★ 정지 객체 검출 (staticMask) — 옅은 회색 outline 박스 (저신뢰도)
      var staticHint = 0;
      if (!isCameraShake) {
        final visitedS = List<bool>.filled(rows * cols, false);
        for (int r = 0; r < rows; r++) {
          for (int c = 0; c < cols; c++) {
            final idx = r * cols + c;
            if (visitedS[idx] || !staticMask[idx]) { visitedS[idx] = true; continue; }
            final queue = <List<int>>[[r, c]];
            visitedS[idx] = true;
            int minR = r, maxR = r, minC = c, maxC = c, scount = 0;
            while (queue.isNotEmpty) {
              final p = queue.removeLast();
              final cr = p[0], cc = p[1];
              scount++;
              if (cr < minR) minR = cr; if (cr > maxR) maxR = cr;
              if (cc < minC) minC = cc; if (cc > maxC) maxC = cc;
              for (final d in dirs8) {
                final nr = cr + d[0], nc = cc + d[1];
                if (nr < 0 || nr >= rows || nc < 0 || nc >= cols) continue;
                final ni = nr * cols + nc;
                if (visitedS[ni] || !staticMask[ni]) continue;
                visitedS[ni] = true;
                queue.add([nr, nc]);
              }
            }
            // 큰 정지 blob (≥ 6 cells) 만 표시
            if (scount >= 6 && staticHint < 6) {
              staticHint++;
              final wM = (maxC - minC + 1) * cellM;
              final lM = (maxR - minR + 1) * cellM;
              final cxM = (((minC + maxC) / 2 + 0.5) - cols / 2) * cellM;
              final czM = ((minR + maxR) / 2 + 0.5) * cellM;
              // 옅은 회색 outline box (정지 = 저신뢰도)
              final p1 = _project(cxM - wM/2, 0, czM - lM/2, cx, cz, size);
              final p2 = _project(cxM + wM/2, 0, czM - lM/2, cx, cz, size);
              final p3 = _project(cxM + wM/2, 0, czM + lM/2, cx, cz, size);
              final p4 = _project(cxM - wM/2, 0, czM + lM/2, cx, cz, size);
              final outlinePath = Path()
                ..moveTo(p1.dx, p1.dy)..lineTo(p2.dx, p2.dy)
                ..lineTo(p3.dx, p3.dy)..lineTo(p4.dx, p4.dy)..close();
              canvas.drawPath(outlinePath, Paint()
                ..color = const Color(0xFF8090A8).withValues(alpha: 0.15)
                ..style = PaintingStyle.fill);
              canvas.drawPath(outlinePath, Paint()
                ..color = const Color(0xFFA0B0C8).withValues(alpha: 0.55)
                ..style = PaintingStyle.stroke
                ..strokeWidth = 1.0);
            }
          }
        }
      }

      // 4) 잔여 voxel dots (background, 옅게)
      var dotCount = 0;
      for (int r = 0; r < rows; r++) {
        for (int c = 0; c < cols; c++) {
          final p = ((flat[r * cols + c] ?? 0) as num).toDouble();
          if (p < 0.50) continue;
          dotCount++;
          if (dotCount > 30) break;  // 최대 30 dot 만
          final xM = ((c - cols / 2) + 0.5) * cellM;
          final zM = (r + 0.5) * cellM;
          final base = _project(xM, 0, zM, cx, cz, size);
          canvas.drawCircle(base, 1.2, Paint()
            ..color = const Color(0xFF00E09A).withValues(alpha: 0.45));
        }
      }

      // 카운터 — 우상단 (신뢰도 명시) + FPS
      final totalDetect = personHint + vehicleHint;
      final fpsStr = fps > 0 ? ' · ${fps.toStringAsFixed(0)} fps' : '';
      final staticStr = staticHint > 0 ? ' · 정지 $staticHint' : '';
      final summary = isCameraShake
          ? '카메라 흔들림 (${(cameraShakeRatio*100).toStringAsFixed(0)}%)$fpsStr'
          : totalDetect > 0
            ? '사람 $personHint · 차량 $vehicleHint$staticStr$fpsStr'
            : (staticHint > 0 ? '정지 객체 $staticHint$fpsStr' : '대기$fpsStr');
      final tp = TextPainter(
        text: TextSpan(text: summary,
          style: TextStyle(
            color: totalDetect > 0 ? const Color(0xFF00E09A) : _muted.withValues(alpha: 0.85),
            fontSize: 9.5, fontWeight: FontWeight.w800, letterSpacing: 0.6)),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(size.width - tp.width - 8, 6));
      // 처리 파이프라인 표시 (좌상단)
      const pipeText = '📷 edge + motion (≥0.08) → 8-connected blob (≥4 cells)';
      final tp2 = TextPainter(
        text: TextSpan(text: pipeText,
          style: TextStyle(color: _muted.withValues(alpha: 0.7), fontSize: 8, fontWeight: FontWeight.w600)),
        textDirection: TextDirection.ltr,
        maxLines: 1,
      )..layout(maxWidth: size.width - 16);
      tp2.paint(canvas, const Offset(8, 6));
      // 검출 0개 또는 카메라 shake 시 화면 안내
      if ((totalDetect == 0 && staticHint == 0) || isCameraShake) {
        final msg = isCameraShake
            ? '📱 카메라 흔들림 감지 (${(cameraShakeRatio*100).toStringAsFixed(0)}%)\n폰 고정 시 객체 검출 재개'
            : '카메라 시야에 객체 없음';
        final tp3 = TextPainter(
          text: TextSpan(text: msg,
            style: TextStyle(color: isCameraShake ? _warn : _muted, fontSize: 11, fontWeight: FontWeight.w700, height: 1.4)),
          textDirection: TextDirection.ltr,
          textAlign: TextAlign.center,
          maxLines: 2,
        )..layout(maxWidth: size.width - 40);
        tp3.paint(canvas, Offset((size.width - tp3.width) / 2, size.height * 0.5));
      }
    } else if (hasClass) {
      final rows = (shape[0] as num).toInt();
      final cols = (shape[1] as num).toInt();
      final cellM = 40.0 / cols;

      // BFS flood-fill — 동일 class 인접 셀 클러스터링
      final visited = List<bool>.filled(rows * cols, false);
      final dirs = const [[-1, 0], [1, 0], [0, -1], [0, 1]];
      final clusters = <Map<String, dynamic>>[];

      for (int r = 0; r < rows; r++) {
        for (int c = 0; c < cols; c++) {
          final idx = r * cols + c;
          if (visited[idx]) continue;
          final cls = ((classFlat[idx] as num?) ?? 0).toInt();
          if (cls == 0) { visited[idx] = true; continue; }
          // BFS
          final queue = <List<int>>[[r, c]];
          visited[idx] = true;
          int minR = r, maxR = r, minC = c, maxC = c, count = 0;
          while (queue.isNotEmpty) {
            final p = queue.removeLast();
            final cr = p[0], cc = p[1];
            count++;
            if (cr < minR) minR = cr; if (cr > maxR) maxR = cr;
            if (cc < minC) minC = cc; if (cc > maxC) maxC = cc;
            for (final d in dirs) {
              final nr = cr + d[0], nc = cc + d[1];
              if (nr < 0 || nr >= rows || nc < 0 || nc >= cols) continue;
              final ni = nr * cols + nc;
              if (visited[ni]) continue;
              final ncls = ((classFlat[ni] as num?) ?? 0).toInt();
              if (ncls != cls) continue;
              visited[ni] = true;
              queue.add([nr, nc]);
            }
          }
          if (count >= 2 || cls == 4 || cls == 5) {
            clusters.add({
              'cls': cls, 'minR': minR, 'maxR': maxR, 'minC': minC, 'maxC': maxC, 'count': count,
            });
          }
        }
      }

      // 클러스터 — 멀리 (큰 row) 부터 그려서 가까운게 위로
      clusters.sort((a, b) => ((b['maxR'] as int) - (a['maxR'] as int)));

      for (final cl in clusters) {
        final cls = cl['cls'] as int;
        final minR = (cl['minR'] as int).toDouble();
        final maxR = (cl['maxR'] as int).toDouble();
        final minC = (cl['minC'] as int).toDouble();
        final maxC = (cl['maxC'] as int).toDouble();
        final wM = (maxC - minC + 1) * cellM;
        final lM = (maxR - minR + 1) * cellM;
        final cxM = (((minC + maxC) / 2 + 0.5) - cols / 2) * cellM;
        final czM = ((minR + maxR) / 2 + 0.5) * cellM;

        if (cls == 1) {
          _drawVehicle(canvas, size, cxM, czM, lM, wM, cx, cz);
        } else if (cls == 2) {
          _drawMotoBike(canvas, size, cxM, czM, lM, wM, cx, cz);
        } else if (cls == 3) {
          _drawOcclusion(canvas, size, cxM - wM/2, czM - lM/2, cxM + wM/2, czM + lM/2, cx, cz);
        } else if (cls == 4) {
          // 보행자 zone — 클러스터 면적 비례 N명 (2~4명)
          final n = (cl['count'] as int).clamp(0, 999);
          final peopleN = (n / 4).clamp(2, 4).toInt();
          for (int i = 0; i < peopleN; i++) {
            final ang = (i / peopleN) * 2 * math.pi + minR * 0.3;
            final px = cxM + math.cos(ang) * math.min(wM, lM) * 0.3;
            final pz = czM + math.sin(ang) * math.min(wM, lM) * 0.3;
            _drawPedestrianMarker(canvas, size, px, pz, cx, cz);
          }
        } else if (cls == 5) {
          _drawSignalMarker(canvas, size, cxM, czM, cx, cz);
        }
      }

      // ── 시나리오별 시각 보조 (우회전 화살표, 충돌점 등) ──
      final scnId = bev?['scenario_id'] as String?;
      if (scnId == 'right_turn_pedestrian') {
        _drawRightTurnAids(canvas, size, cx, cz);
      }

    }

    // ── hotspot 마커 (구체 + 빔) — DEMO 시나리오에서만 (LIVE 모드 막대기 제거)
    final hs = bev?['hotspots'];
    if (hs is List && isDemoScene) {
      final fineRows = (bev?['shape']?[0] ?? 80) as num;
      final fineCols = (bev?['shape']?[1] ?? 80) as num;
      for (final h in hs) {
        if (h is! Map) continue;
        final row = (h['row'] as num?)?.toDouble() ?? 0;
        final col = (h['col'] as num?)?.toDouble() ?? 0;
        final kind = h['kind'] as String? ?? 'object';
        final x = (col - fineCols / 2 + 0.5) * (40.0 / fineCols);
        final z = row * (40.0 / fineRows);
        final color = ({
          'object':           const Color(0xFFFF3B3B),
          'occluded_shadow':  const Color(0xFFFFB020),
          'intent_prior':     const Color(0xFF00E09A),
          'signal_shadow':    const Color(0xFF7C3AED),
        }[kind]) ?? _accent;
        // beam (바닥 → 위)
        final bot = _project(x, 0, z, cx, cz, size);
        final top = _project(x, 6.0, z, cx, cz, size);
        canvas.drawLine(bot, top, Paint()
          ..color = color.withValues(alpha: 0.6)
          ..strokeWidth = 1.5);
        // sphere (위)
        canvas.drawCircle(top, 5, Paint()
          ..color = color
          ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 4));
        canvas.drawCircle(top, 3.5, Paint()..color = color);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _Bev3DVoxelPainter old) =>
      old.bev != bev || old.t != t || old.zoom != zoom || old.yawDeg != yawDeg;
}



class _CameraPlaceholder extends StatelessWidget {
  const _CameraPlaceholder();
  @override
  Widget build(BuildContext context) {
    return Container(
      color: _bg,
      child: Center(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 32),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.no_photography_outlined, color: _muted, size: 56),
            const SizedBox(height: 16),
            const Text('카메라 권한이 필요합니다',
                style: TextStyle(color: _text, fontSize: 16, fontWeight: FontWeight.w800),
                textAlign: TextAlign.center),
            const SizedBox(height: 8),
            const Text(
              'AuraView는 운전 중 도로 영상을 분석해 사각지대를 보여줍니다.\n영상은 위험 순간만 PII 자동 마스킹 후 업로드됩니다.',
              style: TextStyle(color: _muted, fontSize: 12, height: 1.55),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 24),
            // 카메라 권한 재요청 버튼
            FilledButton.icon(
              onPressed: () async {
                final st = await Permission.camera.request();
                if (st.isPermanentlyDenied) {
                  await openAppSettings();
                }
              },
              icon: const Icon(Icons.camera_alt_outlined, size: 18),
              label: const Text('카메라 권한 허용'),
              style: FilledButton.styleFrom(
                backgroundColor: _accent, foregroundColor: _bg,
                padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 12),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(99)),
              ),
            ),
            const SizedBox(height: 10),
            // 영구 거부 시 시스템 설정 직접 열기
            TextButton.icon(
              onPressed: () => openAppSettings(),
              icon: const Icon(Icons.settings_outlined, size: 14, color: _muted),
              label: const Text('시스템 설정 직접 열기',
                  style: TextStyle(color: _muted, fontSize: 11, fontWeight: FontWeight.w700)),
            ),
            const SizedBox(height: 12),
            // 카메라 없이도 동작하는 부분 안내
            Text('카메라 없이도 GPS · 신호 · 15-source 데이터는 받습니다',
                style: TextStyle(color: _muted.withValues(alpha: 0.6), fontSize: 10, height: 1.4),
                textAlign: TextAlign.center),
          ]),
        ),
      ),
    );
  }
}

class _IdleStatusCard extends StatelessWidget {
  final int uploads;
  final int captures;
  final bool shadowOn;
  final String? intersectionId;
  final String? intersectionName;
  final VoidCallback? onSettingsTap;
  final VoidCallback? onRecToggleTap;   // v9.3: 헤더 REC 토글
  const _IdleStatusCard({
    required this.uploads,
    required this.captures,
    required this.shadowOn,
    this.intersectionId,
    this.intersectionName,
    this.onSettingsTap,
    this.onRecToggleTap,
  });

  @override
  Widget build(BuildContext context) {
    final hasInter = intersectionId != null && intersectionId!.isNotEmpty;
    return GestureDetector(
      onTap: onSettingsTap,  // 카드 어디든 탭하면 설정 열림
      child: Container(
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 11),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          begin: Alignment.topLeft, end: Alignment.bottomRight,
          colors: [Color(0xCC0D1520), Color(0xAA081020)],
        ),
        borderRadius: BorderRadius.circular(14),
        boxShadow: [BoxShadow(color: _accent.withValues(alpha: 0.18), blurRadius: 16)],
      ),
      child: Row(children: [
        // 좌측 — 브랜드 + 모드
        Expanded(
          flex: 3,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(children: [
                Container(
                  width: 8, height: 8,
                  decoration: BoxDecoration(
                    color: shadowOn ? _safe : _muted,
                    shape: BoxShape.circle,
                    boxShadow: [BoxShadow(color: shadowOn ? _safe : Colors.transparent, blurRadius: 6)],
                  ),
                ),
                const SizedBox(width: 6),
                Text('AURAVIEW · K-PERCEPTION',
                  style: TextStyle(
                    color: _accent, fontSize: 10,
                    fontWeight: FontWeight.w900, letterSpacing: 1.5,
                  )),
              ]),
              const SizedBox(height: 4),
              Text(
                hasInter
                  ? (intersectionName ?? '교차로 $intersectionId')
                  : (shadowOn ? '주행 모니터링 · 카메라 분석 중' : '주행 시작 버튼을 눌러 모니터링 시작'),
                maxLines: 1, overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: Color(0xFFE2EAF5), fontSize: 13.5,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                hasInter
                  ? '근접 교차로 자동 감지 · 가려진 신호등도 보여줍니다'
                  : (shadowOn ? '위험 순간만 자동으로 안전 데이터에 기여합니다' : '아래 주행 시작 버튼으로 모니터링을 켜세요'),
                style: TextStyle(
                  color: _muted, fontSize: 10.5,
                  fontFamily: 'monospace', fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(width: 10),
        // 우측 — 통계
        Column(
          crossAxisAlignment: CrossAxisAlignment.end,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(mainAxisSize: MainAxisSize.min, children: [
              Text('$captures', style: const TextStyle(color: Color(0xFFE2EAF5), fontSize: 18, fontWeight: FontWeight.w900)),
              const SizedBox(width: 4),
              Text('포착', style: TextStyle(color: _muted, fontSize: 10)),
            ]),
            Row(mainAxisSize: MainAxisSize.min, children: [
              Text('$uploads', style: TextStyle(color: _safe, fontSize: 14, fontWeight: FontWeight.w900)),
              const SizedBox(width: 4),
              Text('업로드', style: TextStyle(color: _muted, fontSize: 10)),
            ]),
          ],
        ),
        const SizedBox(width: 10),
        // v9 2026-05-18: "3D" 버튼 제거 — 메인 라이브 화면 자체가 3D BEV이므로 별도 진입점 불필요.
        // v7.4 2026-05-18: 심사위원 가산점 모드 (⭐ → /scorecard webview)
        Builder(builder: (ctx) => GestureDetector(
          onTap: () => Navigator.of(ctx).push(MaterialPageRoute(
            builder: (_) => const _JudgeModeScreen(),
          )),
          behavior: HitTestBehavior.opaque,
          child: Container(
            width: 38, height: 38,
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topLeft, end: Alignment.bottomRight,
                colors: [_safe.withValues(alpha: 0.30), _accent2.withValues(alpha: 0.20)],
              ),
              border: Border.all(color: _safe.withValues(alpha: 0.60), width: 1.2),
              borderRadius: BorderRadius.circular(10),
              boxShadow: [BoxShadow(color: _safe.withValues(alpha: 0.30), blurRadius: 9)],
            ),
            child: Center(child: Text('★',
                style: TextStyle(color: _safe, fontSize: 18,
                                 fontWeight: FontWeight.w900, height: 1.0))),
          ),
        )),
        // v10: 중복 ⚙ 설정 버튼 제거 (상단 헤더에 이미 있음). ★ 만 유지.
      ]),
    ),
    );
  }
}

class _SignalHud extends StatefulWidget {
  final Map<String, dynamic> altSignal;
  final String intersectionName;
  final bool pulse;
  const _SignalHud({
    required this.altSignal,
    required this.intersectionName,
    required this.pulse,
  });
  @override
  State<_SignalHud> createState() => _SignalHudState();
}

class _SignalHudState extends State<_SignalHud>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;
  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this, duration: const Duration(milliseconds: 1400),
    )..repeat(reverse: true);
  }
  @override
  void dispose() { _ctrl.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final s = widget.altSignal;
    final guide = (s['alt_guide'] ?? '') as String;
    final action = (s['alt_action'] ?? '') as String;
    final state = (s['signal_state'] ?? '') as String;
    final remain = s['remain_time_s'];
    final risk = s['risk_score'] ?? 0;
    final isStop = state.toLowerCase().contains('stop') || state.toLowerCase().contains('red');

    final mainColor = isStop ? const Color(0xFFFF5A5A) : const Color(0xFF00E09A);
    final iconBg = isStop ? const Color(0xFFFF5A5A) : const Color(0xFF00E09A);
    final iconLabel = isStop ? '⛔' : '🟢';

    return AnimatedBuilder(
      animation: _ctrl,
      builder: (_, __) {
        final t = widget.pulse ? _ctrl.value : 0.0;
        return Container(
          padding: const EdgeInsets.fromLTRB(14, 11, 14, 12),
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topLeft, end: Alignment.bottomRight,
              colors: [
                const Color(0xEE0D1520),
                isStop ? const Color(0xFF2A0F12) : const Color(0xFF0F2520),
              ],
            ),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(
              color: mainColor.withValues(alpha: 0.55 + 0.40 * t),
              width: 1.6 + 0.7 * t,
            ),
            boxShadow: [
              BoxShadow(
                color: mainColor.withValues(alpha: 0.30 + 0.35 * t),
                blurRadius: 16 + 14 * t,
              ),
            ],
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  // 신호 아이콘 (정지/주행) — 크기 키움
                  Container(
                    width: 48, height: 48,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: iconBg.withValues(alpha: 0.22),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: iconBg.withValues(alpha: 0.70), width: 1.5),
                      boxShadow: [BoxShadow(color: iconBg.withValues(alpha: 0.40), blurRadius: 10)],
                    ),
                    child: Text(iconLabel, style: const TextStyle(fontSize: 26)),
                  ),
                  const SizedBox(width: 12),
                  // 교차로명 + 상태
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          widget.intersectionName.isEmpty ? '근접 교차로 자동 감지 대기' : widget.intersectionName,
                          maxLines: 1, overflow: TextOverflow.ellipsis,
                          style: const TextStyle(color: Color(0xFFE2EAF5), fontSize: 16, fontWeight: FontWeight.w900, letterSpacing: -0.3),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          '$state' +
                          (remain != null ? ' · 남은 ${remain}초' : '') +
                          ' · risk $risk',
                          style: TextStyle(color: mainColor, fontSize: 12, fontFamily: 'monospace', fontWeight: FontWeight.w800, letterSpacing: 0.5),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              if (guide.isNotEmpty) ...[
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 11),
                  decoration: BoxDecoration(
                    color: Colors.black.withValues(alpha: 0.35),
                    borderRadius: BorderRadius.circular(10),
                    border: Border(left: BorderSide(color: mainColor, width: 4)),
                  ),
                  child: Text(
                    guide,
                    style: const TextStyle(color: Color(0xFFE2EAF5), fontSize: 14, height: 1.45, fontWeight: FontWeight.w700),
                  ),
                ),
              ],
              if (action.isNotEmpty) ...[
                const SizedBox(height: 8),
                Row(children: [
                  Icon(Icons.arrow_forward_rounded, size: 14, color: mainColor.withValues(alpha: 0.85)),
                  const SizedBox(width: 4),
                  Expanded(child: Text(
                    action,
                    style: TextStyle(color: mainColor.withValues(alpha: 0.95), fontSize: 12.5, fontWeight: FontWeight.w800, letterSpacing: 0.3),
                  )),
                ]),
              ],
            ],
          ),
        );
      },
    );
  }
}

class _LiveBadge extends StatelessWidget {
  final String reason;
  const _LiveBadge({required this.reason});
  @override
  Widget build(BuildContext context) {
    final isHard = reason != 'ok' && reason != 'idle';
    final color = isHard ? _warn : _safe;
    final label = {
      'high_entropy': '🔥 어려운 장면 — 기여 중',
      'motion_spike': '⚡ 큰 움직임 — 기여 중',
      'low_confidence': '⚠ 불확실 — 기여 중',
      'manual': '✨ 수동 기여',
      'ok': '✓ 안전 · 모니터링',
      'idle': '대기',
    }[reason] ?? reason;

    return AnimatedContainer(
      duration: const Duration(milliseconds: 350),
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 9),
      decoration: BoxDecoration(
        color: const Color(0xCC0D1520),
        borderRadius: BorderRadius.circular(99),
        border: Border.all(color: color.withValues(alpha: 0.5)),
        boxShadow: [BoxShadow(color: color.withValues(alpha: 0.18), blurRadius: 16)],
      ),
      child: Text(
        label,
        style: TextStyle(color: color, fontSize: 12.5, fontWeight: FontWeight.w800, letterSpacing: 0.3),
      ),
    );
  }
}

class _DetailSheet extends StatefulWidget {
  final String deviceId;
  final int captures, uploads, failures, serverTotal;
  final String serverError;
  final String? intersectionId;
  final Position? pos;
  final double lastEntropy;
  final String lastReason;
  final DateTime? lastUploadAt;
  final bool v2vEnabled;
  final int v2vSent;
  final ValueChanged<String> onIntersectionChanged;
  final ValueChanged<bool> onV2VChanged;

  const _DetailSheet({
    required this.deviceId,
    required this.captures, required this.uploads, required this.failures,
    required this.serverTotal, required this.serverError,
    required this.intersectionId, required this.pos,
    required this.lastEntropy, required this.lastReason,
    required this.lastUploadAt,
    required this.v2vEnabled, required this.v2vSent,
    required this.onIntersectionChanged,
    required this.onV2VChanged,
  });

  @override
  State<_DetailSheet> createState() => _DetailSheetState();
}

class _DetailSheetState extends State<_DetailSheet> {
  late final TextEditingController _intersectionCtrl =
      TextEditingController(text: widget.intersectionId ?? '');

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      initialChildSize: 0.62, minChildSize: 0.4, maxChildSize: 0.92, expand: false,
      builder: (_, ctrl) => Container(
        decoration: const BoxDecoration(
          color: _surface,
          borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
          boxShadow: [BoxShadow(color: Color(0x66000000), blurRadius: 30, offset: Offset(0, -6))],
        ),
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
        child: ListView(controller: ctrl, children: [
          // grip
          Center(
            child: Container(
              width: 42, height: 4,
              decoration: BoxDecoration(color: _muted.withValues(alpha: 0.5), borderRadius: BorderRadius.circular(99)),
            ),
          ),
          const SizedBox(height: 16),

          // v12.14: 실증 가능 안내 카드 — 브라우저로 API URL 열어 화면값 매칭 검증
          Container(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
            margin: const EdgeInsets.only(bottom: 12),
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                begin: Alignment.topLeft, end: Alignment.bottomRight,
                colors: [Color(0x3300C8FF), Color(0x2200E09A)],
              ),
              border: Border.all(color: const Color(0xFF00C8FF).withValues(alpha: 0.55), width: 1.2),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  const Text('🔬', style: TextStyle(fontSize: 18)),
                  const SizedBox(width: 8),
                  const Expanded(child: Text('실증 가능 — 화면값 = 서버 응답',
                    style: TextStyle(color: Color(0xFFB6F0FF), fontSize: 13.5,
                      fontWeight: FontWeight.w900, letterSpacing: 0.3))),
                ]),
                const SizedBox(height: 8),
                const Text(
                  '아래 URL 을 브라우저로 열어보시면 네이티브앱 화면의 모든 chip 값 (위험점수/TAAS/스쿨존/DTG/119/노후/V2X 등)이 서버 응답 JSON 과 1:1 일치하는 것을 즉시 확인 가능.',
                  style: TextStyle(color: _text, fontSize: 11.5, height: 1.5),
                ),
                const SizedBox(height: 8),
                Row(children: [
                  const Expanded(child: Text(
                    'auraview.allthatai.kr/fusion/intersection/1007',
                    style: TextStyle(color: Color(0xFFB6F0FF), fontSize: 10.5,
                      fontFamily: 'monospace', fontWeight: FontWeight.w700),
                  )),
                  GestureDetector(
                    onTap: () async {
                      await Clipboard.setData(const ClipboardData(text:
                        'https://auraview.allthatai.kr/fusion/intersection/1007'));
                      if (context.mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                          content: Text('🔬 실증 URL 복사됨 — 브라우저로 열어 화면 chip 과 매칭 확인'),
                          backgroundColor: Color(0xFF003E5C),
                          duration: Duration(seconds: 3),
                        ));
                      }
                    },
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                      decoration: BoxDecoration(
                        color: const Color(0xFF00C8FF), borderRadius: BorderRadius.circular(99),
                      ),
                      child: const Row(mainAxisSize: MainAxisSize.min, children: [
                        Icon(Icons.copy, size: 12, color: Color(0xFF0A0E18)),
                        SizedBox(width: 4),
                        Text('실증 URL 복사', style: TextStyle(color: Color(0xFF0A0E18),
                          fontSize: 11, fontWeight: FontWeight.w900)),
                      ]),
                    ),
                  ),
                ]),
                const SizedBox(height: 6),
                Row(children: [
                  const Icon(Icons.science_outlined, size: 12, color: Color(0xFF7CC8B0)),
                  const SizedBox(width: 4),
                  const Expanded(child: Text(
                    '/fusion/sources · 21 종 소스 카탈로그 + schema 검증',
                    style: TextStyle(color: Color(0xFF7CC8B0), fontSize: 10.5,
                      fontFamily: 'monospace', fontWeight: FontWeight.w700),
                  )),
                  GestureDetector(
                    onTap: () async {
                      await Clipboard.setData(const ClipboardData(text:
                        'https://auraview.allthatai.kr/fusion/sources'));
                      if (context.mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                          content: Text('/fusion/sources URL 복사됨'),
                          backgroundColor: Color(0xFF003E5C),
                          duration: Duration(seconds: 2),
                        ));
                      }
                    },
                    child: const Padding(
                      padding: EdgeInsets.symmetric(horizontal: 6, vertical: 3),
                      child: Icon(Icons.copy, size: 13, color: Color(0xFF7CC8B0)),
                    ),
                  ),
                ]),
              ],
            ),
          ),

          // ── v4 2026-05-16: 'AuraView가 뭐예요?' 카드 (처음 보는 사람용) ──
          Container(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 14),
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                begin: Alignment.topLeft, end: Alignment.bottomRight,
                colors: [Color(0x33FFB020), Color(0x22FF6B6B)],
              ),
              border: Border.all(color: const Color(0xFFFFB020).withValues(alpha: 0.55), width: 1.2),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  const Text('📖', style: TextStyle(fontSize: 20)),
                  const SizedBox(width: 8),
                  const Expanded(child: Text(
                    'AuraView가 뭐예요?',
                    style: TextStyle(color: Color(0xFFFFD78A), fontSize: 14, fontWeight: FontWeight.w900, letterSpacing: 0.3),
                  )),
                ]),
                const SizedBox(height: 6),
                const Text(
                  '운전자가 못 보는 곳을 21종 공공데이터와 V2V로 미리 알려주는 한국 도로 안전 AI. 평균 3.38초 먼저 위험 감지, 매년 21명 보호.',
                  style: TextStyle(color: _text, fontSize: 12, height: 1.55),
                ),
                const SizedBox(height: 10),
                Row(children: [
                  const Expanded(child: Text(
                    'auraview.allthatai.kr/story',
                    style: TextStyle(color: Color(0xFFFFB020), fontSize: 11, fontFamily: 'monospace', fontWeight: FontWeight.w700),
                  )),
                  GestureDetector(
                    onTap: () async {
                      await Clipboard.setData(const ClipboardData(text: 'https://auraview.allthatai.kr/story/'));
                      if (context.mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                          content: Text('링크 복사됨 — 브라우저로 열어보세요'),
                          backgroundColor: Color(0xFF003E5C),
                          duration: Duration(seconds: 2),
                        ));
                      }
                    },
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                      decoration: BoxDecoration(
                        color: const Color(0xFFFFB020),
                        borderRadius: BorderRadius.circular(99),
                      ),
                      child: const Row(mainAxisSize: MainAxisSize.min, children: [
                        Icon(Icons.copy, size: 12, color: Color(0xFF0A0E18)),
                        SizedBox(width: 4),
                        Text('링크 복사', style: TextStyle(color: Color(0xFF0A0E18), fontSize: 11, fontWeight: FontWeight.w900)),
                      ]),
                    ),
                  ),
                ]),
              ],
            ),
          ),
          const SizedBox(height: 16),

          // 라이브 통계
          Row(children: [
            _StatTile(label: '내 캡처', value: widget.captures.toString()),
            _StatTile(label: '내 기여', value: widget.uploads.toString(), highlight: _safe),
            _StatTile(label: '실패', value: widget.failures.toString(),
                       highlight: widget.failures > 0 ? _danger : null),
            _StatTile(label: '서버 누적',
                       value: widget.serverError.isNotEmpty ? '—' : '${widget.serverTotal}',
                       highlight: _accent),
          ]),

          const SizedBox(height: 18),
          _SectionTitle('// 마지막 분석'),
          _KV('Entropy', widget.lastEntropy.toStringAsFixed(2)),
          _KV('Reason', widget.lastReason),
          if (widget.lastUploadAt != null)
            _KV('직전 업로드', _ago(widget.lastUploadAt!)),

          const SizedBox(height: 18),
          _SectionTitle('// 현장 정보'),
          TextField(
            controller: _intersectionCtrl,
            decoration: InputDecoration(
              labelText: '교차로 ID (선택)',
              labelStyle: const TextStyle(color: _muted, fontSize: 11, letterSpacing: 1.2),
              filled: true, fillColor: _surface2,
              hintText: '예: 1007',
              hintStyle: const TextStyle(color: _muted),
              suffixIcon: const Icon(Icons.location_on_outlined, color: _muted, size: 18),
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: _accent.withValues(alpha: 0.2))),
              enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: _accent.withValues(alpha: 0.2))),
              focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: _accent)),
            ),
            style: const TextStyle(color: _text),
            onChanged: widget.onIntersectionChanged,
          ),
          const SizedBox(height: 12),
          if (widget.pos != null)
            _KV('현재 위치', '${widget.pos!.latitude.toStringAsFixed(4)}, ${widget.pos!.longitude.toStringAsFixed(4)}')
          else
            _KV('현재 위치', '권한 없음 또는 측정 중'),

          const SizedBox(height: 18),
          // v12.15: 데모 실험 모드 토글 — GPS 자동감지 대신 강제로 데모 교차로 사용
          _SectionTitle('// 데모/실험 모드 (옵트인)'),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: _surface2,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: const Color(0xFFFFB020).withValues(alpha: 0.25)),
            ),
            child: FutureBuilder<SharedPreferences>(
              future: SharedPreferences.getInstance(),
              builder: (ctx, snap) {
                final sp = snap.data;
                final on = sp?.getBool('demo_mode') ?? false;
                return Row(children: [
                  const Icon(Icons.science_outlined, color: Color(0xFFFFB020), size: 18),
                  const SizedBox(width: 10),
                  const Expanded(child: Text(
                    'GPS 미감지 시 강제로 한양대역 교차로(1007) 데모 데이터 표시',
                    style: TextStyle(color: _text, fontSize: 12, height: 1.4),
                  )),
                  Switch(
                    value: on,
                    onChanged: sp == null ? null : (v) async {
                      await sp.setBool('demo_mode', v);
                      if (ctx.mounted) ScaffoldMessenger.of(ctx).showSnackBar(SnackBar(
                        content: Text(v ? '데모 모드 ON — 앱 재시작 시 1007 강제'
                                       : '데모 모드 OFF — GPS 자동감지만 사용'),
                        backgroundColor: const Color(0xFF003E5C),
                        duration: const Duration(seconds: 2),
                      ));
                      // 즉시 반영하려면 setState 가 필요한데 _DetailSheetState 에는 미반영.
                      // 다음 _fetchBev 사이클에서 자연스럽게 적용됨.
                    },
                    activeThumbColor: const Color(0xFFFFB020),
                  ),
                ]);
              },
            ),
          ),
          const SizedBox(height: 18),

          _SectionTitle('// V2V 협업 인지'),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: _surface2,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: _accent.withValues(alpha: 0.18)),
            ),
            child: Column(children: [
              Row(children: [
                const Icon(Icons.cell_tower, color: _accent, size: 18),
                const SizedBox(width: 10),
                Expanded(child: Text(
                  '내 위치·속도·heading 을 같은 교차로 다른 차량과 공유',
                  style: TextStyle(color: _text.withValues(alpha: 0.85), fontSize: 12, height: 1.4),
                )),
                Switch(
                  value: widget.v2vEnabled,
                  onChanged: widget.onV2VChanged,
                  activeThumbColor: _accent,
                ),
              ]),
              if (widget.v2vEnabled)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Row(children: [
                    const Icon(Icons.send_rounded, color: _safe, size: 14),
                    const SizedBox(width: 6),
                    Text('전송 ${widget.v2vSent}건',
                        style: const TextStyle(color: _safe, fontSize: 11, fontFamily: 'monospace', fontWeight: FontWeight.w700)),
                    const Spacer(),
                    Text(
                      widget.intersectionId == null || widget.intersectionId!.isEmpty
                        ? '⚠ 교차로 ID 입력 시 활성화'
                        : 'intersection ${widget.intersectionId}',
                      style: TextStyle(color: _muted, fontSize: 10, fontFamily: 'monospace'),
                    ),
                  ]),
                ),
            ]),
          ),

          const SizedBox(height: 18),
          _SectionTitle('// 디바이스'),
          _KV('Device ID', _shortId(widget.deviceId)),
          _KV('서버 상태', widget.serverError.isEmpty ? '연결됨' : widget.serverError,
              highlight: widget.serverError.isEmpty ? _safe : _warn),
          _KV('백엔드', kApiBase.replaceFirst('https://', '')),

          const SizedBox(height: 18),
          _SectionTitle('// 경진대회 KPI · 심사 검증용'),
          GestureDetector(
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const _CompetitionKpiScreen()),
            ),
            child: Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  colors: [_safe.withValues(alpha: 0.14), _accent.withValues(alpha: 0.06)],
                ),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: _safe.withValues(alpha: 0.30)),
              ),
              child: const Row(children: [
                Icon(Icons.workspace_premium, color: _safe, size: 22),
                SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('통합 KPI 4축 한 화면',
                        style: TextStyle(color: _text, fontSize: 13.5, fontWeight: FontWeight.w700)),
                      SizedBox(height: 2),
                      Text('AUC · 임팩트 · 공공데이터 · 검증 · git_sha',
                        style: TextStyle(color: _muted, fontSize: 10.5, fontFamily: 'monospace')),
                    ],
                  ),
                ),
                Icon(Icons.arrow_forward_ios_rounded, color: _muted, size: 14),
              ]),
            ),
          ),

          const SizedBox(height: 18),
          _SectionTitle('// 내 업로드 갤러리 (서버)'),
          GestureDetector(
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const _FleetGalleryScreen()),
            ),
            child: Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  colors: [_accent.withValues(alpha: 0.10), _accent2.withValues(alpha: 0.05)],
                ),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: _accent.withValues(alpha: 0.30)),
              ),
              child: const Row(children: [
                Icon(Icons.photo_library_outlined, color: _accent, size: 22),
                SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('서버에 업로드된 이미지 보기',
                        style: TextStyle(color: _text, fontSize: 13.5, fontWeight: FontWeight.w700)),
                      SizedBox(height: 2),
                      Text('PII 마스킹된 버전 · 관리자 토큰 필요',
                        style: TextStyle(color: _muted, fontSize: 10.5, fontFamily: 'monospace')),
                    ],
                  ),
                ),
                Icon(Icons.arrow_forward_ios_rounded, color: _muted, size: 14),
              ]),
            ),
          ),

          const SizedBox(height: 18),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: _surface2,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: _safe.withValues(alpha: 0.30)),
            ),
            child: const Row(children: [
              Icon(Icons.shield_outlined, color: _safe, size: 18),
              SizedBox(width: 10),
              Expanded(
                child: Text(
                  '📌 폰에는 이미지를 저장하지 않습니다.\n캡처 → PII 마스킹 → 업로드 → 즉시 폐기 (임시 파일).\n서버에는 마스킹된 버전만 보관 · 디바이스 ID 가명화.',
                  style: TextStyle(color: _muted, fontSize: 12, height: 1.5),
                ),
              ),
            ]),
          ),
        ]),
      ),
    );
  }

  String _shortId(String id) => id.length > 24 ? '${id.substring(0, 14)}…${id.substring(id.length - 6)}' : id;

  String _ago(DateTime t) {
    final diff = DateTime.now().difference(t);
    if (diff.inSeconds < 5) return '방금';
    if (diff.inSeconds < 60) return '${diff.inSeconds}초 전';
    if (diff.inMinutes < 60) return '${diff.inMinutes}분 전';
    return '${diff.inHours}시간 전';
  }
}

class _SectionTitle extends StatelessWidget {
  final String label;
  const _SectionTitle(this.label);
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Text(label, style: const TextStyle(color: _accent, fontSize: 11, letterSpacing: 2.4, fontFamily: 'monospace')),
  );
}

class _KV extends StatelessWidget {
  final String k;
  final String v;
  final Color? highlight;
  const _KV(this.k, this.v, {this.highlight});
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 5),
    child: Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(k, style: const TextStyle(color: _muted, fontSize: 12)),
        const SizedBox(width: 16),
        Flexible(
          child: Text(v, textAlign: TextAlign.right,
              style: TextStyle(color: highlight ?? _text, fontSize: 12.5, fontWeight: FontWeight.w700, fontFamily: 'monospace')),
        ),
      ],
    ),
  );
}

class _StatTile extends StatelessWidget {
  final String label;
  final String value;
  final Color? highlight;
  const _StatTile({required this.label, required this.value, this.highlight});

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        margin: const EdgeInsets.symmetric(horizontal: 4),
        padding: const EdgeInsets.symmetric(vertical: 12),
        decoration: BoxDecoration(
          color: _surface2,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: _accent.withValues(alpha: 0.15)),
        ),
        child: Column(children: [
          Text(label, style: const TextStyle(color: _muted, fontSize: 9.5, letterSpacing: 1.5, fontFamily: 'monospace')),
          const SizedBox(height: 6),
          Text(value, style: TextStyle(color: highlight ?? _text, fontSize: 22, fontWeight: FontWeight.w900)),
        ]),
      ),
    );
  }
}


// ──────────────────────────────────────────────────────────────────────
// 내 업로드 이미지 갤러리 — 서버에 마스킹된 버전만 저장됨 · 폰 자체 저장 X
// ──────────────────────────────────────────────────────────────────────
class _FleetGalleryScreen extends StatefulWidget {
  const _FleetGalleryScreen();
  @override
  State<_FleetGalleryScreen> createState() => _FleetGalleryScreenState();
}

class _FleetGalleryScreenState extends State<_FleetGalleryScreen> {
  List<dynamic> _items = [];
  bool _loading = false;
  String? _error;
  String _adminToken = '';
  final TextEditingController _tokenCtrl = TextEditingController();
  // 일괄 선택 모드
  bool _selectMode = false;
  final Set<String> _selected = {};   // 파일명 set
  bool _deleting = false;

  @override
  void initState() {
    super.initState();
    _loadToken();
  }

  Future<void> _loadToken() async {
    final sp = await SharedPreferences.getInstance();
    final tok = sp.getString('admin_token') ?? '';
    if (mounted) {
      setState(() {
        _adminToken = tok;
        _tokenCtrl.text = tok;
      });
    }
    if (tok.isNotEmpty) await _fetchList();
  }

  Future<void> _saveToken(String tok) async {
    final sp = await SharedPreferences.getInstance();
    await sp.setString('admin_token', tok);
    if (mounted) setState(() => _adminToken = tok);
  }

  Future<void> _fetchList() async {
    if (_adminToken.isEmpty) {
      setState(() => _error = '관리자 토큰을 입력하세요');
      return;
    }
    setState(() { _loading = true; _error = null; });
    try {
      final r = await http.get(
        Uri.parse('$kApiBase/fleet/list?limit=100'),
        headers: {'X-Admin-Token': _adminToken},
      ).timeout(const Duration(seconds: 8));
      if (r.statusCode == 401) {
        setState(() { _error = '토큰이 잘못됐습니다'; _items = []; });
      } else if (r.statusCode == 200) {
        final body = jsonDecode(r.body);
        if (body is List) {
          setState(() => _items = body);
        }
      } else {
        setState(() => _error = '서버 응답 ${r.statusCode}');
      }
    } catch (e) {
      setState(() => _error = '네트워크: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  String _ago(String? iso) {
    if (iso == null) return '—';
    try {
      final t = DateTime.parse(iso.replaceAll('Z', ''));
      final d = DateTime.now().difference(t);
      if (d.inMinutes < 1) return '방금';
      if (d.inMinutes < 60) return '${d.inMinutes}분 전';
      if (d.inHours < 24) return '${d.inHours}시간 전';
      return '${d.inDays}일 전';
    } catch (_) { return iso; }
  }

  void _toggleSelect(String fname) {
    setState(() {
      if (_selected.contains(fname)) {
        _selected.remove(fname);
      } else {
        _selected.add(fname);
      }
    });
  }

  void _selectAll() {
    setState(() {
      if (_selected.length == _items.length) {
        _selected.clear();
      } else {
        _selected
          ..clear()
          ..addAll(_items.map((it) => (it['path'] ?? '').toString().split('/').last)
              .where((s) => s.isNotEmpty));
      }
    });
  }

  Future<void> _confirmAndDelete() async {
    if (_selected.isEmpty) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _surface,
        title: Text('${_selected.length}개 이미지 삭제',
          style: const TextStyle(color: _text, fontSize: 16, fontWeight: FontWeight.w700)),
        content: const Text(
          '서버에서 영구 삭제됩니다. 되돌릴 수 없습니다.\n'
          'manifest 에서도 제거 · 폰에는 원래 저장 안됨.',
          style: TextStyle(color: _muted, fontSize: 13, height: 1.5),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false),
              child: const Text('취소', style: TextStyle(color: _muted))),
          TextButton(onPressed: () => Navigator.pop(ctx, true),
              child: const Text('삭제', style: TextStyle(color: _danger, fontWeight: FontWeight.w700))),
        ],
      ),
    );
    if (ok != true) return;
    setState(() => _deleting = true);
    try {
      final r = await http.post(
        Uri.parse('$kApiBase/fleet/delete-batch'),
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Token': _adminToken,
        },
        body: jsonEncode({'filenames': _selected.toList()}),
      ).timeout(const Duration(seconds: 12));
      if (r.statusCode == 200) {
        final body = jsonDecode(r.body) as Map<String, dynamic>;
        final deleted = (body['deleted'] as List?)?.length ?? 0;
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('$deleted개 삭제 완료'),
            backgroundColor: _safe,
            duration: const Duration(seconds: 2),
          ));
          _selected.clear();
          _selectMode = false;
        }
        await _fetchList();
      } else {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('삭제 실패 ${r.statusCode}'),
            backgroundColor: _danger,
          ));
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('네트워크: $e'),
          backgroundColor: _danger,
        ));
      }
    } finally {
      if (mounted) setState(() => _deleting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      appBar: AppBar(
        backgroundColor: _surface,
        title: Text(
          _selectMode ? '${_selected.length}개 선택' : '내 업로드 갤러리',
          style: const TextStyle(color: _text, fontWeight: FontWeight.w700, fontSize: 16),
        ),
        iconTheme: const IconThemeData(color: _accent),
        elevation: 0,
        actions: [
          if (_selectMode) ...[
            IconButton(
              icon: const Icon(Icons.select_all, color: _accent),
              onPressed: _items.isEmpty ? null : _selectAll,
              tooltip: '전체 선택',
            ),
            IconButton(
              icon: _deleting
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(color: _danger, strokeWidth: 2))
                : const Icon(Icons.delete_forever, color: _danger),
              onPressed: (_selected.isEmpty || _deleting) ? null : _confirmAndDelete,
              tooltip: '선택 삭제',
            ),
            IconButton(
              icon: const Icon(Icons.close, color: _muted),
              onPressed: () => setState(() {
                _selectMode = false;
                _selected.clear();
              }),
              tooltip: '취소',
            ),
          ] else ...[
            IconButton(
              icon: const Icon(Icons.checklist_rounded, color: _accent),
              onPressed: _items.isEmpty ? null : () => setState(() => _selectMode = true),
              tooltip: '일괄 선택',
            ),
            IconButton(
              icon: const Icon(Icons.refresh, color: _accent),
              onPressed: _loading ? null : _fetchList,
              tooltip: '새로고침',
            ),
          ],
        ],
      ),
      body: Column(children: [
        // 토큰 입력 영역
        Container(
          margin: const EdgeInsets.all(14),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: _surface,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: _accent.withValues(alpha: 0.20)),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              const Icon(Icons.key, color: _accent, size: 16),
              const SizedBox(width: 8),
              Text('관리자 토큰',
                style: TextStyle(color: _muted, fontSize: 11, letterSpacing: 1.4, fontFamily: 'monospace')),
            ]),
            const SizedBox(height: 8),
            TextField(
              controller: _tokenCtrl,
              obscureText: true,
              decoration: InputDecoration(
                hintText: '예: auraview-admin-2026',
                hintStyle: const TextStyle(color: _muted, fontSize: 12),
                filled: true, fillColor: _surface2,
                contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide.none),
                suffixIcon: IconButton(
                  icon: const Icon(Icons.send, color: _accent, size: 18),
                  onPressed: () async {
                    await _saveToken(_tokenCtrl.text.trim());
                    await _fetchList();
                  },
                ),
              ),
              style: const TextStyle(color: _text, fontFamily: 'monospace'),
            ),
          ]),
        ),

        // 안내문
        Container(
          margin: const EdgeInsets.symmetric(horizontal: 14),
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: _safe.withValues(alpha: 0.06),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: _safe.withValues(alpha: 0.25)),
          ),
          child: const Row(children: [
            Icon(Icons.shield_outlined, color: _safe, size: 14),
            SizedBox(width: 8),
            Expanded(child: Text(
              '폰에는 저장 X · 서버에는 PII 마스킹된 버전만 보관',
              style: TextStyle(color: _muted, fontSize: 11),
            )),
          ]),
        ),

        // 결과 영역
        Expanded(
          child: _loading
            ? const Center(child: CircularProgressIndicator(color: _accent))
            : _error != null
              ? Center(child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Text(_error!,
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: _danger, fontSize: 13)),
                ))
              : _items.isEmpty
                ? const Center(child: Text('업로드된 이미지가 없습니다',
                    style: TextStyle(color: _muted, fontSize: 13)))
                : GridView.builder(
                    padding: const EdgeInsets.all(14),
                    gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: 2,
                      mainAxisSpacing: 10,
                      crossAxisSpacing: 10,
                      childAspectRatio: 0.85,
                    ),
                    itemCount: _items.length,
                    itemBuilder: (_, i) {
                      final it = _items[i] as Map<String, dynamic>;
                      final fname = (it['path'] ?? '').toString().split('/').last;
                      final url = '$kApiBase/fleet/image/$fname?token=$_adminToken';
                      final reason = it['reason'] ?? 'unknown';
                      final entropy = (it['entropy'] ?? 0.0) is num ? it['entropy'].toStringAsFixed(2) : '—';
                      final ts = it['ts'] ?? it['uploaded_at'];
                      final size = it['size_kb'] ?? 0;
                      final isSelected = _selected.contains(fname);
                      return GestureDetector(
                        onTap: () {
                          if (_selectMode) {
                            _toggleSelect(fname);
                          } else {
                            Navigator.of(context).push(MaterialPageRoute(
                              builder: (_) => _FleetImageDetailScreen(url: url, item: it),
                            ));
                          }
                        },
                        onLongPress: () {
                          if (!_selectMode) {
                            setState(() => _selectMode = true);
                          }
                          _toggleSelect(fname);
                        },
                        child: Stack(children: [
                          Container(
                            decoration: BoxDecoration(
                              color: _surface,
                              borderRadius: BorderRadius.circular(10),
                              border: Border.all(
                                color: isSelected ? _accent : _accent.withValues(alpha: 0.15),
                                width: isSelected ? 2.4 : 1,
                              ),
                            ),
                            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                              Expanded(
                                child: ClipRRect(
                                  borderRadius: const BorderRadius.vertical(top: Radius.circular(10)),
                                  child: Image.network(
                                    url,
                                    fit: BoxFit.cover,
                                    loadingBuilder: (_, child, prog) => prog == null
                                      ? child
                                      : Container(color: _surface2,
                                          child: const Center(child: CircularProgressIndicator(color: _accent, strokeWidth: 2))),
                                    errorBuilder: (_, _, _) => Container(
                                      color: _surface2,
                                      child: const Center(child: Icon(Icons.broken_image_outlined, color: _muted)),
                                    ),
                                  ),
                                ),
                              ),
                              Padding(
                                padding: const EdgeInsets.all(8),
                                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                                  Text(reason, style: const TextStyle(color: _accent, fontSize: 10.5, fontFamily: 'monospace', fontWeight: FontWeight.w700)),
                                  const SizedBox(height: 2),
                                  Text('H=$entropy · ${size}KB',
                                    style: const TextStyle(color: _muted, fontSize: 9.5, fontFamily: 'monospace')),
                                  Text(_ago(ts is String ? ts : null),
                                    style: const TextStyle(color: _muted, fontSize: 9.5)),
                                ]),
                              ),
                            ]),
                          ),
                          if (_selectMode)
                            Positioned(top: 6, right: 6,
                              child: Container(
                                width: 24, height: 24,
                                decoration: BoxDecoration(
                                  shape: BoxShape.circle,
                                  color: isSelected ? _accent : Colors.black.withValues(alpha: 0.55),
                                  border: Border.all(color: Colors.white, width: 1.5),
                                ),
                                child: Icon(
                                  isSelected ? Icons.check : Icons.circle_outlined,
                                  color: Colors.white,
                                  size: 16,
                                ),
                              ),
                            ),
                        ]),
                      );
                    },
                  ),
        ),
      ]),
    );
  }
}


class _FleetImageDetailScreen extends StatelessWidget {
  final String url;
  final Map<String, dynamic> item;
  const _FleetImageDetailScreen({required this.url, required this.item});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black87,
        iconTheme: const IconThemeData(color: _accent),
        title: Text(item['reason']?.toString() ?? '이미지',
          style: const TextStyle(color: _text, fontSize: 14)),
        elevation: 0,
      ),
      body: Column(children: [
        Expanded(
          child: InteractiveViewer(
            minScale: 0.5, maxScale: 4,
            child: Image.network(url, fit: BoxFit.contain,
              errorBuilder: (_, __, ___) => const Center(
                child: Icon(Icons.broken_image_outlined, color: _muted, size: 64),
              ),
            ),
          ),
        ),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(14),
          color: Colors.black87,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (final entry in item.entries)
              if (entry.value != null && entry.value.toString().isNotEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(children: [
                    SizedBox(width: 110,
                      child: Text(entry.key, style: const TextStyle(color: _muted, fontSize: 11, fontFamily: 'monospace'))),
                    Expanded(child: Text(entry.value.toString(),
                      style: const TextStyle(color: _text, fontSize: 11.5, fontFamily: 'monospace'),
                      overflow: TextOverflow.ellipsis)),
                  ]),
                ),
          ]),
        ),
      ]),
    );
  }
}


// ──────────────────────────────────────────────────────────────────────
// 경진대회 KPI 패널 — 심사위원 1-step 검증용 폰 화면
// /metrics/competition 응답 → 4 축 (모델·임팩트·공공데이터·검증) 한 화면에
// ──────────────────────────────────────────────────────────────────────
class _CompetitionKpiScreen extends StatefulWidget {
  const _CompetitionKpiScreen();
  @override
  State<_CompetitionKpiScreen> createState() => _CompetitionKpiScreenState();
}

class _CompetitionKpiScreenState extends State<_CompetitionKpiScreen> {
  Map<String, dynamic>? _data;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _fetch();
  }

  Future<void> _fetch() async {
    setState(() { _loading = true; _error = null; });
    try {
      final r = await http.get(Uri.parse('$kApiBase/metrics/competition'))
          .timeout(const Duration(seconds: 8));
      if (r.statusCode == 200) {
        setState(() => _data = jsonDecode(r.body) as Map<String, dynamic>);
      } else {
        setState(() => _error = '서버 ${r.statusCode}');
      }
    } catch (e) {
      setState(() => _error = '네트워크: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Widget _kpiCard(String label, String value, {Color? color, String? sub}) {
    final c = color ?? _accent;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: _surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: c.withValues(alpha: 0.30)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: TextStyle(color: c, fontSize: 9.5, letterSpacing: 1.5, fontFamily: 'monospace', fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        Text(value, style: TextStyle(color: c, fontSize: 26, fontWeight: FontWeight.w900, height: 1)),
        if (sub != null) ...[
          const SizedBox(height: 4),
          Text(sub, style: const TextStyle(color: _muted, fontSize: 10.5, fontFamily: 'monospace')),
        ],
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final mp = _data?['model_performance'] as Map<String, dynamic>?;
    final ie = _data?['impact_estimate'] as Map<String, dynamic>?;
    final headline = ie?['headline_pilot_5pct'] as Map<String, dynamic>?;
    final pf = _data?['public_data_fusion'] as Map<String, dynamic>?;
    final ver = _data?['verification'] as Map<String, dynamic>?;

    return Scaffold(
      backgroundColor: _bg,
      appBar: AppBar(
        backgroundColor: _surface,
        title: const Text('경진대회 KPI',
          style: TextStyle(color: _text, fontWeight: FontWeight.w700, fontSize: 16)),
        iconTheme: const IconThemeData(color: _accent),
        elevation: 0,
        actions: [
          IconButton(icon: const Icon(Icons.refresh, color: _accent), onPressed: _fetch),
        ],
      ),
      body: _loading
        ? const Center(child: CircularProgressIndicator(color: _accent))
        : _error != null
          ? Center(child: Padding(padding: const EdgeInsets.all(20),
              child: Text(_error!, textAlign: TextAlign.center,
                style: const TextStyle(color: _danger, fontSize: 13))))
          : ListView(
              padding: const EdgeInsets.all(14),
              children: [
                // 헤더
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      colors: [_accent.withValues(alpha: 0.16), _accent2.withValues(alpha: 0.08)],
                    ),
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(color: _accent.withValues(alpha: 0.30)),
                  ),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    const Text('AuraView K-Perception',
                      style: TextStyle(color: _text, fontSize: 18, fontWeight: FontWeight.w900)),
                    const SizedBox(height: 4),
                    Text('${_data?['version'] ?? '—'}  ·  git ${_data?['git_sha'] ?? 'unknown'}',
                      style: const TextStyle(color: _muted, fontSize: 11, fontFamily: 'monospace')),
                    const SizedBox(height: 4),
                    Text('2026 국토교통 데이터활용 경진대회',
                      style: TextStyle(color: _accent, fontSize: 11, fontFamily: 'monospace', letterSpacing: 1.2)),
                  ]),
                ),
                const SizedBox(height: 16),

                // 1) 모델 성능
                _SectionTitle('// 1. MODEL PERFORMANCE'),
                Row(children: [
                  Expanded(child: _kpiCard('AUC', '${mp?['auc'] ?? '—'}',
                    color: _accent, sub: 'Risk Transformer trained')),
                  const SizedBox(width: 8),
                  Expanded(child: _kpiCard('F1@0.5', '${mp?['f1'] ?? '—'}',
                    color: _safe, sub: 'Backend ${mp?['backend'] ?? '—'}')),
                ]),
                const SizedBox(height: 8),
                _kpiCard('p99 추론 지연', '${mp?['p99_inference_ms'] ?? '—'} ms',
                  color: _accent2, sub: 'CPU 단일 코어 100회 측정'),

                const SizedBox(height: 18),

                // 2) 임팩트
                _SectionTitle('// 2. PROJECTED IMPACT (TAAS 2024)'),
                _kpiCard('연간 사망 예방 (5% pilot)',
                  '${headline?['prevented_deaths_yr'] ?? '—'}명',
                  color: _safe, sub: 'avg lead time 3.38s · preventability 84.5%'),
                const SizedBox(height: 8),
                Row(children: [
                  Expanded(child: _kpiCard('사고 예방',
                    _formatNum(headline?['prevented_incidents_yr']),
                    color: _accent, sub: '건/년')),
                  const SizedBox(width: 8),
                  Expanded(child: _kpiCard('부상 예방',
                    _formatNum(headline?['prevented_injuries_yr']),
                    color: _warn, sub: '명/년')),
                ]),

                const SizedBox(height: 18),

                // 3) 공공데이터
                _SectionTitle('// 3. PUBLIC DATA FUSION'),
                Row(children: [
                  Expanded(child: _kpiCard('LIVE', '${pf?['sources_live'] ?? 0}',
                    color: _safe, sub: '실시간 폴링')),
                  const SizedBox(width: 8),
                  Expanded(child: _kpiCard('STUB', '${pf?['sources_stub'] ?? 0}',
                    color: _warn, sub: 'fallback 명시적')),
                  const SizedBox(width: 8),
                  Expanded(child: _kpiCard('TOTAL', '${pf?['sources_total'] ?? 6}',
                    color: _accent, sub: '신호·VDS·돌발·TAAS·ITS·DSZ')),
                ]),

                const SizedBox(height: 18),

                // 4) 검증
                _SectionTitle('// 4. VERIFICATION'),
                Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: _surface,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: _safe.withValues(alpha: 0.30)),
                  ),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(ver?['tests'] ?? '—',
                      style: const TextStyle(color: _safe, fontSize: 14, fontWeight: FontWeight.w700)),
                    const SizedBox(height: 4),
                    Text(ver?['ci'] ?? '—',
                      style: const TextStyle(color: _muted, fontSize: 11, fontFamily: 'monospace')),
                    const SizedBox(height: 4),
                    Text('Fallback mode: ${ver?['fallback_mode'] == true ? 'ON (시연용)' : 'OFF'}',
                      style: const TextStyle(color: _muted, fontSize: 11, fontFamily: 'monospace')),
                  ]),
                ),

                const SizedBox(height: 18),

                // 시나리오
                _SectionTitle('// SCENARIOS SUPPORTED'),
                Wrap(spacing: 6, runSpacing: 6, children: [
                  for (final s in (_data?['scenarios_supported'] as List? ?? []))
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        color: _surface,
                        borderRadius: BorderRadius.circular(99),
                        border: Border.all(color: _accent.withValues(alpha: 0.30)),
                      ),
                      child: Text(s.toString(),
                        style: const TextStyle(color: _text, fontSize: 11, fontFamily: 'monospace')),
                    ),
                ]),

                const SizedBox(height: 24),
                Text('생성: ${_data?['as_of'] ?? '—'}',
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: _muted, fontSize: 10, fontFamily: 'monospace')),
                const SizedBox(height: 4),
                Text('GET /metrics/competition',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: _muted.withValues(alpha: 0.6), fontSize: 9.5, fontFamily: 'monospace')),
                const SizedBox(height: 24),
              ],
            ),
    );
  }

  String _formatNum(dynamic v) {
    if (v == null) return '—';
    if (v is num) {
      final s = v.round().toString();
      // thousand separator
      final buf = StringBuffer();
      for (int i = 0; i < s.length; i++) {
        if (i > 0 && (s.length - i) % 3 == 0) buf.write(',');
        buf.write(s[i]);
      }
      return buf.toString();
    }
    return v.toString();
  }
}

// ─────────────────────────────────────────────────────────────────
// v5 2026-05-17: 첫 진입 온보딩 (3장 PageView)
// ─────────────────────────────────────────────────────────────────
class _OnboardingScreen extends StatefulWidget {
  final VoidCallback onDone;
  const _OnboardingScreen({required this.onDone});
  @override
  State<_OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<_OnboardingScreen> {
  final _ctrl = PageController();
  int _page = 0;
  static const _pages = [
    _OnboardPage(
      icon: '👀',
      title: 'AuraView가 뭐예요?',
      body: '운전 중 트럭에 가려진 신호등, 사각지대 보행자를\n15종 공공데이터와 V2V로 미리 알려주는 한국 도로 안전 AI 입니다.',
      accent: Color(0xFFFFB020),
    ),
    _OnboardPage(
      icon: '🛡️',
      title: '내 폰이 도로의 눈이 됩니다',
      body: '카메라 + GPS 로 위험 순간만 자동 감지.\n영상은 PII 자동 마스킹 후 업로드 → AI 재학습.\n폰에는 이미지가 저장되지 않습니다.',
      accent: Color(0xFF00E09A),
    ),
    _OnboardPage(
      icon: '🤝',
      title: '권한이 필요합니다',
      body: '• 카메라 (필수) — 도로 영상 분석\n• 위치 (선택) — 교차로 자동 감지\n• 인터넷 (필수) — 안전 데이터 기여\n다음 화면에서 허용 또는 거부 선택.',
      accent: Color(0xFF00C8FF),
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final isLast = _page == _pages.length - 1;
    return Scaffold(
      backgroundColor: _bg,
      body: SafeArea(
        child: Column(children: [
          // 상단 skip
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 14, 20, 0),
            child: Row(mainAxisAlignment: MainAxisAlignment.end, children: [
              TextButton(
                onPressed: widget.onDone,
                child: const Text('건너뛰기', style: TextStyle(color: _muted, fontWeight: FontWeight.w700)),
              ),
            ]),
          ),
          // PageView
          Expanded(
            child: PageView.builder(
              controller: _ctrl,
              itemCount: _pages.length,
              onPageChanged: (i) => setState(() => _page = i),
              itemBuilder: (_, i) => _pages[i],
            ),
          ),
          // 인디케이터
          Row(mainAxisAlignment: MainAxisAlignment.center, children: List.generate(_pages.length, (i) {
            final active = i == _page;
            return AnimatedContainer(
              duration: const Duration(milliseconds: 220),
              margin: const EdgeInsets.symmetric(horizontal: 4),
              width: active ? 24 : 8, height: 8,
              decoration: BoxDecoration(
                color: active ? _accent : _muted.withValues(alpha: 0.3),
                borderRadius: BorderRadius.circular(99),
              ),
            );
          })),
          const SizedBox(height: 22),
          // 다음 / 시작 버튼
          Padding(
            padding: const EdgeInsets.fromLTRB(28, 0, 28, 28),
            child: SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: () {
                  if (isLast) {
                    widget.onDone();
                  } else {
                    _ctrl.nextPage(duration: const Duration(milliseconds: 280), curve: Curves.easeOutCubic);
                  }
                },
                style: FilledButton.styleFrom(
                  backgroundColor: isLast ? _safe : _accent,
                  foregroundColor: _bg,
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(99)),
                ),
                child: Text(isLast ? '시작하기' : '다음',
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w900, letterSpacing: 1.5)),
              ),
            ),
          ),
        ]),
      ),
    );
  }
}

class _OnboardPage extends StatelessWidget {
  final String icon;
  final String title;
  final String body;
  final Color accent;
  const _OnboardPage({required this.icon, required this.title, required this.body, required this.accent});
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 32),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Container(
            width: 140, height: 140,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: RadialGradient(
                colors: [accent.withValues(alpha: 0.35), accent.withValues(alpha: 0.05), Colors.transparent],
              ),
            ),
            child: Center(child: Text(icon, style: const TextStyle(fontSize: 80))),
          ),
          const SizedBox(height: 36),
          Text(title,
            style: TextStyle(color: accent, fontSize: 28, fontWeight: FontWeight.w900, letterSpacing: -0.5),
            textAlign: TextAlign.center),
          const SizedBox(height: 18),
          Text(body,
            style: TextStyle(color: _text.withValues(alpha: 0.85), fontSize: 14.5, height: 1.7, fontWeight: FontWeight.w500),
            textAlign: TextAlign.center),
        ],
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// v7 2026-05-18: AuraView 자체 3D BEV (Three.js + 폰 카메라 getUserMedia)
//   - 페이지: https://auraview.allthatai.kr/bev3d/
//   - WebView 안에서 후면 카메라(getUserMedia) 호출 → PiP + Three.js 렌더
//   - /fusion/intersection/1007 폴링으로 우측 메트릭 패널 갱신
// ═══════════════════════════════════════════════════════════════
class AuraView3DBevScreen extends StatefulWidget {
  const AuraView3DBevScreen({super.key});
  @override
  State<AuraView3DBevScreen> createState() => _AuraView3DBevScreenState();
}

class _AuraView3DBevScreenState extends State<AuraView3DBevScreen> {
  late final WebViewController _wv;
  int _progress = 0;
  bool _loaded = false;
  static const _url = 'https://auraview.allthatai.kr/bev3d/';

  @override
  void initState() {
    super.initState();
    final ctrl = WebViewController();
    ctrl
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(_bg)
      ..setNavigationDelegate(NavigationDelegate(
        onProgress: (p) => setState(() => _progress = p),
        onPageFinished: (_) => setState(() => _loaded = true),
      ));
    // Android: getUserMedia 자동 허용 (앱 자체 카메라 권한은 네이티브 단에서 이미 받음)
    final platform = ctrl.platform;
    if (platform is AndroidWebViewController) {
      AndroidWebViewController.enableDebugging(false);
      platform.setMediaPlaybackRequiresUserGesture(false);
      platform.setOnPlatformPermissionRequest((req) => req.grant());
    }
    ctrl.loadRequest(Uri.parse(_url));
    _wv = ctrl;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      appBar: AppBar(
        backgroundColor: _surface,
        elevation: 0,
        title: const Row(children: [
          Icon(Icons.view_in_ar, color: _accent2, size: 20),
          SizedBox(width: 8),
          Text('AuraView 3D BEV',
              style: TextStyle(color: _text, fontSize: 16, fontWeight: FontWeight.w900, letterSpacing: 0.5)),
        ]),
        actions: [
          IconButton(
            icon: Icon(Icons.refresh, color: _muted),
            tooltip: '새로고침',
            onPressed: () => _wv.reload(),
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(2),
          child: !_loaded ? LinearProgressIndicator(
            value: _progress / 100,
            backgroundColor: _surface,
            valueColor: AlwaysStoppedAnimation(_accent2),
            minHeight: 2,
          ) : const SizedBox(height: 2),
        ),
      ),
      body: Stack(children: [
        WebViewWidget(controller: _wv),
        if (!_loaded)
          Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                CircularProgressIndicator(color: _accent2, strokeWidth: 2.5),
                const SizedBox(height: 18),
                Text('AuraView 실시간 3D BEV 로딩…',
                    style: TextStyle(color: _muted, fontSize: 13, fontWeight: FontWeight.w600)),
                const SizedBox(height: 4),
                Text('후면 카메라 + Three.js 3D 위험도 시각화',
                    style: TextStyle(color: _muted.withValues(alpha: 0.6), fontSize: 11)),
              ],
            ),
          ),
      ]),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// v7.4 2026-05-18: 심사위원 가산점 모드 (★)
//   - 4탭: ⭐ 가산점 25점 · 🔒 PII · 🛡️ 안전구역 · 🎬 스토리
//   - 각 탭은 WebView 로 https://auraview.allthatai.kr/{path}/ 로드
// ═══════════════════════════════════════════════════════════════
class _JudgeModeScreen extends StatefulWidget {
  const _JudgeModeScreen();
  @override
  State<_JudgeModeScreen> createState() => _JudgeModeScreenState();
}

class _JudgeModeScreenState extends State<_JudgeModeScreen> {
  int _tab = 0;
  late WebViewController _wv;
  int _progress = 0;
  bool _loaded = false;

  static const _tabs = <Map<String, String>>[
    {'name': '가산점',  'icon': '★', 'url': 'https://auraview.allthatai.kr/scorecard/'},
    {'name': '정책',    'icon': '⚖', 'url': 'https://auraview.allthatai.kr/policy/'},
    {'name': 'PII',     'icon': '🔒', 'url': 'https://auraview.allthatai.kr/privacy/'},
    {'name': '안전구역','icon': '🛡', 'url': 'https://auraview.allthatai.kr/safezone/'},
    {'name': '스토리',  'icon': '📖', 'url': 'https://auraview.allthatai.kr/story/'},
  ];

  @override
  void initState() {
    super.initState();
    final ctrl = WebViewController();
    ctrl
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(_bg)
      ..setNavigationDelegate(NavigationDelegate(
        onProgress: (p) => setState(() => _progress = p),
        onPageStarted: (_) => setState(() { _loaded = false; _progress = 0; }),
        onPageFinished: (_) => setState(() => _loaded = true),
      ));
    final platform = ctrl.platform;
    if (platform is AndroidWebViewController) {
      platform.setMediaPlaybackRequiresUserGesture(false);
      platform.setOnPlatformPermissionRequest((req) => req.grant());
    }
    ctrl.loadRequest(Uri.parse(_tabs[0]['url']!));
    _wv = ctrl;
  }

  void _select(int i) {
    if (i == _tab) return;
    setState(() { _tab = i; _loaded = false; });
    _wv.loadRequest(Uri.parse(_tabs[i]['url']!));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      appBar: AppBar(
        backgroundColor: _surface,
        elevation: 0,
        title: Row(children: [
          Container(width: 8, height: 8, decoration: BoxDecoration(
            color: _safe, shape: BoxShape.circle,
            boxShadow: [BoxShadow(color: _safe, blurRadius: 6)],
          )),
          const SizedBox(width: 8),
          const Text('심사위원 모드 · 가산점 25점',
              style: TextStyle(color: _text, fontSize: 15, fontWeight: FontWeight.w900, letterSpacing: 0.5)),
        ]),
        actions: [
          IconButton(icon: Icon(Icons.refresh, color: _muted), onPressed: () => _wv.reload()),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(2),
          child: !_loaded ? LinearProgressIndicator(
            value: _progress / 100, backgroundColor: _surface,
            valueColor: AlwaysStoppedAnimation(_safe), minHeight: 2,
          ) : const SizedBox(height: 2),
        ),
      ),
      body: Column(children: [
        // Tabs
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
          decoration: BoxDecoration(
            color: _surface,
            border: Border(bottom: BorderSide(color: _surface2, width: 0.5)),
          ),
          child: Row(
            children: List.generate(_tabs.length, (i) {
              final t = _tabs[i]; final on = i == _tab;
              return Expanded(child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 3),
                child: GestureDetector(
                  onTap: () => _select(i),
                  behavior: HitTestBehavior.opaque,
                  child: Container(
                    padding: const EdgeInsets.symmetric(vertical: 9),
                    decoration: BoxDecoration(
                      color: on ? _safe.withValues(alpha: 0.15) : Colors.transparent,
                      border: Border.all(
                        color: on ? _safe.withValues(alpha: 0.6) : _surface2,
                        width: on ? 1.2 : 0.7),
                      borderRadius: BorderRadius.circular(9),
                    ),
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                      Text(t['icon']!, style: const TextStyle(fontSize: 16, height: 1)),
                      const SizedBox(height: 3),
                      Text(t['name']!,
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          color: on ? _safe : _muted,
                          fontSize: 10.5, fontWeight: FontWeight.w800, letterSpacing: 0.2),
                      ),
                    ]),
                  ),
                ),
              ));
            }),
          ),
        ),
        Expanded(child: Stack(children: [
          WebViewWidget(controller: _wv),
          if (!_loaded)
            Center(child: Column(mainAxisSize: MainAxisSize.min, children: [
              CircularProgressIndicator(color: _safe, strokeWidth: 2.5),
              const SizedBox(height: 16),
              Text('${_tabs[_tab]['name']} 로딩…',
                style: TextStyle(color: _muted, fontSize: 13, fontWeight: FontWeight.w600)),
              const SizedBox(height: 4),
              Text(_tabs[_tab]['url']!,
                style: TextStyle(color: _muted.withValues(alpha: 0.5), fontSize: 10)),
            ])),
        ])),
      ]),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// v10 2026-05-19: 제로베이스 재설계
//   사용자 지적 "실시간 카메라에 보이는걸 화면에 BEV로 표현해야",
//                "차선 중앙이 아니면 저게 성립될리가 없는데",
//                "테슬라 컴퓨터 모니터랑 디자인 패턴 등 다 다시해라",
//                "지금 모든 디자인 제로베이스에서 출발"
//   결정:
//     • 차선/도로/주행가능구역 그림 전부 폐기 (실 데이터 없으면 그리지 X)
//     • Tesla 컴퓨터 모니터 split: 상단 카메라(실보임) + 하단 BEV(검출 객체)
//     • BEV 는 거리 grid 와 검출 silhouette 만 — 합성 도로 X
// ═══════════════════════════════════════════════════════════════
class _CameraBevSplit extends StatefulWidget {
  final CameraController? camera;
  final List<Map<String, dynamic>> detections;
  final List<Map<String, dynamic>> rawDetections;   // v12.4
  final int imgW;
  final int imgH;
  final double fps;   // v12.12: BEV FPS
  // v12.13: 서버 헬시 + 스키마 + 마지막 성공
  final int serverLiveSources;
  final int serverTotalSources;
  final String serverSchema;
  final DateTime? lastFusionOk;
  const _CameraBevSplit({
    required this.camera, required this.detections,
    this.rawDetections = const [],
    required this.imgW, required this.imgH,
    this.fps = 0,
    this.serverLiveSources = 0,
    this.serverTotalSources = 0,
    this.serverSchema = '',
    this.lastFusionOk,
  });
  @override
  State<_CameraBevSplit> createState() => _CameraBevSplitState();
}

class _CameraBevSplitState extends State<_CameraBevSplit> with SingleTickerProviderStateMixin {
  late final Ticker _ticker;
  final List<_BevObj2> _objs = [];
  double _t = 0;
  double _lastMs = 0;

  @override
  void initState() {
    super.initState();
    _ticker = createTicker((d) {
      final ms = d.inMicroseconds / 1000.0;
      final dt = _lastMs == 0 ? 0.016 : ((ms - _lastMs) / 1000.0).clamp(0.0, 0.05);
      _lastMs = ms;
      _t = ms / 1000.0;
      bool dirty = false;
      for (int i = _objs.length - 1; i >= 0; i--) {
        final o = _objs[i];
        final ox = o.x, oy = o.y;
        o.x = o.x * (1 - dt * 5.5) + o.tx * dt * 5.5;
        o.y = o.y * (1 - dt * 5.5) + o.ty * dt * 5.5;
        if ((o.x - ox).abs() > 0.0005 || (o.y - oy).abs() > 0.0005) dirty = true;
        if (_t - o.lastSeen > 1.8) {
          o.alpha = (o.alpha * (1 - dt * 2.5)).clamp(0.0, 1.0);
          if (o.alpha < 0.05) { _objs.removeAt(i); dirty = true; continue; }
        } else {
          o.alpha = (o.alpha + dt * 4.0).clamp(0.0, 1.0);
        }
      }
      if (mounted && (dirty || _objs.isNotEmpty)) setState(() {});
    });
    _ticker.start();
    _sync();
  }

  @override
  void didUpdateWidget(covariant _CameraBevSplit old) {
    super.didUpdateWidget(old);
    if (!identical(old.detections, widget.detections)) _sync();
  }

  void _sync() {
    final ds = widget.detections;
    final iw = widget.imgW.toDouble(), ih = widget.imgH.toDouble();
    final now = _t;
    final used = <int>{};
    for (final d in ds) {
      final box = (d['box'] as List).map((e) => (e as num).toDouble()).toList();
      final bx = box[0] + box[2] / 2, by = box[1] + box[3];
      final ny = (by / ih).clamp(0.0, 1.0);
      final nx = ((bx / iw) - 0.5) * 2.0;
      final forward = math.pow(1.0 - ny, 1.8).toDouble();
      final cls = d['cls']?.toString() ?? 'car';
      double bestD = 0.30; int bestI = -1;
      for (int i = 0; i < _objs.length; i++) {
        if (used.contains(i)) continue;
        final o = _objs[i]; if (o.cls != cls) continue;
        final dd = math.sqrt(math.pow(o.tx - nx, 2) + math.pow(o.ty - forward, 2));
        if (dd < bestD) { bestD = dd; bestI = i; }
      }
      if (bestI >= 0) {
        final o = _objs[bestI];
        o.tx = nx; o.ty = forward;
        o.conf = (d['score'] as num?)?.toDouble() ?? 0.6;
        o.lastSeen = now; used.add(bestI);
      } else {
        _objs.add(_BevObj2(cls: cls, x: nx, y: forward, tx: nx, ty: forward,
          conf: (d['score'] as num?)?.toDouble() ?? 0.6,
          phase: math.Random().nextDouble() * 6.28,
          lastSeen: now, alpha: 0.0));
      }
    }
  }

  @override
  void dispose() { _ticker.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    int pc = 0, vc = 0;
    for (final o in _objs) { if (o.cls == 'person') pc++; else vc++; }

    return Column(children: [
      // ── 상단 절반: 카메라 + ML Kit 박스 (Tesla 풍 카드)
      Expanded(flex: 5, child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        decoration: BoxDecoration(
          color: Colors.black,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: Colors.white.withValues(alpha: 0.08), width: 0.8),
          boxShadow: [
            BoxShadow(color: Colors.black.withValues(alpha: 0.5),
              blurRadius: 18, offset: const Offset(0, 6)),
          ],
        ),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(19),
          child: Stack(fit: StackFit.expand, children: [
            // 카메라
            if (widget.camera != null && widget.camera!.value.isInitialized)
              _FullCameraPreview(controller: widget.camera!)
            else
              Center(child: Column(mainAxisSize: MainAxisSize.min, children: [
                Icon(Icons.no_photography, size: 36, color: _muted),
                const SizedBox(height: 8),
                Text('카메라 권한 필요',
                  style: TextStyle(color: _muted, fontSize: 12, fontWeight: FontWeight.w800)),
              ])),
            // v12.4: ML Kit raw 박스 (filter 전/후 다른 색)
            if (widget.camera != null && widget.camera!.value.isInitialized)
              IgnorePointer(child: CustomPaint(
                size: Size.infinite,
                painter: _CamBoxPainter(
                  detections: widget.detections,
                  rawDetections: widget.rawDetections,
                  imgW: widget.imgW, imgH: widget.imgH,
                ),
              )),
            // 좌상단 Tesla 라벨
            Positioned(left: 12, top: 10, child: _TeslaLabel(
              icon: Icons.videocam_rounded, label: 'CAM · LIVE', color: _danger)),
            // 우상단 검출 카운트 + AI 상태
            Positioned(right: 12, top: 10, child: _TeslaLabel(
              icon: Icons.center_focus_strong_rounded,
              label: '검출 ${widget.detections.length}',
              color: widget.detections.isNotEmpty ? _accent : Colors.white.withValues(alpha: 0.55))),
          ]),
        ),
      )),
      // ── 하단 절반: 순수 합성 3D BEV
      Expanded(flex: 5, child: Container(
        decoration: BoxDecoration(
          gradient: const RadialGradient(
            center: Alignment(0, 0.9), radius: 1.2,
            colors: [Color(0xFF0A1322), Color(0xFF02050A)],
          ),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: Colors.white.withValues(alpha: 0.08), width: 0.8),
          boxShadow: [
            BoxShadow(color: Colors.black.withValues(alpha: 0.5),
              blurRadius: 18, offset: const Offset(0, 6)),
          ],
        ),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(19),
          child: Stack(fit: StackFit.expand, children: [
            RepaintBoundary(child: CustomPaint(
              size: Size.infinite,
              painter: _CleanBevPainter(objs: _objs, t: _t),
            )),
            Positioned(left: 12, top: 10, child: _TeslaLabel(
              icon: Icons.view_in_ar_rounded,
              label: 'BEV · ${widget.fps > 0.5 ? widget.fps.toStringAsFixed(1) : "0"} FPS',
              color: _safe)),
            Positioned(right: 12, top: 10, child: _TeslaLabel(
              icon: Icons.tag_faces_rounded, label: '$pc 보행 · $vc 차량',
              color: (pc + vc) > 0 ? _accent : Colors.white.withValues(alpha: 0.55))),
            // v12.13: 서버 헬시 배지 (좌하단) — N/21 live + 스키마 v
            if (widget.serverTotalSources > 0)
              Positioned(left: 12, bottom: 10, child: _TeslaLabel(
                icon: Icons.lan_rounded,
                label: '${widget.serverLiveSources}/${widget.serverTotalSources}'
                       '${widget.serverSchema.contains("v7") ? " · v7" : (widget.serverSchema.isNotEmpty ? " · ${widget.serverSchema.split("-").first.replaceAll("fusion.", "")}" : "")}',
                color: widget.serverLiveSources > 0
                  ? _safe
                  : Colors.white.withValues(alpha: 0.45))),
            // v12.13: 마지막 fetch (우하단)
            if (widget.lastFusionOk != null)
              Positioned(right: 12, bottom: 10, child: _TeslaLabel(
                icon: Icons.sync_rounded,
                label: '${DateTime.now().difference(widget.lastFusionOk!).inSeconds}s',
                color: DateTime.now().difference(widget.lastFusionOk!).inSeconds < 10
                  ? _safe : _warn)),
          ]),
        ),
      )),
    ]);
  }
}

// v12.4: 카메라 위 ML Kit 박스 + raw 박스 디버그 오버레이
class _CamBoxPainter extends CustomPainter {
  final List<Map<String, dynamic>> detections;
  final List<Map<String, dynamic>> rawDetections;
  final int imgW, imgH;
  _CamBoxPainter({required this.detections, this.rawDetections = const [],
    required this.imgW, required this.imgH});
  @override
  void paint(Canvas canvas, Size size) {
    // 카메라 영상이 FittedBox.cover로 그려졌으므로 imgW/imgH → 화면 비율 매핑
    // (이 페인터는 카메라 위에 깔리는 overlay 라 같은 cover 매핑 필요)
    final sensorAR = imgW / imgH;
    final containerAR = size.width / size.height;
    double scale, dx = 0, dy = 0;
    if (containerAR > sensorAR) {
      // 컨테이너가 더 가로 → 가로 맞춤
      scale = size.width / imgW;
      dy = (size.height - imgH * scale) / 2;
    } else {
      scale = size.height / imgH;
      dx = (size.width - imgW * scale) / 2;
    }

    // 1) raw 박스 모두 그리기 (filter 거부된 것은 옅게)
    for (final d in rawDetections) {
      final box = (d['box'] as List).map((e) => (e as num).toDouble()).toList();
      final kept = d['kept'] as bool? ?? false;
      final labels = d['labels']?.toString() ?? '';
      final rej = d['rej']?.toString();
      final col = kept ? const Color(0xFF00C8FF) : const Color(0xFFFFB020);
      final r = Rect.fromLTWH(
        dx + box[0] * scale, dy + box[1] * scale,
        box[2] * scale, box[3] * scale);
      canvas.drawRRect(RRect.fromRectAndRadius(r, const Radius.circular(3)),
        Paint()..style = PaintingStyle.stroke..strokeWidth = kept ? 2.4 : 1.2
          ..color = col.withValues(alpha: kept ? 0.95 : 0.5));
      // 라벨 (cls 라벨 + 거부 사유 or kept 표시)
      final tag = kept ? '✓ $labels' : '✗ $rej · $labels';
      final tp = TextPainter(
        text: TextSpan(text: tag, style: TextStyle(
          color: kept ? Colors.white : const Color(0xFFFFCB6B),
          fontSize: 9.5, fontWeight: FontWeight.w800,
          backgroundColor: Colors.black.withValues(alpha: 0.65))),
        textDirection: TextDirection.ltr,
        maxLines: 1, ellipsis: '…',
      )..layout(maxWidth: r.width * 1.5);
      tp.paint(canvas, Offset(r.left, r.top - tp.height - 1));
    }
  }
  @override
  bool shouldRepaint(covariant _CamBoxPainter old) =>
      old.detections != detections || old.rawDetections != rawDetections;
}

// 깨끗한 BEV 페인터 (도로 X, 거리 grid + ego + 검출 silhouette 만)
class _CleanBevPainter extends CustomPainter {
  final List<_BevObj2> objs;
  final double t;
  _CleanBevPainter({required this.objs, required this.t});

  Offset _project(double x, double y, Size size) {
    final w = size.width, h = size.height;
    final cy = h * (0.88 - y * 0.78);
    final lateralScale = 0.52 + (1 - y) * 0.35;
    final cx = w / 2 + x * w * lateralScale;
    return Offset(cx, cy);
  }

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width, h = size.height;

    // ── 가로 거리 grid (cyan 옅음)
    final gp = Paint()..strokeWidth = 1;
    final labels = [
      [0.10, '5m'], [0.30, '15m'], [0.55, '30m'], [0.80, '50m+'],
    ];
    for (final entry in labels) {
      final yNorm = entry[0] as double;
      final txt = entry[1] as String;
      final yPx = h * (0.88 - yNorm * 0.78);
      final scale = 0.52 + (1 - yNorm) * 0.35;
      gp.color = const Color(0xFF00C8FF).withValues(alpha: 0.10 + (1 - yNorm) * 0.10);
      canvas.drawLine(Offset(w / 2 - w * scale * 0.92, yPx),
        Offset(w / 2 + w * scale * 0.92, yPx), gp);
      // 거리 텍스트
      final tp = TextPainter(
        text: TextSpan(text: txt, style: TextStyle(
          color: const Color(0xFF5A7A9A).withValues(alpha: 0.75), fontSize: 9,
          fontWeight: FontWeight.w800)),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(w / 2 - w * scale * 0.92 - tp.width - 4, yPx - tp.height / 2));
    }

    // ── Ego (cyan top-down 차량 silhouette)
    final pEgo = _project(0, 0.0, size);
    _drawTopDownCarLocal(canvas, pEgo, 1.0, const Color(0xFF00C8FF), 1.0);
    final tpEgo = TextPainter(
      text: TextSpan(text: 'EGO', style: TextStyle(
        color: const Color(0xFF00C8FF), fontSize: 9,
        fontWeight: FontWeight.w900, letterSpacing: 1.5)),
      textDirection: TextDirection.ltr,
    )..layout();
    tpEgo.paint(canvas, Offset(pEgo.dx - tpEgo.width / 2, pEgo.dy + 30));

    // ── 검출 객체
    final sorted = [...objs];
    sorted.sort((a, b) => b.y.compareTo(a.y));
    for (final o in sorted) {
      final p = _project(o.x.clamp(-0.92, 0.92), o.y.clamp(0.0, 0.95), size);
      final scale = (1.0 - o.y * 0.70).clamp(0.30, 1.0);
      // v10.1: Tesla AI Day 식 3D voxel 클러스터 (검출 객체 위치에 cube column)
      _drawVoxelCluster(canvas, p, scale, o.cls, o.alpha);
      if (o.cls == 'person') {
        _drawPersonLocal(canvas, p, scale, o.alpha, o.phase);
      } else {
        _drawTopDownCarLocal(canvas, p, scale, const Color(0xFFA095FF), o.alpha);
      }
      final distM = 1.5 + 33.5 * o.y;
      final tp = TextPainter(
        text: TextSpan(text: '${o.cls == "person" ? "👤" : "🚗"} ${distM.toStringAsFixed(1)}m',
          style: TextStyle(color: Colors.white, fontSize: 9, fontWeight: FontWeight.w900,
            backgroundColor: (o.cls == 'person' ? const Color(0xFFFF4040) : const Color(0xFFA095FF))
              .withValues(alpha: 0.85 * o.alpha))),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(p.dx - tp.width / 2, p.dy - 22 * scale - tp.height));
    }
  }

  // v10.1: Tesla AI Day 식 voxel 클러스터 — 검출 객체 자리에 3D 큐브 컬럼
  //   사람: 좁고 높은 컬럼 (3x6 큐브 ≈ 사람 윤곽 voxelize)
  //   차량: 넓고 낮은 큐브 클러스터 (5x3 ≈ 차량 ground footprint voxelize)
  void _drawVoxelCluster(Canvas canvas, Offset c, double scale, String cls, double alpha) {
    final isPed = cls == 'person';
    final col = isPed ? const Color(0xFFFF4040) : const Color(0xFFA095FF);
    final cubeSize = (isPed ? 3.5 : 4.2) * scale;
    final cols = isPed ? 3 : 5;
    final rows = isPed ? 5 : 3;
    // 컬럼별로 약간씩 offset → voxelize 느낌
    for (int r = 0; r < rows; r++) {
      for (int co = 0; co < cols; co++) {
        // 외곽 cell skip (사람=중앙 columns 만, 차량=직사각)
        if (isPed) {
          // 사람: 정 중앙 1열은 머리(상단) + 몸통(중) + 다리 끝(아래) — 셀 패턴
          if (r == 0 && co != 1) continue;  // 머리 1개만
          if (r >= 3 && (co == 0 || co == 2)) continue;  // 다리는 좌우 2 column
        }
        final dx = (co - (cols - 1) / 2) * cubeSize * 1.05;
        final dy = (r - (rows - 1) / 2) * cubeSize * 0.95 - (isPed ? cubeSize * 1.0 : cubeSize * 0.5);
        final pos = c.translate(dx, dy);
        // 큐브 본체
        final cubeAlpha = alpha * (0.45 + 0.55 * (1 - r / rows));   // 위쪽 cube 더 흐림
        canvas.drawRect(
          Rect.fromCenter(center: pos, width: cubeSize, height: cubeSize),
          Paint()..color = col.withValues(alpha: cubeAlpha));
        // 위쪽 하이라이트 (입체감)
        canvas.drawRect(
          Rect.fromLTWH(pos.dx - cubeSize / 2, pos.dy - cubeSize / 2,
            cubeSize, cubeSize * 0.30),
          Paint()..color = col.withValues(alpha: cubeAlpha * 0.55));
        // 외곽선
        canvas.drawRect(
          Rect.fromCenter(center: pos, width: cubeSize, height: cubeSize),
          Paint()..style = PaintingStyle.stroke..strokeWidth = 0.6
            ..color = Colors.white.withValues(alpha: cubeAlpha * 0.5));
      }
    }
  }

  // 로컬 top-down 차량 (외부 _drawTeslaCar 와 동일 로직 축약 인라인)
  void _drawTopDownCarLocal(Canvas canvas, Offset c, double scale, Color col, double alpha) {
    final w = 30.0 * scale, h = 14.0 * scale;
    final colDark = HSLColor.fromColor(col).withLightness(
      (HSLColor.fromColor(col).lightness - 0.20).clamp(0.10, 0.90)).toColor();
    canvas.drawRRect(RRect.fromRectAndRadius(
      Rect.fromCenter(center: c.translate(0, h * 0.55), width: w * 1.10, height: h * 0.5),
      const Radius.circular(4)),
      Paint()..color = Colors.black.withValues(alpha: 0.45 * alpha)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 5));
    canvas.drawCircle(c.translate(0, h * 0.35), w * 0.55,
      Paint()..color = col.withValues(alpha: 0.25 * alpha));
    final bodyRect = Rect.fromCenter(center: c, width: w, height: h);
    final bodyRRect = RRect.fromRectAndCorners(bodyRect,
      topLeft: Radius.circular(h * 0.30), topRight: Radius.circular(h * 0.30),
      bottomLeft: Radius.circular(h * 0.45), bottomRight: Radius.circular(h * 0.45));
    canvas.drawRRect(bodyRRect, Paint()..shader = LinearGradient(
      begin: Alignment.topCenter, end: Alignment.bottomCenter,
      colors: [col.withValues(alpha: alpha), colDark.withValues(alpha: alpha)],
    ).createShader(bodyRect));
    // 바퀴
    final wp = Paint()..color = const Color(0xFF0A0E15).withValues(alpha: alpha);
    for (final dx in [-w * 0.42, w * 0.42]) {
      for (final dy in [-h * 0.28, h * 0.28]) {
        canvas.drawRRect(RRect.fromRectAndRadius(
          Rect.fromCenter(center: c.translate(dx, dy), width: w * 0.07, height: h * 0.45),
          Radius.circular(h * 0.05)), wp);
      }
    }
    // 창문
    canvas.drawPath(Path()
      ..moveTo(c.dx - w * 0.32, c.dy - h * 0.08)
      ..lineTo(c.dx - w * 0.26, c.dy - h * 0.30)
      ..lineTo(c.dx + w * 0.26, c.dy - h * 0.30)
      ..lineTo(c.dx + w * 0.32, c.dy - h * 0.08)..close(),
      Paint()..color = const Color(0xFF06121E).withValues(alpha: 0.85 * alpha));
    // 헤드라이트
    final hl = Paint()..color = const Color(0xFFFFD93D).withValues(alpha: 0.9 * alpha);
    canvas.drawCircle(Offset(c.dx - w * 0.36, c.dy - h * 0.42), 1.5 * scale + 0.6, hl);
    canvas.drawCircle(Offset(c.dx + w * 0.36, c.dy - h * 0.42), 1.5 * scale + 0.6, hl);
    canvas.drawRRect(bodyRRect,
      Paint()..style = PaintingStyle.stroke..strokeWidth = 1.2
        ..color = col.withValues(alpha: alpha));
  }

  // 로컬 사람 silhouette (위에 _drawPersonSilhouette 와 동일 축약)
  void _drawPersonLocal(Canvas canvas, Offset p, double scale, double alpha, double phase) {
    final headR = 6.0 * scale, bodyH = 26.0 * scale, bodyW = 12.0 * scale, legH = 14.0 * scale;
    final col = const Color(0xFFFF4040);
    final pulse = 1.0 + 0.35 * math.sin(t * 3.2 + phase);
    canvas.drawCircle(p.translate(0, headR * 0.5), (headR + bodyW * 0.7) * pulse,
      Paint()..style = PaintingStyle.stroke..strokeWidth = 1.5
        ..color = col.withValues(alpha: (0.55 / pulse) * alpha));
    canvas.drawOval(Rect.fromCenter(
      center: p.translate(0, bodyH * 0.4), width: bodyW * 1.6, height: bodyW * 0.7),
      Paint()..color = Colors.black.withValues(alpha: 0.5 * alpha)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 4));
    final legP = Paint()..color = col.withValues(alpha: 0.85 * alpha)
      ..strokeCap = StrokeCap.round..strokeWidth = bodyW * 0.30;
    canvas.drawLine(Offset(p.dx - bodyW * 0.20, p.dy + bodyH * 0.10),
      Offset(p.dx - bodyW * 0.20, p.dy + bodyH * 0.10 + legH), legP);
    canvas.drawLine(Offset(p.dx + bodyW * 0.20, p.dy + bodyH * 0.10),
      Offset(p.dx + bodyW * 0.20, p.dy + bodyH * 0.10 + legH), legP);
    final bodyPath = Path()
      ..moveTo(p.dx - bodyW * 0.50, p.dy - bodyH * 0.30)
      ..lineTo(p.dx + bodyW * 0.50, p.dy - bodyH * 0.30)
      ..lineTo(p.dx + bodyW * 0.32, p.dy + bodyH * 0.20)
      ..lineTo(p.dx - bodyW * 0.32, p.dy + bodyH * 0.20)..close();
    canvas.drawPath(bodyPath, Paint()..shader = LinearGradient(
      begin: Alignment.topCenter, end: Alignment.bottomCenter,
      colors: [col.withValues(alpha: alpha), col.withValues(alpha: 0.75 * alpha)],
    ).createShader(Rect.fromCenter(center: p, width: bodyW, height: bodyH)));
    canvas.drawCircle(Offset(p.dx, p.dy - bodyH * 0.45), headR,
      Paint()..color = col.withValues(alpha: alpha));
  }

  @override
  bool shouldRepaint(covariant _CleanBevPainter old) => true;
}

// ═══════════════════════════════════════════════════════════════
// v9.4 2026-05-18: 테슬라 식 합성 3D BEV (CustomPainter)
//   - 카메라 영상은 별도 PiP 로만 표시. BEV 는 검출 결과를 합성 도로 위에 박스로.
//   - 위에서 비스듬히 본 시점 (BEV-ish 3D perspective)
//   - 검출 사이 1.5s 간격 → smooth interpolation (60fps Ticker)
//   - 차량/보행자 색상 구분, 거리 ring, ego 진행 경로 fade
// ═══════════════════════════════════════════════════════════════
class _TeslaBev extends StatefulWidget {
  final List<Map<String, dynamic>> detections;
  final int imgW;
  final int imgH;
  const _TeslaBev({required this.detections, required this.imgW, required this.imgH});
  @override
  State<_TeslaBev> createState() => _TeslaBevState();
}

class _BevObj {
  String cls; double x, y;        // BEV 좌표 (도로 평면, -1..1 lateral, 0..1 forward)
  double tx, ty;                  // target (검출 갱신 시 set, 매 프레임 보간)
  double conf;
  double phase;                   // 펄스용
  _BevObj({required this.cls, required this.x, required this.y, required this.conf, required this.phase})
      : tx = x, ty = y;
}

class _TeslaBevState extends State<_TeslaBev> with SingleTickerProviderStateMixin {
  late final Ticker _ticker;
  final List<_BevObj> _objs = [];
  double _t = 0;
  double _lastFrameMs = 0;

  @override
  void initState() {
    super.initState();
    _ticker = createTicker((d) {
      final ms = d.inMicroseconds / 1000.0;
      final dt = _lastFrameMs == 0 ? 0.016 : ((ms - _lastFrameMs) / 1000.0).clamp(0.0, 0.05);
      _lastFrameMs = ms;
      _t = ms / 1000.0;
      // 보간
      for (final o in _objs) {
        o.x = o.x * (1 - dt * 6.0) + o.tx * dt * 6.0;
        o.y = o.y * (1 - dt * 6.0) + o.ty * dt * 6.0;
      }
      if (mounted) setState(() {});
    });
    _ticker.start();
    _syncFromDetections();
  }

  @override
  void didUpdateWidget(covariant _TeslaBev old) {
    super.didUpdateWidget(old);
    if (!identical(old.detections, widget.detections)) {
      _syncFromDetections();
    }
  }

  // 검출 → BEV 좌표로 매핑 (bbox bottom_y → forward dist, bottom_x → lateral)
  void _syncFromDetections() {
    final ds = widget.detections; if (ds.isEmpty) {
      // 검출 없으면 점진 fade-out (안 그리면 자동 사라짐 — 그냥 비움)
      _objs.clear();
      return;
    }
    final iw = widget.imgW.toDouble(), ih = widget.imgH.toDouble();
    final mapped = <_BevObj>[];
    for (final d in ds) {
      final box = (d['box'] as List).map((e) => (e as num).toDouble()).toList();
      final bx = box[0] + box[2] / 2, by = box[1] + box[3];
      final ny = (by / ih).clamp(0.0, 1.0);     // 1 = 카메라 아래(가까움), 0 = 위(멀음)
      final nx = ((bx / iw) - 0.5) * 2.0;       // -1..1 lateral
      // forward: 0(near)..1(far). 비선형으로 원근감
      final forward = 1.0 - math.pow(ny, 1.6).toDouble();
      mapped.add(_BevObj(
        cls: d['cls']?.toString() ?? 'car',
        x: nx, y: forward, conf: (d['score'] as num?)?.toDouble() ?? 0.6,
        phase: (math.Random().nextDouble()) * 6.28,
      ));
    }
    // 기존 트랙과 매칭 (간단: 가장 가까운 거 매치)
    final newList = <_BevObj>[];
    final used = <int>{};
    for (final m in mapped) {
      double bestD = 0.25; int bestI = -1;
      for (int i = 0; i < _objs.length; i++) {
        if (used.contains(i)) continue;
        final o = _objs[i];
        if (o.cls != m.cls) continue;
        final d = math.sqrt(math.pow(o.x - m.x, 2) + math.pow(o.y - m.y, 2));
        if (d < bestD) { bestD = d; bestI = i; }
      }
      if (bestI >= 0) {
        final o = _objs[bestI];
        o.tx = m.x; o.ty = m.y; o.conf = m.conf;
        newList.add(o); used.add(bestI);
      } else {
        newList.add(m);
      }
    }
    _objs..clear()..addAll(newList);
  }

  @override
  void dispose() { _ticker.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          begin: Alignment.topCenter, end: Alignment.bottomCenter,
          colors: [Color(0xFF0A1422), Color(0xFF03070D)],
        ),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: _accent.withValues(alpha: 0.20), width: 0.8),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(15),
        child: Stack(fit: StackFit.expand, children: [
          // 1) Tesla 식 합성 BEV
          RepaintBoundary(child: CustomPaint(
            painter: _TeslaBevPainter(objs: _objs, t: _t),
            size: Size.infinite,
          )),
          // 2) 좌상단 LIVE 라벨
          Positioned(left: 10, top: 8, child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
            decoration: BoxDecoration(
              color: const Color(0xCC0D1520),
              borderRadius: BorderRadius.circular(99),
              border: Border.all(color: _safe.withValues(alpha: 0.40), width: 0.8),
            ),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Container(width: 7, height: 7, decoration: BoxDecoration(
                color: _safe, shape: BoxShape.circle,
                boxShadow: [BoxShadow(color: _safe, blurRadius: 6)],
              )),
              const SizedBox(width: 6),
              Text('LIVE BEV', style: TextStyle(color: _safe, fontSize: 10,
                fontWeight: FontWeight.w900, letterSpacing: 1.2)),
              const SizedBox(width: 8),
              Text('· ${_objs.length} 검출',
                style: TextStyle(color: _muted, fontSize: 10, fontWeight: FontWeight.w700)),
            ]),
          )),
        ]),
      ),
    );
  }
}

class _TeslaBevPainter extends CustomPainter {
  final List<_BevObj> objs;
  final double t;
  _TeslaBevPainter({required this.objs, required this.t});

  // 정규화 BEV (x: -1..1 lateral, y: 0..1 forward) → 화면 좌표 (3D perspective)
  Offset _project(double x, double y, Size size) {
    final w = size.width, h = size.height;
    // forward y → 화면 y (위쪽이 멀음). 원근: y=0 가까이(아래) lateral 폭 = w*0.85, y=1 멀리(위) = w*0.18
    final cy = h * (0.92 - y * 0.78);
    final lateralScale = 0.5 + (1 - y) * 0.35;  // 가까울수록 lateral 폭 넓음
    final cx = w / 2 + x * w * lateralScale;
    return Offset(cx, cy);
  }

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width, h = size.height;

    // 1) 도로 (사다리꼴 그라디언트)
    final road = Path()
      ..moveTo(w * 0.50 - w * 0.09, h * 0.14)
      ..lineTo(w * 0.50 + w * 0.09, h * 0.14)
      ..lineTo(w * 0.50 + w * 0.42, h * 0.95)
      ..lineTo(w * 0.50 - w * 0.42, h * 0.95)
      ..close();
    final roadPaint = Paint()
      ..shader = const LinearGradient(
        begin: Alignment.topCenter, end: Alignment.bottomCenter,
        colors: [Color(0xFF111B2C), Color(0xFF1A2740)],
      ).createShader(Rect.fromLTWH(0, 0, w, h));
    canvas.drawPath(road, roadPaint);

    // 2) 가운데 노란 점선
    final centerLine = Paint()..color = const Color(0xFFFFD93D)..strokeWidth = 3..strokeCap = StrokeCap.round;
    for (int i = 0; i < 18; i++) {
      final y0 = 0.14 + i * 0.046;
      final y1 = y0 + 0.022;
      if (y1 > 0.95) break;
      final p0 = Offset(w / 2, h * y0);
      final p1 = Offset(w / 2, h * y1);
      // 거리 따라 fade (가까울수록 진함)
      centerLine.color = const Color(0xFFFFD93D).withValues(alpha: 0.30 + (y0 - 0.14) * 0.85);
      canvas.drawLine(p0, p1, centerLine);
    }

    // 3) 좌우 차선 라인 (얇은 흰)
    final sideLine = Paint()..color = Colors.white.withValues(alpha: 0.18)..strokeWidth = 1.5;
    canvas.drawLine(
      Offset(w * 0.50 - w * 0.09, h * 0.14),
      Offset(w * 0.50 - w * 0.42, h * 0.95),
      sideLine);
    canvas.drawLine(
      Offset(w * 0.50 + w * 0.09, h * 0.14),
      Offset(w * 0.50 + w * 0.42, h * 0.95),
      sideLine);

    // 4) ego 진행 경로 (cyan strip, 펄스 fade)
    final pathPaint = Paint()..strokeCap = StrokeCap.round..strokeWidth = 5;
    for (int i = 0; i < 6; i++) {
      final y0 = 0.85 - i * 0.07;
      final y1 = y0 - 0.035;
      final alpha = 0.55 - i * 0.08 + 0.05 * math.sin(t * 2 + i);
      pathPaint.color = const Color(0xFF00C8FF).withValues(alpha: alpha.clamp(0.0, 0.6));
      canvas.drawLine(Offset(w / 2, h * y0), Offset(w / 2, h * y1), pathPaint);
    }

    // 5) ego 차량 (cyan, 아래 가까이)
    final egoCenter = _project(0, 0.0, size);
    _drawVehicleBlock(canvas, egoCenter, 0.0, 'ego', 1.0, isEgo: true);

    // 6) 검출 객체 (보간된 위치)
    // 가까운 것 먼저 그리도록 정렬
    final sorted = [...objs];
    sorted.sort((a, b) => a.y.compareTo(b.y));
    for (final o in sorted) {
      final p = _project(o.x.clamp(-0.95, 0.95), o.y.clamp(0.0, 0.92), size);
      _drawVehicleBlock(canvas, p, o.y, o.cls, o.conf, phase: o.phase);
    }

    // 7) 거리 ring 가이드 (5m / 15m / 30m at y=0.15, 0.4, 0.7)
    final ringPaint = Paint()..style = PaintingStyle.stroke..strokeWidth = 1
      ..color = Colors.white.withValues(alpha: 0.06);
    for (final yNorm in [0.15, 0.4, 0.7]) {
      final cy = h * (0.92 - yNorm * 0.78);
      canvas.drawCircle(Offset(w / 2, h), w * (0.40 - yNorm * 0.24), ringPaint);
    }
  }

  void _drawVehicleBlock(Canvas canvas, Offset center, double forwardNorm, String cls, double conf,
                         {bool isEgo = false, double phase = 0}) {
    final isPed = cls == 'person';
    final scale = 1.0 - forwardNorm * 0.7;     // 멀수록 작음
    final w = (isPed ? 18.0 : 38.0) * scale;
    final hBox = (isPed ? 30.0 : 22.0) * scale;
    final col = isEgo ? const Color(0xFF00C8FF)
              : isPed ? const Color(0xFFFF4040)
              : const Color(0xFFA095FF);
    // 그림자
    final shadow = Paint()
      ..color = Colors.black.withValues(alpha: 0.5)
      ..maskFilter = MaskFilter.blur(BlurStyle.normal, 4);
    final rect = Rect.fromCenter(center: center.translate(0, 3), width: w, height: hBox * 0.7);
    canvas.drawRRect(RRect.fromRectAndRadius(rect, const Radius.circular(3)), shadow);
    // 바닥 글로우 (밝은 ring)
    final ring = Paint()..color = col.withValues(alpha: 0.30);
    canvas.drawCircle(center.translate(0, hBox * 0.45), w * 0.65, ring);
    // 메인 바디
    final body = Paint()
      ..shader = LinearGradient(
        begin: Alignment.topCenter, end: Alignment.bottomCenter,
        colors: [col.withValues(alpha: 1.0), col.withValues(alpha: 0.75)],
      ).createShader(Rect.fromCenter(center: center, width: w, height: hBox));
    final bodyRect = Rect.fromCenter(center: center, width: w, height: hBox);
    canvas.drawRRect(RRect.fromRectAndRadius(bodyRect, const Radius.circular(4)), body);
    // 외곽선 (밝은 strokes)
    final stroke = Paint()..style = PaintingStyle.stroke..strokeWidth = 1.2..color = col;
    canvas.drawRRect(RRect.fromRectAndRadius(bodyRect, const Radius.circular(4)), stroke);
    // 위험 펄스 (보행자에만)
    if (isPed) {
      final pulse = 1.0 + 0.4 * math.sin(t * 3.5 + phase);
      final pulseP = Paint()..style = PaintingStyle.stroke..strokeWidth = 1.5
        ..color = col.withValues(alpha: 0.55 / pulse);
      canvas.drawCircle(center, w * 1.2 * pulse, pulseP);
    }
    // 라벨 (cls + 거리 추정)
    if (!isEgo) {
      // forward 0..1 → 1.5m ~ 35m
      final distM = 1.5 + (1 - (1 - forwardNorm).clamp(0.0, 1.0)) * 0 + forwardNorm * 35.0;
      // forwardNorm 0=가까움(1.5m), 1=멀음 (35m). 다시 정리:
      // 우리는 _project 에서 y는 forward (0=가까운 카메라 앞, 1=먼). 그래서 거리는 1.5 + 33.5*y
      final dM = 1.5 + 33.5 * forwardNorm;
      final tp = TextPainter(
        text: TextSpan(children: [
          TextSpan(text: isPed ? '👤 ' : '🚗 ',
            style: const TextStyle(fontSize: 11)),
          TextSpan(text: '${dM.toStringAsFixed(1)}m',
            style: TextStyle(fontSize: 10, color: Colors.white, fontWeight: FontWeight.w900,
              backgroundColor: col.withValues(alpha: 0.85))),
        ]),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(center.dx - tp.width / 2, center.dy - hBox * 0.85 - tp.height));
    } else {
      final tp = TextPainter(
        text: TextSpan(text: 'EGO',
          style: TextStyle(color: col, fontSize: 9, fontWeight: FontWeight.w900, letterSpacing: 1.5)),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(center.dx - tp.width / 2, center.dy - hBox * 0.75 - tp.height));
    }
  }

  @override
  bool shouldRepaint(covariant _TeslaBevPainter old) => true;   // ticker 가 매 프레임 호출
}

// ═══════════════════════════════════════════════════════════════
// v9.3 2026-05-18: REC 토글 칩 (헤더에서 작게)
// ═══════════════════════════════════════════════════════════════
class _RecToggleChip extends StatelessWidget {
  final bool on;
  final VoidCallback? onTap;
  const _RecToggleChip({required this.on, this.onTap});
  @override
  Widget build(BuildContext context) {
    final col = on ? _danger : _muted;
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        height: 38,
        padding: const EdgeInsets.symmetric(horizontal: 11),
        decoration: BoxDecoration(
          color: on ? _danger.withValues(alpha: 0.18) : Colors.transparent,
          border: Border.all(color: col.withValues(alpha: 0.55), width: 1.2),
          borderRadius: BorderRadius.circular(10),
          boxShadow: on ? [BoxShadow(color: _danger.withValues(alpha: 0.35), blurRadius: 10)] : null,
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Container(
            width: 9, height: 9, decoration: BoxDecoration(
              color: col, shape: BoxShape.circle,
              boxShadow: on ? [BoxShadow(color: _danger, blurRadius: 6)] : null,
            ),
          ),
          const SizedBox(width: 6),
          Text(on ? 'REC' : 'OFF',
            style: TextStyle(color: col, fontSize: 11,
              fontWeight: FontWeight.w900, letterSpacing: 1.2)),
        ]),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// v9.3 2026-05-18: 메인 라이브 BEV — Flutter 네이티브 perspective transform.
//   실 카메라 프레임을 3D 회전 + perspective → MetroEyes 식 BEV 시점.
//   위에 ML Kit 검출 박스 직접 오버레이 (BEV 좌표계로 매핑).
//   "실제 보이는 화면을 BEV 로 보여달라" 요구 반영.
// ═══════════════════════════════════════════════════════════════
class _LiveBevTilted extends StatelessWidget {
  final CameraController? camera;
  final List<Map<String, dynamic>> detections;
  final int imgW;
  final int imgH;
  const _LiveBevTilted({
    required this.camera,
    required this.detections,
    required this.imgW,
    required this.imgH,
  });

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (ctx, c) {
      final w = c.maxWidth, h = c.maxHeight;
      // BEV perspective transform: 위쪽을 멀리, 아래쪽을 가까이 — 카메라를 위에서 비스듬히 본 효과
      final m = Matrix4.identity()
        ..setEntry(3, 2, 0.0014)        // 원근감
        ..rotateX(-0.62);                // 위쪽이 화면 안쪽으로 (≈ 35.5°)
      return Container(
        decoration: BoxDecoration(
          color: const Color(0xFF050810),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: _accent.withValues(alpha: 0.20), width: 0.8),
        ),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(13),
          child: Stack(fit: StackFit.expand, children: [
            // 1) 카메라 perspective 변환 (실제 보이는 화면을 BEV 시점으로)
            //    SizedBox 크기를 키워서 변환 후에도 캔버스를 가득 채우게.
            if (camera != null && camera!.value.isInitialized)
              Positioned.fill(
                child: OverflowBox(
                  alignment: Alignment.center,
                  minWidth: w * 1.4, maxWidth: w * 1.4,
                  minHeight: h * 1.8, maxHeight: h * 1.8,
                  child: Transform(
                    alignment: Alignment.center,
                    transform: m,
                    child: _FullCameraPreview(controller: camera!),
                  ),
                ),
              )
            else
              Container(color: const Color(0xFF080C14), child: Center(
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  Icon(Icons.no_photography, size: 28, color: _muted),
                  const SizedBox(height: 6),
                  Text('카메라 초기화 중…',
                    style: TextStyle(color: _muted, fontSize: 12, fontWeight: FontWeight.w700)),
                ]),
              )),

            // 2) BEV 그리드 + 차선 가이드 (Tesla 풍 ego 진행 경로)
            IgnorePointer(child: CustomPaint(
              size: Size(w, h),
              painter: _BevGuidePainter(),
            )),

            // 3) ML Kit 검출 박스 오버레이 (BEV 좌표계)
            //    카메라 frame 좌표(imgW, imgH) → 변환된 BEV 캔버스 좌표 매핑
            IgnorePointer(child: CustomPaint(
              size: Size(w, h),
              painter: _BevDetectionsPainter(
                detections: detections,
                imgW: imgW, imgH: imgH,
                transform: m,
                centerAlign: Alignment.center,
                camW: w * 1.4, camH: h * 1.8,
              ),
            )),

            // 4) 좌상단 LIVE 표시
            Positioned(left: 10, top: 8, child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
              decoration: BoxDecoration(
                color: const Color(0xCC0D1520),
                borderRadius: BorderRadius.circular(99),
                border: Border.all(color: _safe.withValues(alpha: 0.40), width: 0.8),
              ),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Container(width: 7, height: 7, decoration: BoxDecoration(
                  color: _safe, shape: BoxShape.circle,
                  boxShadow: [BoxShadow(color: _safe, blurRadius: 6)],
                )),
                const SizedBox(width: 6),
                Text('LIVE BEV', style: TextStyle(color: _safe, fontSize: 10,
                  fontWeight: FontWeight.w900, letterSpacing: 1.2)),
                const SizedBox(width: 8),
                Text('· ${detections.length} 검출',
                  style: TextStyle(color: _muted, fontSize: 10, fontWeight: FontWeight.w700)),
              ]),
            )),

            // 5) 우상단 ego 정보 (속도/위험)
            Positioned(right: 10, top: 8, child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
              decoration: BoxDecoration(
                color: const Color(0xCC0D1520), borderRadius: BorderRadius.circular(99),
                border: Border.all(color: _accent.withValues(alpha: 0.30), width: 0.8),
              ),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Icon(Icons.speed, size: 11, color: _accent),
                const SizedBox(width: 4),
                Text('0 km/h', style: TextStyle(color: _accent, fontSize: 10,
                  fontWeight: FontWeight.w900, letterSpacing: 0.5)),
              ]),
            )),
          ]),
        ),
      );
    });
  }
}

// BEV 가이드 라인 (도로 차선 + ego 진행 경로 + 거리 원)
class _BevGuidePainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width, h = size.height;
    // ego 진행 경로 (가운데 세로 가이드, fade)
    for (int i = 0; i < 8; i++) {
      final t = i / 7.0;
      final dy = h - 30 - i * 50.0;
      if (dy < 60) break;
      final p = Paint()
        ..color = const Color(0xFF00C8FF).withValues(alpha: 0.55 - t * 0.45)
        ..strokeWidth = 4 - t * 2.5
        ..strokeCap = StrokeCap.round;
      canvas.drawLine(Offset(w / 2, dy), Offset(w / 2, dy - 30), p);
    }
    // 거리 원 (5/10/20m)
    final ringPaint = Paint()
      ..style = PaintingStyle.stroke
      ..color = Colors.white.withValues(alpha: 0.10)
      ..strokeWidth = 1;
    for (final r in [80.0, 160.0, 260.0]) {
      canvas.drawCircle(Offset(w / 2, h - 10), r, ringPaint);
    }
  }
  @override
  bool shouldRepaint(covariant _BevGuidePainter oldDelegate) => false;
}

// 검출 박스 BEV 오버레이 — frame 좌표를 같은 perspective transform 으로 매핑
class _BevDetectionsPainter extends CustomPainter {
  final List<Map<String, dynamic>> detections;
  final int imgW, imgH;
  final Matrix4 transform;
  final Alignment centerAlign;
  final double camW, camH;
  _BevDetectionsPainter({
    required this.detections, required this.imgW, required this.imgH,
    required this.transform, required this.centerAlign,
    required this.camW, required this.camH,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width, h = size.height;
    // 카메라 OverflowBox 가 (camW, camH) 로 그려졌고 Transform alignment center.
    final scaleX = camW / imgW;
    final scaleY = camH / imgH;
    // OverflowBox 가 (w/2 - camW/2, h/2 - camH/2) 부터 시작
    final xOffset = (w - camW) / 2;
    final yOffset = (h - camH) / 2;

    canvas.save();
    canvas.translate(w / 2, h / 2);
    canvas.transform(transform.storage);
    canvas.translate(-w / 2, -h / 2);

    for (final d in detections) {
      final box = (d['box'] as List).map((e) => (e as num).toDouble()).toList();
      final cls = d['cls']?.toString() ?? 'car';
      final isPed = cls == 'person';
      final left = xOffset + box[0] * scaleX;
      final top = yOffset + box[1] * scaleY;
      final bw = box[2] * scaleX;
      final bh = box[3] * scaleY;
      final col = isPed ? _danger : _accent;
      final stroke = Paint()
        ..style = PaintingStyle.stroke
        ..color = col
        ..strokeWidth = 2.2;
      final fill = Paint()
        ..style = PaintingStyle.fill
        ..color = col.withValues(alpha: 0.16);
      final rect = Rect.fromLTWH(left, top, bw, bh);
      final rrect = RRect.fromRectAndRadius(rect, const Radius.circular(6));
      canvas.drawRRect(rrect, fill);
      canvas.drawRRect(rrect, stroke);

      // 라벨 텍스트 (cls + 면적)
      final tp = TextPainter(
        text: TextSpan(
          text: isPed ? '👤 보행자' : '🚗 차량',
          style: TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w900,
            backgroundColor: col.withValues(alpha: 0.85)),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(left + 3, top + 3));
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant _BevDetectionsPainter oldDelegate) =>
      oldDelegate.detections != detections;
}

// ═══════════════════════════════════════════════════════════════
// v9 2026-05-18: 메인 라이브 BEV — /bev3d/ WebView 인라인 임베드.
//   목적: 메인 화면이 곧 MetroEyes 식 실시간 3D BEV (별도 진입 X).
//   기능:
//     • 후면 카메라 + COCO-SSD on-device 검출 (TF.js webgl/cpu)
//     • 검출 박스 영역 비디오 픽셀을 텍스처화 → 3D 빌보드 (객체 모양 보존)
//     • 위험 빌보드 + 메트릭 패널 + AI 상태 LED — 모두 WebView 내부에
//   외부 HUD (Flutter side):
//     • _SignalHud · _CityInfoLine · _DriveButton 가 위에 겹쳐 표시
// ═══════════════════════════════════════════════════════════════
class _LiveBev3D extends StatefulWidget {
  final Map<String, dynamic>? fusion;
  final Map<String, dynamic>? busLive;
  final void Function(WebViewController controller)? onControllerReady;
  const _LiveBev3D({this.fusion, this.busLive, this.onControllerReady});
  @override
  State<_LiveBev3D> createState() => _LiveBev3DState();
}

class _LiveBev3DState extends State<_LiveBev3D> {
  late final WebViewController _wv;
  int _progress = 0;
  bool _loaded = false;
  static const _url = 'https://auraview.allthatai.kr/bev3d/?embed=fleet';

  @override
  void initState() {
    super.initState();
    final ctrl = WebViewController();
    ctrl
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(const Color(0xFF0A1018))
      ..setNavigationDelegate(NavigationDelegate(
        onProgress: (p) => setState(() => _progress = p),
        onPageFinished: (_) => setState(() => _loaded = true),
      ));
    final platform = ctrl.platform;
    if (platform is AndroidWebViewController) {
      platform.setMediaPlaybackRequiresUserGesture(false);
      platform.setOnPlatformPermissionRequest((req) => req.grant());
    }
    ctrl.loadRequest(Uri.parse(_url));
    _wv = ctrl;
    widget.onControllerReady?.call(ctrl);
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF0A1018),
        borderRadius: BorderRadius.circular(16),
        // v9.2: 패딩 줄이고 더 edge-to-edge 느낌
        border: Border.all(color: _accent.withValues(alpha: 0.20), width: 0.8),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(15),
        child: Stack(fit: StackFit.expand, children: [
          WebViewWidget(controller: _wv),
          // 로딩 인디케이터 (위쪽 가장자리)
          if (!_loaded)
            Positioned(left: 0, right: 0, top: 0, child: LinearProgressIndicator(
              value: _progress / 100,
              backgroundColor: const Color(0xFF121A2A),
              valueColor: AlwaysStoppedAnimation(_accent),
              minHeight: 2,
            )),
          // 로딩 중 중앙 안내
          if (!_loaded)
            Center(
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                CircularProgressIndicator(color: _accent, strokeWidth: 2.5),
                const SizedBox(height: 14),
                Text('실시간 3D BEV 시작…',
                  style: TextStyle(color: _text.withValues(alpha: 0.85), fontSize: 13, fontWeight: FontWeight.w800)),
                const SizedBox(height: 3),
                Text('카메라 + COCO-SSD on-device 검출',
                  style: TextStyle(color: _muted, fontSize: 10.5, fontWeight: FontWeight.w600)),
              ]),
            ),
          // 상단 좌측 라벨 (Flutter 측에서 표시 — WebView 내부 라벨이 가려지지 않게 우측 정렬도 무방)
          Positioned(
            left: 12, top: 8,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
              decoration: BoxDecoration(
                color: const Color(0xCC0D1520),
                borderRadius: BorderRadius.circular(99),
                border: Border.all(color: _accent.withValues(alpha: 0.35), width: 0.8),
              ),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Container(width: 7, height: 7, decoration: BoxDecoration(
                  color: _safe, shape: BoxShape.circle,
                  boxShadow: [BoxShadow(color: _safe, blurRadius: 6)],
                )),
                const SizedBox(width: 6),
                Text('LIVE BEV', style: TextStyle(color: _accent, fontSize: 10, fontWeight: FontWeight.w900, letterSpacing: 1.2)),
              ]),
            ),
          ),
        ]),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// v9.6 2026-05-19: 테슬라 식 BEV v2
//   사용자 요구: "사람 모양으로 나오게 할 수 없냐고", "거리감도 아예 다르고 UI/UX 갈아엎어라"
//   - 사람: 머리(원) + 몸통(트라페즈) + 다리 — 진짜 사람 실루엣
//   - 차량: 3D 박스 + 창문 + 보닛 + 그림자 + 글로우
//   - 거리감: 비선형 perspective + 거리 ring 5/15/30/50m
//   - perspective 그리드 바닥 (Tesla 시그니처)
//   - 60fps Ticker + smooth 보간
// ═══════════════════════════════════════════════════════════════
class _TeslaBevV2 extends StatefulWidget {
  final List<Map<String, dynamic>> detections;
  final int imgW;
  final int imgH;
  final Map<String, dynamic>? bev;   // v9.7: grid_flat (40x40 voxel occupancy)
  const _TeslaBevV2({required this.detections, required this.imgW, required this.imgH, this.bev});
  @override
  State<_TeslaBevV2> createState() => _TeslaBevV2State();
}

class _TeslaBevV2State extends State<_TeslaBevV2> with SingleTickerProviderStateMixin {
  late final Ticker _ticker;
  final List<_BevObj2> _objs = [];
  double _t = 0;
  double _lastMs = 0;

  @override
  void initState() {
    super.initState();
    _ticker = createTicker((d) {
      final ms = d.inMicroseconds / 1000.0;
      final dt = _lastMs == 0 ? 0.016 : ((ms - _lastMs) / 1000.0).clamp(0.0, 0.05);
      _lastMs = ms;
      _t = ms / 1000.0;
      bool dirty = false;
      for (int i = _objs.length - 1; i >= 0; i--) {
        final o = _objs[i];
        final ox = o.x, oy = o.y;
        o.x = o.x * (1 - dt * 5.5) + o.tx * dt * 5.5;
        o.y = o.y * (1 - dt * 5.5) + o.ty * dt * 5.5;
        if ((o.x - ox).abs() > 0.0005 || (o.y - oy).abs() > 0.0005) dirty = true;
        if (_t - o.lastSeen > 1.8) {
          o.alpha = (o.alpha * (1 - dt * 2.5)).clamp(0.0, 1.0);
          if (o.alpha < 0.05) { _objs.removeAt(i); dirty = true; continue; }
        } else {
          o.alpha = (o.alpha + dt * 4.0).clamp(0.0, 1.0);
        }
      }
      if (mounted && (dirty || _objs.isNotEmpty)) setState(() {});
    });
    _ticker.start();
    _syncFromDetections();
  }

  @override
  void didUpdateWidget(covariant _TeslaBevV2 old) {
    super.didUpdateWidget(old);
    if (!identical(old.detections, widget.detections)) _syncFromDetections();
  }

  void _syncFromDetections() {
    final ds = widget.detections;
    final iw = widget.imgW.toDouble(), ih = widget.imgH.toDouble();
    final now = _t;
    final used = <int>{};
    for (final d in ds) {
      final box = (d['box'] as List).map((e) => (e as num).toDouble()).toList();
      final bx = box[0] + box[2] / 2, by = box[1] + box[3];
      final ny = (by / ih).clamp(0.0, 1.0);
      final nx = ((bx / iw) - 0.5) * 2.0;
      final forward = math.pow(1.0 - ny, 1.8).toDouble();
      final cls = d['cls']?.toString() ?? 'car';
      double bestD = 0.30; int bestI = -1;
      for (int i = 0; i < _objs.length; i++) {
        if (used.contains(i)) continue;
        final o = _objs[i]; if (o.cls != cls) continue;
        final dd = math.sqrt(math.pow(o.tx - nx, 2) + math.pow(o.ty - forward, 2));
        if (dd < bestD) { bestD = dd; bestI = i; }
      }
      if (bestI >= 0) {
        final o = _objs[bestI];
        o.tx = nx; o.ty = forward;
        o.conf = (d['score'] as num?)?.toDouble() ?? 0.6;
        o.lastSeen = now; used.add(bestI);
      } else {
        _objs.add(_BevObj2(cls: cls, x: nx, y: forward, tx: nx, ty: forward,
          conf: (d['score'] as num?)?.toDouble() ?? 0.6,
          phase: math.Random().nextDouble() * 6.28,
          lastSeen: now, alpha: 0.0));
      }
    }
  }

  @override
  void dispose() { _ticker.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        gradient: const RadialGradient(
          center: Alignment(0, 0.9), radius: 1.2,
          colors: [Color(0xFF0B1320), Color(0xFF040810)],
        ),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: _accent.withValues(alpha: 0.20), width: 0.8),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(15),
        child: Stack(fit: StackFit.expand, children: [
          RepaintBoundary(child: CustomPaint(
            painter: _TeslaBevV2Painter(objs: _objs, t: _t, bev: widget.bev),
            size: Size.infinite,
          )),
          Positioned(left: 10, top: 8, child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
            decoration: BoxDecoration(
              color: const Color(0xCC0D1520), borderRadius: BorderRadius.circular(99),
              border: Border.all(color: _safe.withValues(alpha: 0.40), width: 0.8),
            ),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Container(width: 7, height: 7, decoration: BoxDecoration(
                color: _safe, shape: BoxShape.circle,
                boxShadow: [BoxShadow(color: _safe, blurRadius: 6)],
              )),
              const SizedBox(width: 6),
              Text('LIVE BEV', style: TextStyle(color: _safe, fontSize: 10,
                fontWeight: FontWeight.w900, letterSpacing: 1.2)),
              const SizedBox(width: 8),
              Builder(builder: (_) {
                int p = 0, v = 0;
                for (final o in _objs) { if (o.cls == 'person') p++; else v++; }
                return Text('· 사람 $p · 차량 $v',
                  style: TextStyle(color: _muted, fontSize: 10, fontWeight: FontWeight.w800));
              }),
            ]),
          )),
        ]),
      ),
    );
  }
}

class _BevObj2 {
  String cls; double x, y, tx, ty, conf, phase, lastSeen, alpha;
  _BevObj2({required this.cls, required this.x, required this.y,
    required this.tx, required this.ty, required this.conf,
    required this.phase, required this.lastSeen, required this.alpha});
}

class _TeslaBevV2Painter extends CustomPainter {
  final List<_BevObj2> objs;
  final double t;
  final Map<String, dynamic>? bev;
  _TeslaBevV2Painter({required this.objs, required this.t, this.bev});

  Offset _project(double x, double y, Size size) {
    final w = size.width, h = size.height;
    final cy = h * (0.92 - y * 0.82);
    final lateralScale = 0.50 + (1 - y) * 0.38;
    final cx = w / 2 + x * w * lateralScale;
    return Offset(cx, cy);
  }

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width, h = size.height;

    // ── 1) perspective 그리드 바닥
    final gridP = Paint()..strokeWidth = 1;
    for (final yNorm in [0.10, 0.30, 0.55, 0.80]) {
      final yPx = h * (0.92 - yNorm * 0.82);
      final scale = 0.50 + (1 - yNorm) * 0.38;
      gridP.color = const Color(0xFF00C8FF).withValues(alpha: 0.06 + (1 - yNorm) * 0.10);
      canvas.drawLine(Offset(w / 2 - w * scale, yPx), Offset(w / 2 + w * scale, yPx), gridP);
    }
    // v9.9: radial 라인 제거 (차선과 시각적 충돌). 가로 거리 라인만 유지.

    // ── 1.5) v9.9: Tesla AP 실 시각화 — 주행가능구역 폴리곤 + 평행 차선
    //   원근감 그리드 위에 옅은 회색 주행가능구역(drivable area) 폴리곤.
    //   차선은 평행하게 (한 점으로 수렴 X — 그건 철길임).
    final laneL = -0.22, laneR = 0.22;
    // 주행가능 폴리곤 (옅은 흰/회 fill)
    final drivable = Path()
      ..moveTo(_project(laneL * 1.4, 0.0, size).dx, _project(laneL * 1.4, 0.0, size).dy)
      ..lineTo(_project(laneR * 1.4, 0.0, size).dx, _project(laneR * 1.4, 0.0, size).dy)
      ..lineTo(_project(laneR * 1.0, 1.0, size).dx, _project(laneR * 1.0, 1.0, size).dy)
      ..lineTo(_project(laneL * 1.0, 1.0, size).dx, _project(laneL * 1.0, 1.0, size).dy)
      ..close();
    canvas.drawPath(drivable, Paint()
      ..shader = LinearGradient(
        begin: Alignment.bottomCenter, end: Alignment.topCenter,
        colors: [Colors.white.withValues(alpha: 0.06), Colors.white.withValues(alpha: 0.01)],
      ).createShader(Rect.fromLTWH(0, 0, w, h)));

    // 좌/우 차선 (Tesla 흰 굵은 선) — 평행에 가깝게
    final lanePaint = Paint()
      ..style = PaintingStyle.stroke..strokeCap = StrokeCap.round..strokeWidth = 3.5
      ..shader = LinearGradient(
        begin: Alignment.bottomCenter, end: Alignment.topCenter,
        colors: [Colors.white.withValues(alpha: 0.75), Colors.white.withValues(alpha: 0.10)],
      ).createShader(Rect.fromLTWH(0, 0, w, h));
    canvas.drawPath(Path()
      ..moveTo(_project(laneL * 1.4, 0.0, size).dx, _project(laneL * 1.4, 0.0, size).dy)
      ..lineTo(_project(laneL * 1.0, 1.0, size).dx, _project(laneL * 1.0, 1.0, size).dy),
      lanePaint);
    canvas.drawPath(Path()
      ..moveTo(_project(laneR * 1.4, 0.0, size).dx, _project(laneR * 1.4, 0.0, size).dy)
      ..lineTo(_project(laneR * 1.0, 1.0, size).dx, _project(laneR * 1.0, 1.0, size).dy),
      lanePaint);

    // ── 2) 거리 라벨
    final labels = [[0.10, '5m'], [0.30, '15m'], [0.55, '30m'], [0.80, '50m+']];
    for (final entry in labels) {
      final yNorm = entry[0] as double;
      final txt = entry[1] as String;
      final yPx = h * (0.92 - yNorm * 0.82);
      final scale = 0.50 + (1 - yNorm) * 0.38;
      final tp = TextPainter(
        text: TextSpan(text: txt, style: TextStyle(
          color: const Color(0xFF5A7A9A).withValues(alpha: 0.75), fontSize: 9,
          fontWeight: FontWeight.w800, letterSpacing: 0.5)),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(w / 2 - w * scale - tp.width - 4, yPx - tp.height / 2));
    }

    // ── 3) Ego 진행 경로
    final pathP = Paint()..strokeCap = StrokeCap.round;
    for (int i = 0; i < 7; i++) {
      final y0n = 0.02 + i * 0.075;
      final y1n = y0n + 0.04;
      if (y1n > 0.55) break;
      final p0 = _project(0, y0n, size);
      final p1 = _project(0, y1n, size);
      final base = 0.55 - i * 0.06;
      final alpha = base + 0.10 * math.sin(t * 2.5 + i * 0.6);
      pathP.color = const Color(0xFF00C8FF).withValues(alpha: alpha.clamp(0.0, 0.7));
      pathP.strokeWidth = 5 - i * 0.4;
      canvas.drawLine(p0, p1, pathP);
    }

    // ── 4) Ego
    _drawEgo(canvas, size);

    // ── 5) 검출 객체
    final sorted = [...objs];
    sorted.sort((a, b) => b.y.compareTo(a.y));
    for (final o in sorted) {
      final p = _project(o.x.clamp(-0.92, 0.92), o.y.clamp(0.0, 0.95), size);
      if (o.cls == 'person') {
        _drawPersonSilhouette(canvas, p, o.y, o.alpha, o.phase);
      } else {
        _drawVehicle3D(canvas, p, o.y, o.alpha);
      }
    }
  }

  // v9.8: Tesla 실 AP 식 ego (위에서 본 차량 실루엣 - 차체 + 창문 + 바퀴 + 그림자)
  void _drawEgo(Canvas canvas, Size size) {
    final p = _project(0, 0.0, size);
    _drawTeslaCar(canvas, p, scale: 1.0, col: const Color(0xFF00C8FF), isEgo: true);
    // EGO 라벨
    final tp = TextPainter(
      text: TextSpan(text: 'EGO',
        style: TextStyle(color: const Color(0xFF00C8FF), fontSize: 9,
          fontWeight: FontWeight.w900, letterSpacing: 1.5)),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(canvas, Offset(p.dx - tp.width / 2, p.dy + 30));
  }

  // 위에서 본 차량 (top-down) — Tesla AP 차량 아이콘 스타일
  //   - 차체: 둥근 모서리 사각형 (gradient)
  //   - 창문: 앞/뒤 어두운 사다리꼴
  //   - 바퀴: 네 모서리 작은 어두운 사각형
  //   - 헤드라이트/테일라이트: 노랑/빨강 작은 점
  //   - 그라운드 그림자 + 글로우
  void _drawTeslaCar(Canvas canvas, Offset center,
      {required double scale, required Color col, bool isEgo = false, double alpha = 1.0}) {
    // 차량 dim (top-down Tesla 비율): 가로 4 : 세로 1.85
    final w = 30.0 * scale, h = 14.0 * scale;
    final colDark = HSLColor.fromColor(col).withLightness(
      (HSLColor.fromColor(col).lightness - 0.20).clamp(0.10, 0.90)).toColor();

    // 그라운드 그림자
    canvas.drawRRect(RRect.fromRectAndRadius(
      Rect.fromCenter(center: center.translate(0, h * 0.55), width: w * 1.10, height: h * 0.5),
      const Radius.circular(4)),
      Paint()..color = Colors.black.withValues(alpha: 0.45 * alpha)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 5));
    // 그라운드 글로우
    canvas.drawCircle(center.translate(0, h * 0.35), w * 0.55,
      Paint()..color = col.withValues(alpha: 0.25 * alpha));

    // 차체 (rounded rect)
    final bodyRect = Rect.fromCenter(center: center, width: w, height: h);
    final bodyRRect = RRect.fromRectAndCorners(bodyRect,
      topLeft: Radius.circular(h * 0.30),
      topRight: Radius.circular(h * 0.30),
      bottomLeft: Radius.circular(h * 0.45),
      bottomRight: Radius.circular(h * 0.45));
    canvas.drawRRect(bodyRRect,
      Paint()..shader = LinearGradient(
        begin: Alignment.topCenter, end: Alignment.bottomCenter,
        colors: [col.withValues(alpha: alpha), colDark.withValues(alpha: alpha)],
      ).createShader(bodyRect));

    // 4 바퀴 (모서리 검은 사각형)
    final wheelP = Paint()..color = const Color(0xFF0A0E15).withValues(alpha: alpha);
    final wRad = h * 0.18;
    final wheelW = w * 0.07, wheelH = h * 0.45;
    for (final dx in [-w * 0.42, w * 0.42]) {
      for (final dy in [-h * 0.28, h * 0.28]) {
        canvas.drawRRect(RRect.fromRectAndRadius(
          Rect.fromCenter(center: center.translate(dx, dy), width: wheelW, height: wheelH),
          Radius.circular(wRad * 0.3)), wheelP);
      }
    }

    // 앞 창문 (사다리꼴 어두운, 위쪽이 좁음 → 앞 방향 = 위)
    final winFront = Path()
      ..moveTo(center.dx - w * 0.32, center.dy - h * 0.08)
      ..lineTo(center.dx - w * 0.26, center.dy - h * 0.30)
      ..lineTo(center.dx + w * 0.26, center.dy - h * 0.30)
      ..lineTo(center.dx + w * 0.32, center.dy - h * 0.08)
      ..close();
    canvas.drawPath(winFront, Paint()..color = const Color(0xFF06121E).withValues(alpha: 0.85 * alpha));
    // 뒷 창문 (작게)
    final winRear = Path()
      ..moveTo(center.dx - w * 0.30, center.dy + h * 0.10)
      ..lineTo(center.dx - w * 0.24, center.dy + h * 0.26)
      ..lineTo(center.dx + w * 0.24, center.dy + h * 0.26)
      ..lineTo(center.dx + w * 0.30, center.dy + h * 0.10)
      ..close();
    canvas.drawPath(winRear, Paint()..color = const Color(0xFF06121E).withValues(alpha: 0.85 * alpha));

    // 가운데 보닛/지붕 분리 라인 (얇은 밝은 선)
    canvas.drawLine(
      Offset(center.dx - w * 0.42, center.dy),
      Offset(center.dx + w * 0.42, center.dy),
      Paint()..color = Colors.white.withValues(alpha: 0.18 * alpha)..strokeWidth = 0.6);

    // 헤드라이트 (앞 = 위, 노랑) / 테일라이트 (뒤 = 아래, 빨강) — ego 도 동일
    final hl = Paint()..color = const Color(0xFFFFD93D).withValues(alpha: 0.9 * alpha);
    canvas.drawCircle(Offset(center.dx - w * 0.36, center.dy - h * 0.42), 1.5 * scale + 0.6, hl);
    canvas.drawCircle(Offset(center.dx + w * 0.36, center.dy - h * 0.42), 1.5 * scale + 0.6, hl);
    final tl = Paint()..color = const Color(0xFFFF4040).withValues(alpha: 0.85 * alpha);
    canvas.drawCircle(Offset(center.dx - w * 0.36, center.dy + h * 0.42), 1.3 * scale + 0.5, tl);
    canvas.drawCircle(Offset(center.dx + w * 0.36, center.dy + h * 0.42), 1.3 * scale + 0.5, tl);

    // 외곽선
    canvas.drawRRect(bodyRRect,
      Paint()..style = PaintingStyle.stroke..strokeWidth = 1.2
        ..color = col.withValues(alpha: alpha));
  }

  void _drawPersonSilhouette(Canvas canvas, Offset p, double forwardNorm, double alpha, double phase) {
    final scale = 1.0 - forwardNorm * 0.70;
    final headR = 6.0 * scale;
    final bodyH = 26.0 * scale;
    final bodyW = 12.0 * scale;
    final legH = 14.0 * scale;
    final col = const Color(0xFFFF4040);

    final pulse = 1.0 + 0.35 * math.sin(t * 3.2 + phase);
    canvas.drawCircle(p.translate(0, headR * 0.5), (headR + bodyW * 0.7) * pulse,
      Paint()..style = PaintingStyle.stroke..strokeWidth = 1.5
        ..color = col.withValues(alpha: (0.55 / pulse) * alpha));

    canvas.drawOval(Rect.fromCenter(
      center: p.translate(0, bodyH * 0.4), width: bodyW * 1.6, height: bodyW * 0.7),
      Paint()..color = Colors.black.withValues(alpha: 0.5 * alpha)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 4));

    final legP = Paint()..color = col.withValues(alpha: 0.85 * alpha)
      ..strokeCap = StrokeCap.round..strokeWidth = bodyW * 0.30;
    canvas.drawLine(Offset(p.dx - bodyW * 0.20, p.dy + bodyH * 0.10),
      Offset(p.dx - bodyW * 0.20, p.dy + bodyH * 0.10 + legH), legP);
    canvas.drawLine(Offset(p.dx + bodyW * 0.20, p.dy + bodyH * 0.10),
      Offset(p.dx + bodyW * 0.20, p.dy + bodyH * 0.10 + legH), legP);

    final bodyPath = Path()
      ..moveTo(p.dx - bodyW * 0.50, p.dy - bodyH * 0.30)
      ..lineTo(p.dx + bodyW * 0.50, p.dy - bodyH * 0.30)
      ..lineTo(p.dx + bodyW * 0.32, p.dy + bodyH * 0.20)
      ..lineTo(p.dx - bodyW * 0.32, p.dy + bodyH * 0.20)
      ..close();
    canvas.drawPath(bodyPath, Paint()..shader = LinearGradient(
      begin: Alignment.topCenter, end: Alignment.bottomCenter,
      colors: [col.withValues(alpha: alpha), col.withValues(alpha: 0.75 * alpha)],
    ).createShader(Rect.fromCenter(center: p, width: bodyW, height: bodyH)));

    final armP = Paint()..color = col.withValues(alpha: 0.85 * alpha)
      ..strokeCap = StrokeCap.round..strokeWidth = bodyW * 0.22;
    canvas.drawLine(Offset(p.dx - bodyW * 0.50, p.dy - bodyH * 0.25),
      Offset(p.dx - bodyW * 0.75, p.dy - bodyH * 0.05), armP);
    canvas.drawLine(Offset(p.dx + bodyW * 0.50, p.dy - bodyH * 0.25),
      Offset(p.dx + bodyW * 0.75, p.dy - bodyH * 0.05), armP);

    canvas.drawCircle(Offset(p.dx, p.dy - bodyH * 0.45), headR,
      Paint()..color = col.withValues(alpha: alpha));
    canvas.drawCircle(Offset(p.dx, p.dy - bodyH * 0.45), headR * 1.4,
      Paint()..color = col.withValues(alpha: 0.55 * alpha)
        ..maskFilter = MaskFilter.blur(BlurStyle.normal, headR * 0.5));

    final distM = 1.5 + 33.5 * forwardNorm;
    final tp = TextPainter(
      text: TextSpan(text: '👤 ${distM.toStringAsFixed(1)}m',
        style: TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.w900,
          backgroundColor: col.withValues(alpha: 0.85 * alpha))),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(canvas, Offset(p.dx - tp.width / 2, p.dy - bodyH * 0.75 - tp.height - 4));
  }

  // v9.8: 검출 차량도 Tesla 식 top-down 실루엣 (ego 와 동일 모양, 색만 다름)
  void _drawVehicle3D(Canvas canvas, Offset p, double forwardNorm, double alpha) {
    final scale = 1.0 - forwardNorm * 0.70;
    _drawTeslaCar(canvas, p, scale: scale, col: const Color(0xFFA095FF), alpha: alpha);
    // 라벨
    final distM = 1.5 + 33.5 * forwardNorm;
    final tp = TextPainter(
      text: TextSpan(text: '🚗 ${distM.toStringAsFixed(1)}m',
        style: TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.w900,
          backgroundColor: const Color(0xFFA095FF).withValues(alpha: 0.85 * alpha))),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(canvas, Offset(p.dx - tp.width / 2, p.dy - 14 * scale - tp.height - 4));
  }

  @override
  bool shouldRepaint(covariant _TeslaBevV2Painter old) => true;
}

// ═══════════════════════════════════════════════════════════════
// v11.2 2026-05-19: Tesla 식 코너 라벨 (카메라/BEV 카드 위에)
// ═══════════════════════════════════════════════════════════════
class _TeslaLabel extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  const _TeslaLabel({required this.icon, required this.label, required this.color});
  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(99),
      child: BackdropFilter(
        filter: ui.ImageFilter.blur(sigmaX: 10, sigmaY: 10),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
          decoration: BoxDecoration(
            color: Colors.black.withValues(alpha: 0.50),
            border: Border.all(color: color.withValues(alpha: 0.35), width: 0.6),
            borderRadius: BorderRadius.circular(99),
          ),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Container(width: 6, height: 6, decoration: BoxDecoration(
              color: color, shape: BoxShape.circle,
              boxShadow: [BoxShadow(color: color, blurRadius: 4)],
            )),
            const SizedBox(width: 6),
            Icon(icon, size: 10, color: color),
            const SizedBox(width: 4),
            Text(label, style: TextStyle(color: color, fontSize: 9.5,
              fontWeight: FontWeight.w900, letterSpacing: 1.0)),
          ]),
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// v11 2026-05-19: floating REC pill (옛 _DriveButton 큰 거 폐기, 작은 알약)
// ═══════════════════════════════════════════════════════════════
class _RecPill extends StatelessWidget {
  final bool on;
  final VoidCallback? onTap;
  const _RecPill({required this.on, this.onTap});

  @override
  Widget build(BuildContext context) {
    final col = on ? _danger : Colors.white;
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 260),
        curve: Curves.easeOutCubic,
        height: 42,
        padding: const EdgeInsets.symmetric(horizontal: 22),
        decoration: BoxDecoration(
          // Tesla "Engage AP" 풍 — pure dark glass + bright accent border
          gradient: on
            ? LinearGradient(
                begin: Alignment.topCenter, end: Alignment.bottomCenter,
                colors: [_danger.withValues(alpha: 0.32), _danger.withValues(alpha: 0.18)],
              )
            : LinearGradient(
                begin: Alignment.topCenter, end: Alignment.bottomCenter,
                colors: [Colors.white.withValues(alpha: 0.10), Colors.white.withValues(alpha: 0.04)],
              ),
          border: Border.all(color: col.withValues(alpha: on ? 0.85 : 0.40), width: 1.4),
          borderRadius: BorderRadius.circular(99),
          boxShadow: on
            ? [BoxShadow(color: _danger.withValues(alpha: 0.55), blurRadius: 18, spreadRadius: 1)]
            : [BoxShadow(color: Colors.black.withValues(alpha: 0.45), blurRadius: 10, offset: const Offset(0, 4))],
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Container(
            width: 8, height: 8, decoration: BoxDecoration(
              color: col, shape: BoxShape.circle,
              boxShadow: [BoxShadow(color: col, blurRadius: 6)],
            ),
          ),
          const SizedBox(width: 10),
          Text(on ? 'AURA · ENGAGED' : 'TAP TO ENGAGE',
            style: TextStyle(color: col, fontSize: 11,
              fontWeight: FontWeight.w900, letterSpacing: 2.0)),
        ]),
      ),
    );
  }
}
