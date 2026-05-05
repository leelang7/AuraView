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
import 'package:flutter/scheduler.dart';
import 'dart:ui' show FontFeature;
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:image/image.dart' as img;
import 'package:permission_handler/permission_handler.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:google_mlkit_object_detection/google_mlkit_object_detection.dart';
import 'package:google_mlkit_commons/google_mlkit_commons.dart';

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
  String? _autoIntersectionId;            // GPS 기반 자동 감지 교차로
  String? _autoIntersectionName;
  Timer? _bevTimer;
  Timer? _scnRotateTimer;
  List<double>? _prevFrameGray;  // motion diff 용 이전 프레임

  // ★ ML Kit 객체 검출 (사람/차량 on-device 인식)
  ObjectDetector? _objDetector;
  bool _mlkitBusy = false;

  // ★ DEMO 시나리오 모드 — 사용자가 명시적으로 켤 때만 활성 (기본 OFF)
  // OFF: LIVE 모드 — 카메라 frame → 클라이언트 voxel (실제 환경)
  // ON:  DEMO 모드 — 서버 4 시나리오 자동 순환 (실내 시연용)
  bool _demoScenarioOn = false;
  static const _scnList = ['truck_occlusion', 'motorcycle_blindspot', 'signal_occlusion', 'rainy_intersection', 'right_turn_pedestrian'];
  static const _scnLabels = {
    'truck_occlusion': '🚛 트럭 가림',
    'motorcycle_blindspot': '◀ 사각지대 이륜',
    'signal_occlusion': '🚦 버스 뒤 신호',
    'rainy_intersection': '🌧️ 우천',
    'right_turn_pedestrian': '🚸 우회전 보행자',
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

  /// GPS 좌표 기준 가장 가까운 교차로 (반경 800m 이내) 자동 감지.
  /// 사용자가 settings 에서 intersection_id 를 안 넣어도 HUD 가 동작하도록.
  void _autoDetectIntersection() {
    final p = _pos;
    if (p == null) return;
    String? bestId;
    String? bestName;
    double bestDist = 0.8;  // 0.8km 이내만 매칭
    for (final it in _knownIntersections) {
      final dKm = _haversineKm(p.latitude, p.longitude,
          (it['lat'] as num).toDouble(), (it['lon'] as num).toDouble());
      if (dKm < bestDist) {
        bestDist = dKm;
        bestId = it['id'] as String;
        bestName = it['name'] as String;
      }
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
        _objDetector = ObjectDetector(
          options: ObjectDetectorOptions(
            mode: DetectionMode.single,
            classifyObjects: false,
            multipleObjects: true,
          ),
        );
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
    _posSub?.cancel();
    _cam?.dispose();
    _objDetector?.close();
    _pulseAnim.dispose();
    super.dispose();
  }

  /// BEV 오버레이 toggle — ON 이면 5초마다 /occupancy/demo + /fusion/intersection 폴링
  void _toggleBev() {
    HapticFeedback.lightImpact();
    setState(() => _bevOpen = !_bevOpen);
    if (_bevOpen) {
      _fetchBev();
      _bevTimer = Timer.periodic(const Duration(seconds: 5), (_) => _fetchBev());
    } else {
      _bevTimer?.cancel();
      _bevTimer = null;
    }
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
      _fetchBev();
      _scnRotateTimer = Timer.periodic(const Duration(seconds: 8), (_) {
        _scnIdx = (_scnIdx + 1) % _scnList.length;
        _fetchBev();
      });
    }
  }

  /// 카메라 프레임 → 클라이언트(엣지) voxel 직접 생성. 서버 호출 X.
  /// + ML Kit 객체 검출 → class_grid_flat 채워서 사람/차량 형상 표시.
  Future<void> _fetchBev() async {
    if (_cam != null && _cam!.value.isInitialized && !_cam!.value.isTakingPicture) {
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

        // 3) 임시 파일 정리
        if (!kIsWeb) {
          try { final f = File(shot.path); if (await f.exists()) await f.delete(); } catch (_) {}
        }
        if (voxel != null && mounted) {
          setState(() => _bev = voxel);
        }
      } catch (_) {}
    }
    // 도시정보 결합 (signal/VDS/TAAS) — voxel 위에 라이브 라인 표시용
    // intersection_id 우선순위: 사용자 설정값 → GPS 자동 감지값
    _autoDetectIntersection();
    final iid = (_intersectionId != null && _intersectionId!.isNotEmpty)
        ? _intersectionId!
        : _autoIntersectionId;
    if (iid != null && iid.isNotEmpty) {
      try {
        final r = await http.get(Uri.parse('$kApiBase/fusion/intersection/$iid'))
            .timeout(const Duration(seconds: 6));
        if (r.statusCode == 200) {
          final body = jsonDecode(r.body) as Map<String, dynamic>;
          if (mounted) setState(() => _fusion = body);
        }
      } catch (_) {}

      // 가려진 신호등 대체 안내 — voxel 분석으로 occlusion_score 추정
      try {
        final occ = _estimateOcclusionScore();
        final r = await http.get(Uri.parse(
              '$kApiBase/signals/$iid/alternate?occlusion_score=${occ.toStringAsFixed(2)}'))
            .timeout(const Duration(seconds: 6));
        if (r.statusCode == 200) {
          final body = jsonDecode(r.body) as Map<String, dynamic>;
          if (mounted) setState(() => _altSignal = body);
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
      for (final obj in objects) {
        final box = obj.boundingBox;
        final cxImg = (box.left + box.right) / 2;
        final cyImg = (box.top + box.bottom) / 2;
        final w = (box.right - box.left).abs();
        final h = (box.bottom - box.top).abs();
        if (w < 8 || h < 8) continue;  // 너무 작은 검출 skip
        final aspect = h / w;
        // 분류 (단순 휴리스틱)
        final cls = aspect > 1.5 ? 4 : 1;  // 4=person 1=vehicle
        // BEV 셀 매핑
        final bevC = (cxImg / imgW * cols).round().clamp(0, cols - 1);
        final bevR = ((1 - cyImg / imgH) * rows).round().clamp(0, rows - 1);
        // 박스 사이즈 → BEV cell radius (1~3)
        final pixelArea = w * h / (imgW * imgH);
        final radius = (math.sqrt(pixelArea) * 14).clamp(1.0, 4.0).toInt();
        for (int dr = -radius; dr <= radius; dr++) {
          for (int dc = -radius; dc <= radius; dc++) {
            final r = bevR + dr;
            final c = bevC + dc;
            if (r < 0 || r >= rows || c < 0 || c >= cols) continue;
            classGrid[r * cols + c] = cls;
          }
        }
      }
      return classGrid;
    } catch (_) {
      return null;
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
        setState(() => _pos = p);
      }, onError: (_) {});
    } catch (_) {}
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused) _ticker?.cancel();
  }

  Future<void> _bootstrap() async {
    final sp = await SharedPreferences.getInstance();
    var id = sp.getString('device_id');
    if (id == null) {
      id = 'fleet-${DateTime.now().millisecondsSinceEpoch}-${Random().nextInt(1 << 32).toRadixString(16)}';
      await sp.setString('device_id', id);
    }
    _intersectionId = sp.getString('intersection_id');
    setState(() => _deviceId = id!);

    if (!kIsWeb) {
      await Permission.camera.request();
      await Permission.locationWhenInUse.request();
    }

    if (_cameras.isNotEmpty) {
      final preferred = _cameras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.back,
        orElse: () => _cameras.first,
      );
      final controller = CameraController(
        preferred,
        ResolutionPreset.medium,
        enableAudio: false,
        imageFormatGroup: ImageFormatGroup.jpeg,
      );
      try {
        await controller.initialize();
        _cam = controller;
      } catch (_) {/* leave null */}
    }

    _refreshLocation();
    _startLocationStream();
    _pollServer();
    Timer.periodic(const Duration(seconds: 30), (_) => _pollServer());

    // BEV 자동 시작 (5초 주기) — LIVE: 카메라 voxelize 만, DEMO: + 서버 시나리오
    _fetchBev();
    _bevTimer = Timer.periodic(const Duration(seconds: 5), (_) => _fetchBev());
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

  Future<void> _manualContribute() async {
    if (_cam == null || !_cam!.value.isInitialized) {
      _toast('카메라 준비 안 됨');
      return;
    }
    HapticFeedback.mediumImpact();
    try {
      final shot = await _cam!.takePicture();
      final bytes = await shot.readAsBytes();
      _captures++;
      _lastReason = 'manual';
      final feat = _entropyAndMotion(bytes);
      _lastEntropy = feat.entropy;
      await _upload(bytes, feat.entropy, 'manual');
      _toast('기여됨 ✨', color: _safe);
    } catch (e) {
      _toast('업로드 실패', color: _danger);
    }
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
                  // 1) 상단 status bar
                  Padding(
                    padding: const EdgeInsets.fromLTRB(14, 12, 14, 0),
                    child: _UnifiedStatusBar(
                      shadowOn: _shadowOn,
                      uploads: _uploads,
                      online: _serverError.isEmpty,
                      pos: _pos,
                      onSettingsTap: _openDetailSheet,
                    ),
                  ),
                  const SizedBox(height: 8),

                  // 2) Alert HUD 또는 Idle 카드 (조건부)
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    child: _altSignal != null
                      ? _SignalHud(
                          altSignal: _altSignal!,
                          intersectionName: _autoIntersectionName ??
                              (_intersectionId != null ? '교차로 $_intersectionId' : ''),
                          pulse: _lastReason == 'signal_occluded',
                        )
                      : _IdleStatusCard(
                          uploads: _uploads,
                          captures: _captures,
                          shadowOn: _shadowOn,
                          intersectionId: _autoIntersectionId ?? _intersectionId,
                          intersectionName: _autoIntersectionName,
                          onSettingsTap: _openDetailSheet,
                        ),
                  ),
                  const SizedBox(height: 10),

                  // 3) ★ BEV 메인 화면 (Tesla 모니터 스타일) — Expanded로 가용 공간 모두 사용
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      child: _BevPanel(
                        bev: _demoScenarioOn ? (_serverBev ?? _bev) : _bev,
                        fusion: _fusion,
                        demoMode: _demoScenarioOn,
                        scenarioLabel: _demoScenarioOn
                            ? (_scnLabels[_scnList[_scnIdx % _scnList.length]] ?? '')
                            : null,
                        onToggleDemo: _toggleDemoScenario,
                        fillScreen: true,
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),
                ],
              ),
            ),

            // 4) 카메라 PiP — 좌하단 작게 (140×100) · 드라이브 버튼 위
            if (_cam != null && _cam!.value.isInitialized)
              Positioned(
                left: 14, bottom: 100,
                child: GestureDetector(
                  onTap: () { /* 추후: 풀스크린 토글 */ },
                  child: Container(
                    width: 140, height: 100,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: _accent.withValues(alpha: 0.40), width: 1.2),
                      boxShadow: [BoxShadow(color: _accent.withValues(alpha: 0.18), blurRadius: 12)],
                    ),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(9),
                      child: Stack(fit: StackFit.expand, children: [
                        _FullCameraPreview(controller: _cam!),
                        Positioned(
                          top: 4, left: 6,
                          child: Container(
                            padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
                            decoration: BoxDecoration(
                              color: const Color(0xCC0D1520),
                              borderRadius: BorderRadius.circular(99),
                            ),
                            child: Row(mainAxisSize: MainAxisSize.min, children: [
                              Container(
                                width: 5, height: 5,
                                decoration: BoxDecoration(
                                  color: _shadowOn ? _safe : _muted, shape: BoxShape.circle,
                                  boxShadow: _shadowOn ? [BoxShadow(color: _safe, blurRadius: 4)] : null,
                                ),
                              ),
                              const SizedBox(width: 4),
                              Text('CAM', style: TextStyle(color: _accent, fontSize: 8, fontWeight: FontWeight.w900, letterSpacing: 1.2)),
                            ]),
                          ),
                        ),
                      ]),
                    ),
                  ),
                ),
              ),

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

            // 7) 하단 드라이브 버튼
            SafeArea(
              child: Align(
                alignment: Alignment.bottomCenter,
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 18),
                  child: _DriveButton(
                    on: _shadowOn,
                    onTap: _toggleShadow,
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
    final size = MediaQuery.of(context).size;
    final ratio = controller.value.aspectRatio;
    return ClipRect(
      child: SizedBox.expand(
        child: FittedBox(
          fit: BoxFit.cover,
          child: SizedBox(
            width: size.width,
            height: size.width / (1 / ratio),
            child: CameraPreview(controller),
          ),
        ),
      ),
    );
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
  final VoidCallback? onSettingsTap;
  const _UnifiedStatusBar({
    required this.shadowOn,
    required this.uploads,
    required this.online,
    required this.pos,
    this.onSettingsTap,
  });

  @override
  Widget build(BuildContext context) {
    final hasGps = pos != null;
    final speed = hasGps ? (pos!.speed * 3.6).toStringAsFixed(0) : '—';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: _bg.withValues(alpha: 0.78),
        border: Border.all(color: _border()),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(children: [
        // 브랜드 마크 — radial gradient circle + 펄스 (shadow ON 시 글로우)
        Container(
          width: 28, height: 28,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            gradient: const RadialGradient(
              colors: [Color(0xFFD8FAFF), _accent, _accent2],
              stops: [0.0, 0.45, 1.0],
            ),
            boxShadow: [
              BoxShadow(
                color: (shadowOn ? _safe : _accent).withValues(alpha: 0.55),
                blurRadius: 14, spreadRadius: 1,
              ),
            ],
          ),
        ),
        const SizedBox(width: 10),
        Text('Aura', style: TextStyle(color: _muted, fontSize: 13, fontWeight: FontWeight.w600)),
        Text('View', style: TextStyle(color: _accent, fontSize: 13, fontWeight: FontWeight.w800)),
        const Spacer(),
        // 속도
        if (hasGps) ...[
          Text(speed, style: TextStyle(color: _text, fontSize: 14, fontWeight: FontWeight.w800,
                                       fontFeatures: const [FontFeature.tabularFigures()])),
          Text('km/h', style: TextStyle(color: _muted, fontSize: 9, fontWeight: FontWeight.w700,
                                        letterSpacing: 1)),
          const SizedBox(width: 14),
        ],
        // 기록 카운터
        Icon(Icons.bookmark_added_rounded, size: 14, color: _safe),
        const SizedBox(width: 4),
        Text('$uploads', style: TextStyle(color: _safe, fontSize: 13, fontWeight: FontWeight.w800)),
        const SizedBox(width: 14),
        // 서버
        Icon(online ? Icons.cloud_done_rounded : Icons.cloud_off_rounded,
             size: 14, color: online ? _safe : _danger),
        const SizedBox(width: 12),
        // ⚙ 설정 버튼 — 우측 끝, 큰 박스 (탭 즉시 시트)
        GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: onSettingsTap,
          child: Container(
            width: 36, height: 36,
            decoration: BoxDecoration(
              color: _accent.withValues(alpha: 0.18),
              border: Border.all(color: _accent.withValues(alpha: 0.6), width: 1.5),
              borderRadius: BorderRadius.circular(10),
            ),
            child: const Icon(Icons.tune_rounded, size: 20, color: _accent),
          ),
        ),
      ]),
    );
  }
  static Color _border() => const Color(0x4400C8FF);
}

class _DriveButton extends StatelessWidget {
  final bool on;
  final VoidCallback onTap;
  const _DriveButton({required this.on, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 220),
        width: 240, height: 64,
        decoration: BoxDecoration(
          gradient: LinearGradient(
            colors: on
                ? [const Color(0xFF005580), const Color(0xFF003344)]
                : [const Color(0xFF00C8FF), const Color(0xFF0078A8)],
          ),
          borderRadius: BorderRadius.circular(32),
          boxShadow: [
            BoxShadow(
              color: (on ? _accent : _safe).withValues(alpha: 0.45),
              blurRadius: 24, spreadRadius: 1,
            ),
          ],
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(on ? Icons.stop_rounded : Icons.directions_car_filled_rounded,
                 size: 26, color: Colors.white),
            const SizedBox(width: 10),
            Text(on ? '주행 중지' : '주행 시작',
                 style: const TextStyle(color: Colors.white, fontSize: 18,
                                        fontWeight: FontWeight.w900, letterSpacing: 1.5)),
          ],
        ),
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────
// BEV 오버레이 — 도시정보 결합 (Tesla-style 단안 카메라 + signal/VDS/TAAS)
// ─────────────────────────────────────────────────────────────────

class _BevToggleChip extends StatelessWidget {
  final bool active;
  final VoidCallback onTap;
  const _BevToggleChip({required this.active, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        height: 40,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        decoration: BoxDecoration(
          color: active ? _accent.withValues(alpha: 0.30) : _surface.withValues(alpha: 0.80),
          border: Border.all(
            color: active ? _accent : _muted.withValues(alpha: 0.5),
            width: 2,
          ),
          borderRadius: BorderRadius.circular(20),
          boxShadow: active ? [
            BoxShadow(color: _accent.withValues(alpha: 0.45), blurRadius: 14),
          ] : null,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.grid_view_rounded, size: 18,
                 color: active ? _accent : _muted),
            const SizedBox(width: 8),
            Text(active ? 'BEV ON' : 'BEV',
                 style: TextStyle(
                   color: active ? _accent : _muted,
                   fontSize: 14, fontWeight: FontWeight.w800,
                   letterSpacing: 1.2,
                 )),
          ],
        ),
      ),
    );
  }
}

class _BevPanel extends StatefulWidget {
  final Map<String, dynamic>? bev;
  final Map<String, dynamic>? fusion;
  final bool demoMode;            // ★ true 면 DEMO 시나리오 표시
  final String? scenarioLabel;    // 활성 시나리오 명 (DEMO 모드일 때만)
  final VoidCallback? onToggleDemo;
  final bool fillScreen;          // ★ true: Tesla 모니터 모드 (Expanded 부모, 큰 화면)
  const _BevPanel({this.bev, this.fusion, this.demoMode = false, this.scenarioLabel, this.onToggleDemo, this.fillScreen = false});

  @override
  State<_BevPanel> createState() => _BevPanelState();
}

class _BevPanelState extends State<_BevPanel>
    with SingleTickerProviderStateMixin {
  late Ticker _ticker;
  double _t = 0;

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
    _ticker = Ticker((d) {
      final now = d.inMilliseconds / 1000.0;
      // FPS 계산 — 최근 0.5초 frame 카운트 / 0.5
      _frameTimes.add(now);
      while (_frameTimes.isNotEmpty && now - _frameTimes.first > 0.5) {
        _frameTimes.removeAt(0);
      }
      _fps = _frameTimes.length * 2.0;  // 0.5초 윈도우 → ×2
      setState(() { _t = now; });
    })..start();
  }

  @override
  void dispose() {
    _ticker.dispose();
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
          child: SizedBox.expand(
            child: CustomPaint(
              size: Size.infinite,
              painter: _Bev3DVoxelPainter(bev: widget.bev, t: _t, zoom: _zoom, yawDeg: _yawDeg, fps: _fps),
            ),
          ),
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
            if (widget.fusion != null) _CityInfoLine(fusion: widget.fusion!),
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
          if (widget.fusion != null) _CityInfoLine(fusion: widget.fusion!),
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
  const _CityInfoLine({required this.fusion});
  @override
  Widget build(BuildContext context) {
    final src = fusion['sources'] as Map<String, dynamic>?;
    String sigState = '?', vdsKmh = '?', taas = '?';
    try {
      final sig = src?['signal']?['body']?['items']?['item']?['stPdsgSttsNm'];
      if (sig is String) sigState = sig.contains('Stop') ? '정지' : '진행';
      final vds = src?['vds']?['list'];
      if (vds is List && vds.isNotEmpty) {
        final v = vds[0];
        if (v is Map && v['speed'] != null) vdsKmh = '${v['speed']}km/h';
      }
      final acc = src?['accidents_history'];
      if (acc is List) taas = '${acc.length}';
    } catch (_) {}
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(children: [
        Icon(Icons.traffic, size: 11, color: _accent),
        const SizedBox(width: 3),
        Text(sigState, style: const TextStyle(color: _text, fontSize: 10)),
        const SizedBox(width: 8),
        Icon(Icons.speed, size: 11, color: _accent),
        const SizedBox(width: 3),
        Text(vdsKmh, style: const TextStyle(color: _text, fontSize: 10)),
        const SizedBox(width: 8),
        Icon(Icons.warning_amber, size: 11, color: _warn),
        const SizedBox(width: 3),
        Text('TAAS $taas', style: const TextStyle(color: _text, fontSize: 10)),
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
    // 거리에 따른 perspective shrink (far → smaller)
    final perspective = 1.0 / (1.0 + rz * 0.012);
    // 캔버스 fit — 가로 36m (-18~18), 세로 60m forward · 사용자 zoom 적용
    final scaleX = (w - 24) / 36.0 * zoom;
    final scaleZ = (h - 70) / 60.0 * zoom;
    // 화면 X: 가로 perspective shrink + rx
    final screenX = w / 2 + rx * scaleX * perspective;
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
        (color.red * 1.3).clamp(0, 255).round(),
        (color.green * 1.3).clamp(0, 255).round(),
        (color.blue * 1.3).clamp(0, 255).round(),
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
        (color.red * 0.65).round(),
        (color.green * 0.65).round(),
        (color.blue * 0.65).round(),
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
    final lightCol = Color.fromRGBO((color.red * 1.25).clamp(0,255).round(),
                                     (color.green * 1.25).clamp(0,255).round(),
                                     (color.blue * 1.25).clamp(0,255).round(), 0.92);
    final darkCol = Color.fromRGBO((color.red * 0.55).round(),
                                    (color.green * 0.55).round(),
                                    (color.blue * 0.55).round(), 0.85);

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
      Paint()..color = Color.fromRGBO(color.red, color.green, color.blue, 0.92));
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

    // 8) 횡단보도 zebra — 4방향
    final zebraPaint = Paint()..color = const Color(0xFFEEF0F4);
    Path zebra(double x1, double z1, double x2, double z2) =>
        rectPath(x1, z1, x2, z2);
    // ego 진입 직전 (z=24~26m)
    for (int i = 0; i < 8; i++) {
      final lx = -5.5 + i * 1.4;
      canvas.drawPath(zebra(lx, 24.5, lx + 0.7, 25.7), zebraPaint);
    }
    // 교차로 너머 (z=30~32m)
    for (int i = 0; i < 8; i++) {
      final lx = -5.5 + i * 1.4;
      canvas.drawPath(zebra(lx, 30.3, lx + 0.7, 31.5), zebraPaint);
    }
    // 좌측 가로 횡단 (x=-7~-5.5)
    for (int i = 0; i < 5; i++) {
      final lz = 24.5 + i * 1.4;
      canvas.drawPath(zebra(-7.2, lz, -6.0, lz + 0.7), zebraPaint);
    }
    // 우측 가로 횡단
    for (int i = 0; i < 5; i++) {
      final lz = 24.5 + i * 1.4;
      canvas.drawPath(zebra(6.0, lz, 7.2, lz + 0.7), zebraPaint);
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

      // ── EGO 차량 (DEMO 시나리오 — 도로 인프라 끝나는 위치)
      _drawVoxel(canvas, size, 0, 0, 1.4, const Color(0xFF00C8FF), cx, cz);
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


class _BevPainter extends CustomPainter {
  final Map<String, dynamic>? bev;
  final Map<String, dynamic>? fusion;
  _BevPainter({this.bev, this.fusion});

  @override
  void paint(Canvas canvas, Size size) {
    final bg = Paint()..color = const Color(0xFF050A10);
    canvas.drawRRect(
      RRect.fromRectAndRadius(Offset.zero & size, const Radius.circular(8)),
      bg,
    );

    final w = size.width, h = size.height;
    // 1) 차로 가이드 점선 (수직 3개) — 깊이감
    final lanePaint = Paint()
      ..color = const Color(0x10FFFFFF)
      ..strokeWidth = 1;
    for (final cx in [w * 0.30, w * 0.50, w * 0.70]) {
      double y = 4;
      while (y < h - 4) {
        canvas.drawLine(Offset(cx, y), Offset(cx, y + 6), lanePaint);
        y += 12;
      }
    }

    // 2) 그리드 점유 (40x40 다운샘플) — 색상 ramp cyan→orange→red
    final gflat = bev?['grid_flat'];
    final gshape = bev?['grid_shape_flat'];
    if (gflat is List && gshape is List && gshape.length == 2) {
      final rows = (gshape[0] as num).toInt();
      final cols = (gshape[1] as num).toInt();
      final cellW = w / cols, cellH = h / rows;
      for (int r = 0; r < rows; r++) {
        for (int c = 0; c < cols; c++) {
          final p = ((gflat[r * cols + c] ?? 0) as num).toDouble();
          if (p < 0.08) continue;
          final t = p.clamp(0.0, 1.0);
          // EGO 가 화면 하단 → row 0 = bottom, row max = top
          final yTop = h - (r + 1) * cellH;
          final xLeft = c * cellW;
          final col = Color.fromARGB(
            (220 * t.clamp(0.4, 1.0)).round(),
            (255 * t).round(),
            (180 - 140 * t).clamp(20, 200).round(),
            (200 * (1 - t)).round(),
          );
          canvas.drawRect(
            Rect.fromLTWH(xLeft, yTop, cellW + 0.5, cellH + 0.5),
            Paint()..color = col,
          );
        }
      }
    }

    // 3) EGO 마커 (하단 중앙)
    final ego = Offset(w * 0.5, h - 8);
    canvas.drawCircle(ego, 5, Paint()..color = _accent);
    canvas.drawCircle(ego, 5, Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1
      ..color = const Color(0xFFFFFFFF));

    // 4) Hotspot 마커 + 거리
    final hotspots = bev?['hotspots'] as List?;
    if (hotspots != null) {
      final shape = bev?['shape'] as List?;
      final fineRows = shape != null ? (shape[0] as num).toInt() : 80;
      final fineCols = shape != null ? (shape[1] as num).toInt() : 80;
      for (final h0 in hotspots) {
        if (h0 is! Map) continue;
        final row = (h0['row'] as num?)?.toInt() ?? 0;
        final col = (h0['col'] as num?)?.toInt() ?? 0;
        final kind = h0['kind'] as String? ?? 'object';
        final dist = (h0['distance_m'] as num?)?.toDouble() ?? 0;
        final px = (col / (fineCols - 1)) * w;
        final py = h - (row / (fineRows - 1)) * h;
        Color color;
        switch (kind) {
          case 'occluded_shadow': color = _warn; break;
          case 'intent_prior':    color = _safe; break;
          case 'signal_shadow':   color = _accent2; break;
          default:                color = _danger;
        }
        // 외곽 box (작게)
        canvas.drawRect(
          Rect.fromCenter(center: Offset(px, py), width: 14, height: 14),
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1.5
            ..color = color,
        );
        canvas.drawCircle(Offset(px, py), 2, Paint()..color = color);
        // 거리 텍스트
        final tp = TextPainter(
          text: TextSpan(
            text: '${dist.toInt()}m',
            style: TextStyle(color: color, fontSize: 9, fontWeight: FontWeight.w700),
          ),
          textDirection: TextDirection.ltr,
        )..layout();
        var lx = px + 10;
        var ly = py - 10;
        if (lx + tp.width > w) lx = px - tp.width - 10;
        if (ly < 0) ly = 0;
        tp.paint(canvas, Offset(lx, ly));
      }
    }

    // 5) 도시정보 결합 표시 — 좌상단 작은 배지
    if (fusion != null) {
      final tp = TextPainter(
        text: const TextSpan(
          text: '도시정보 결합',
          style: TextStyle(color: _safe, fontSize: 9, fontWeight: FontWeight.w700),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          Rect.fromLTWH(4, 4, tp.width + 10, 14),
          const Radius.circular(4),
        ),
        Paint()..color = _safe.withValues(alpha: 0.15),
      );
      tp.paint(canvas, const Offset(9, 4.5));
    }
  }

  @override
  bool shouldRepaint(covariant _BevPainter oldDelegate) =>
      oldDelegate.bev != bev || oldDelegate.fusion != fusion;
}

class _CameraPlaceholder extends StatelessWidget {
  const _CameraPlaceholder();
  @override
  Widget build(BuildContext context) {
    return Container(
      color: _bg,
      child: const Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.no_photography_outlined, color: _muted, size: 56),
          SizedBox(height: 16),
          Text('카메라 권한이 필요합니다', style: TextStyle(color: _muted, fontSize: 14)),
        ]),
      ),
    );
  }
}

class _BrandLogo extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 32, height: 32,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            gradient: const RadialGradient(
              colors: [Color(0xFFD8FAFF), _accent, _accent2],
              stops: [0.0, 0.45, 1.0],
            ),
            boxShadow: [BoxShadow(color: _accent.withValues(alpha: 0.4), blurRadius: 10)],
          ),
        ),
        const SizedBox(width: 10),
        const Text(
          'AuraView',
          style: TextStyle(
            color: _text, fontSize: 17, fontWeight: FontWeight.w900, letterSpacing: 0.3,
          ),
        ),
      ],
    );
  }
}

class _CounterChip extends StatelessWidget {
  final int uploads;
  final int serverTotal;
  const _CounterChip({required this.uploads, required this.serverTotal});
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      decoration: BoxDecoration(
        color: const Color(0xCC0D1520),
        borderRadius: BorderRadius.circular(99),
        border: Border.all(color: const Color(0x4400C8FF)),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        const Icon(Icons.cloud_upload_outlined, color: _accent, size: 14),
        const SizedBox(width: 6),
        Text(
          uploads > 0 ? '내 기여 $uploads' : '서버 ${serverTotal > 0 ? serverTotal : "—"}',
          style: const TextStyle(color: _text, fontSize: 12, fontWeight: FontWeight.w700, fontFamily: 'monospace'),
        ),
      ]),
    );
  }
}

class _StatusOrb extends StatelessWidget {
  final bool online;
  final bool shadowOn;
  const _StatusOrb({required this.online, required this.shadowOn});
  @override
  Widget build(BuildContext context) {
    final color = !online ? _warn : (shadowOn ? _safe : _accent);
    return TweenAnimationBuilder(
      tween: Tween<double>(begin: 0.5, end: 1.0),
      duration: const Duration(milliseconds: 800),
      curve: Curves.easeInOut,
      builder: (_, double t, __) => Container(
        width: 14, height: 14,
        decoration: BoxDecoration(
          color: color, shape: BoxShape.circle,
          boxShadow: [BoxShadow(color: color.withValues(alpha: 0.6 * t), blurRadius: 12)],
        ),
      ),
      onEnd: () {},
    );
  }
}

/// 가려진 신호등 자동 안내 HUD — 카메라 위 상단 표시.
/// alt_signal 응답이 있고 alt_guide 가 있으면 항상 표시.
/// 평상시 (신호 HUD 없을 때) 상단 상태 카드 — 화면 텅 비는 거 방지
class _IdleStatusCard extends StatelessWidget {
  final int uploads;
  final int captures;
  final bool shadowOn;
  final String? intersectionId;
  final String? intersectionName;
  final VoidCallback? onSettingsTap;
  const _IdleStatusCard({
    required this.uploads,
    required this.captures,
    required this.shadowOn,
    this.intersectionId,
    this.intersectionName,
    this.onSettingsTap,
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
                  ? '근접 교차로 자동 감지 · alt_signal API 활성'
                  : (shadowOn ? '엣지 voxel · 위험 장면만 자동 업로드' : '데모 모드는 BEV 패널 LIVE↔DEMO 토글로 전환'),
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
        const SizedBox(width: 12),
        // 설정 버튼 (눈에 띄게)
        GestureDetector(
          onTap: onSettingsTap,
          behavior: HitTestBehavior.opaque,
          child: Container(
            width: 38, height: 38,
            decoration: BoxDecoration(
              color: _accent.withValues(alpha: 0.15),
              border: Border.all(color: _accent.withValues(alpha: 0.50), width: 1.2),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(Icons.tune, color: _accent, size: 20),
          ),
        ),
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
                  // 신호 아이콘 (정지/주행)
                  Container(
                    width: 38, height: 38,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: iconBg.withValues(alpha: 0.20),
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: iconBg.withValues(alpha: 0.60)),
                    ),
                    child: Text(iconLabel, style: const TextStyle(fontSize: 20)),
                  ),
                  const SizedBox(width: 10),
                  // 교차로명 + 상태
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          widget.intersectionName.isEmpty ? '근접 교차로 자동 감지 대기' : widget.intersectionName,
                          maxLines: 1, overflow: TextOverflow.ellipsis,
                          style: const TextStyle(color: Color(0xFFE2EAF5), fontSize: 13.5, fontWeight: FontWeight.w800),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          '$state' +
                          (remain != null ? ' · 남은 ${remain}초' : '') +
                          ' · risk $risk',
                          style: TextStyle(color: mainColor, fontSize: 10.5, fontFamily: 'monospace', fontWeight: FontWeight.w700, letterSpacing: 0.5),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              if (guide.isNotEmpty) ...[
                const SizedBox(height: 10),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 9),
                  decoration: BoxDecoration(
                    color: Colors.black.withValues(alpha: 0.32),
                    borderRadius: BorderRadius.circular(8),
                    border: Border(left: BorderSide(color: mainColor, width: 3)),
                  ),
                  child: Text(
                    guide,
                    style: const TextStyle(color: Color(0xFFE2EAF5), fontSize: 12.5, height: 1.35, fontWeight: FontWeight.w600),
                  ),
                ),
              ],
              if (action.isNotEmpty) ...[
                const SizedBox(height: 6),
                Text(
                  '권고 · $action',
                  style: TextStyle(color: mainColor.withValues(alpha: 0.85), fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 0.3),
                ),
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

class _PrimaryActionPill extends StatelessWidget {
  final bool shadowOn;
  final VoidCallback onTap;
  final VoidCallback onLongPress;
  const _PrimaryActionPill({required this.shadowOn, required this.onTap, required this.onLongPress});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      onLongPress: onLongPress,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 250),
        padding: const EdgeInsets.symmetric(horizontal: 36, vertical: 16),
        decoration: BoxDecoration(
          gradient: shadowOn
              ? const LinearGradient(colors: [Color(0xFFFF3B3B), Color(0xFFB71C1C)])
              : const LinearGradient(colors: [_accent, _accent2]),
          borderRadius: BorderRadius.circular(99),
          boxShadow: [
            BoxShadow(
              color: (shadowOn ? _danger : _accent).withValues(alpha: 0.45),
              blurRadius: 28, offset: const Offset(0, 6),
            ),
          ],
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(shadowOn ? Icons.stop_rounded : Icons.play_arrow_rounded,
                 size: 28, color: shadowOn ? Colors.white : _bg),
            const SizedBox(width: 10),
            Text(
              shadowOn ? '정지' : '시작',
              style: TextStyle(
                color: shadowOn ? Colors.white : _bg,
                fontSize: 18, fontWeight: FontWeight.w900, letterSpacing: 0.6,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _OpenSheetHandle extends StatelessWidget {
  final VoidCallback onTap;
  const _OpenSheetHandle({required this.onTap});
  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 18),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Container(
            width: 38, height: 4,
            decoration: BoxDecoration(
              color: _muted.withValues(alpha: 0.5), borderRadius: BorderRadius.circular(99),
            ),
          ),
          const SizedBox(height: 4),
          Text('스와이프 / 탭으로 상세',
              style: TextStyle(color: _muted.withValues(alpha: 0.7), fontSize: 10, letterSpacing: 1.5)),
        ]),
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────
// Detail bottom sheet
// ─────────────────────────────────────────────────────────────────

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

          const SizedBox(height: 22),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: _surface2,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: _accent.withValues(alpha: 0.18)),
            ),
            child: const Row(children: [
              Icon(Icons.shield_outlined, color: _safe, size: 18),
              SizedBox(width: 10),
              Expanded(
                child: Text(
                  '업로드 시 얼굴·번호판 자동 마스킹 후 저장됩니다.\n원본은 즉시 폐기 · 디바이스 ID는 가명화됩니다.',
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
