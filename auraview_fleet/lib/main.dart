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
  Map<String, dynamic>? _bev;          // 로컬 voxelize 결과
  Map<String, dynamic>? _serverBev;    // /occupancy/demo class_grid_flat (Tesla-style 객체 형상)
  Map<String, dynamic>? _fusion;
  Map<String, dynamic>? _altSignal;       // /signals/{iid}/alternate 응답
  String? _autoIntersectionId;            // GPS 기반 자동 감지 교차로
  String? _autoIntersectionName;
  Timer? _bevTimer;
  Timer? _scnRotateTimer;
  List<double>? _prevFrameGray;  // motion diff 용 이전 프레임

  // BEV 시나리오 자동 순환 (3초 주기) — 4 시나리오
  static const _scnList = ['truck_occlusion', 'motorcycle_blindspot', 'signal_occlusion', 'rainy_intersection'];
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

  /// 카메라 프레임 → 클라이언트(엣지) voxel 직접 생성. 서버 호출 X.
  /// 도시정보 결합만 가벼운 GET /fusion (옵션).
  Future<void> _fetchBev() async {
    if (_cam != null && _cam!.value.isInitialized && !_cam!.value.isTakingPicture) {
      try {
        final shot = await _cam!.takePicture();
        final bytes = await shot.readAsBytes();
        if (!kIsWeb) {
          try { final f = File(shot.path); if (await f.exists()) await f.delete(); } catch (_) {}
        }
        final voxel = _voxelizeOnDevice(bytes);
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

    // Tesla-style 객체 형상 BEV — /occupancy/demo class_grid_flat 받기
    try {
      final scn = _scnList[_scnIdx % _scnList.length];
      final r = await http.get(Uri.parse('$kApiBase/occupancy/demo?scenario=$scn'))
          .timeout(const Duration(seconds: 6));
      if (r.statusCode == 200) {
        final body = jsonDecode(r.body) as Map<String, dynamic>;
        if (mounted) setState(() => _serverBev = body);
      }
    } catch (_) {}
  }

  /// voxel grid 의 신호등 영역 (멀리·중앙) 점유율을 0~1 occlusion_score 로 변환.
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

      // 2) 수직 에지 — 위 cell vs 현재 cell 차이 (객체 윤곽 위쪽 검출)
      // + 좌우 에지 — 옆 cell 과 차이 (객체 측면)
      // + motion diff — 이전 프레임과 차이 (움직임)
      final flat = List<double>.filled(ROWS * COLS, 0.0);
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
          // 결합 — 수직 에지 가중치 가장 크게 (도로 위 객체)
          final occ = (vEdge * 3.0 + hEdge * 1.2 + motion * 2.5).clamp(0.0, 1.0);
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

    // BEV 자동 시작 (5초 주기)
    _fetchBev();
    _bevTimer = Timer.periodic(const Duration(seconds: 5), (_) => _fetchBev());

    // 시나리오 자동 순환 (8초 주기) — 4종 BEV demo 회전
    _scnRotateTimer = Timer.periodic(const Duration(seconds: 8), (_) {
      _scnIdx = (_scnIdx + 1) % _scnList.length;
      _fetchBev();
    });

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
            // 카메라 풀스크린
            if (_cam != null && _cam!.value.isInitialized)
              _FullCameraPreview(controller: _cam!)
            else
              const _CameraPlaceholder(),

            // 비네트
            Container(
              decoration: const BoxDecoration(
                gradient: RadialGradient(
                  center: Alignment.center, radius: 1.0,
                  colors: [Color(0x00000000), Color(0xCC000000)],
                  stops: [0.55, 1.0],
                ),
              ),
            ),

            // 캡처 펄스 링
            AnimatedBuilder(
              animation: _pulseAnim,
              builder: (_, __) {
                if (_pulseAnim.value == 0) return const SizedBox.shrink();
                final t = _pulseAnim.value;
                return IgnorePointer(
                  child: Center(
                    child: Container(
                      width: 200 + 240 * t,
                      height: 200 + 240 * t,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        border: Border.all(
                          color: _safe.withValues(alpha: (1 - t) * 0.85),
                          width: 3,
                        ),
                        boxShadow: [
                          BoxShadow(
                            color: _safe.withValues(alpha: (1 - t) * 0.4),
                            blurRadius: 28,
                          ),
                        ],
                      ),
                    ),
                  ),
                );
              },
            ),

            // 상단 단일 status 배지 — 모든 정보 통합
            SafeArea(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(14, 12, 14, 0),
                child: _UnifiedStatusBar(
                  shadowOn: _shadowOn,
                  uploads: _uploads,
                  online: _serverError.isEmpty,
                  pos: _pos,
                  onSettingsTap: _openDetailSheet,
                ),
              ),
            ),

            // BEV — 우하단 (Tesla 식 mini voxel · 항상 ON)
            // 서버 /occupancy/demo (class_grid_flat) 우선 사용 — 객체 형상 클러스터 표시
            Positioned(
              right: 12, bottom: 110,
              child: _BevPanel(bev: _serverBev ?? _bev, fusion: _fusion),
            ),

            // ★ HUD: 가려진 신호등 자동 안내 — alt_signal 응답 있을 때 표시
            if (_altSignal != null)
              Positioned(
                top: 78, left: 12, right: 12,
                child: _SignalHud(
                  altSignal: _altSignal!,
                  intersectionName: _autoIntersectionName ??
                      (_intersectionId != null ? '교차로 $_intersectionId' : ''),
                  pulse: _lastReason == 'signal_occluded',
                ),
              ),

            // 자동 캡처 펄스 (캡처 직후 잠깐 노출) — 컨셉 한글 라벨
            if (_shadowOn && _lastReason != 'ok' && _lastReason != 'idle')
              Positioned(
                top: 144, left: 0, right: 0,
                child: Center(child: _LiveBadge(reason: _reasonKo(_lastReason))),
              ),

            // 하단 단일 큰 버튼 — 주행 시작 / 중지
            SafeArea(
              child: Align(
                alignment: Alignment.bottomCenter,
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 24),
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
  const _BevPanel({this.bev, this.fusion});

  @override
  State<_BevPanel> createState() => _BevPanelState();
}

class _BevPanelState extends State<_BevPanel>
    with SingleTickerProviderStateMixin {
  late Ticker _ticker;
  double _t = 0;

  @override
  void initState() {
    super.initState();
    _ticker = Ticker((d) {
      setState(() { _t = d.inMilliseconds / 1000.0; });
    })..start();
  }

  @override
  void dispose() {
    _ticker.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // 코너 오버레이 — 카메라 가리지 않도록 200x200 정사각형
    const panelW = 200.0;
    return Container(
      width: panelW,
      padding: const EdgeInsets.all(6),
      decoration: BoxDecoration(
        color: _bg.withValues(alpha: 0.88),
        border: Border.all(color: _accent.withValues(alpha: 0.55), width: 1.5),
        borderRadius: BorderRadius.circular(12),
        boxShadow: [BoxShadow(color: _accent.withValues(alpha: 0.30), blurRadius: 14)],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(children: [
            Icon(Icons.view_in_ar, size: 12, color: _accent),
            const SizedBox(width: 4),
            Text('BEV · 3D VOXEL',
                 style: TextStyle(color: _accent, fontSize: 9,
                                  fontWeight: FontWeight.w800, letterSpacing: 1.5)),
            const Spacer(),
            Container(
              width: 6, height: 6,
              decoration: BoxDecoration(
                color: _safe, shape: BoxShape.circle,
                boxShadow: [BoxShadow(color: _safe, blurRadius: 6)],
              ),
            ),
          ]),
          const SizedBox(height: 4),
          AspectRatio(
            aspectRatio: 1.0,
            child: ClipRRect(
              borderRadius: BorderRadius.circular(6),
              child: Container(
                color: const Color(0xFF04080E),
                child: CustomPaint(
                  size: const Size.square(panelW - 12),
                  painter: _Bev3DVoxelPainter(bev: widget.bev, t: _t),
                ),
              ),
            ),
          ),
          const SizedBox(height: 4),
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
  _Bev3DVoxelPainter({this.bev, required this.t});

  // 3D 점 → 2D 화면 (1-point perspective)
  Offset _project(double x, double y, double z, double cx, double cz, Size size) {
    // 카메라 좌표계로 변환: 카메라가 (cx, 12, cz) 에서 (0, 0, 18) 보고 있다고 가정
    // 단순화: 회전 행렬 없이 isometric-perspective 혼합
    final w = size.width, h = size.height;
    final dx = x - cx;
    final dz = z - cz;
    // 거리에 따른 perspective 축소
    final dist = math.sqrt(dx * dx + dz * dz) + 0.001;
    final scale = 6.0 / (dist * 0.45 + 4);
    // 화면 중심 + 투영
    final screenX = w / 2 + dx * scale * 6;
    final screenY = h * 0.62 - y * scale * 4 - dz * scale * 1.3;
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
    canvas.drawRect(Offset.zero & size, Paint()..color = const Color(0xFF04080E));

    // 자동 회전 카메라 (15초 주기)
    final theta = t * 0.4;
    final cx = math.cos(theta) * 14;
    final cz = math.sin(theta) * 14 + 8;

    // ── 도로 그리드 (40m × 40m, 1m cell) — 짙은 시안 라인
    final gridPaint = Paint()
      ..color = const Color.fromRGBO(0, 60, 120, 0.5)
      ..strokeWidth = 0.5;
    for (int g = -20; g <= 20; g += 2) {
      final p1 = _project(g.toDouble(), 0, 0, cx, cz, size);
      final p2 = _project(g.toDouble(), 0, 40, cx, cz, size);
      canvas.drawLine(p1, p2, gridPaint);
    }
    for (int g = 0; g <= 40; g += 2) {
      final p1 = _project(-20, 0, g.toDouble(), cx, cz, size);
      final p2 = _project(20,  0, g.toDouble(), cx, cz, size);
      canvas.drawLine(p1, p2, gridPaint);
    }

    // ── EGO 차량 (시안 박스, 원점)
    _drawVoxel(canvas, size, 0, 0, 1.6, const Color(0xFF00C8FF), cx, cz);

    // ── voxel grid — 클래스 인식 (class_grid_flat) 우선, 없으면 heatmap 폴백
    final flat = bev?['grid_flat'];
    final shape = bev?['grid_shape_flat'];
    final classFlat = bev?['class_grid_flat'];
    if (flat is List && shape is List && shape.length == 2) {
      final rows = (shape[0] as num).toInt();
      final cols = (shape[1] as num).toInt();
      final hasClass = classFlat is List && classFlat.length == rows * cols;

      // Tesla-style 객체별 색상 (web 와 동일)
      const classColors = <int, Color>{
        1: Color(0xFF3A8FFF),  // vehicle/truck/bus
        2: Color(0xFFFF8C00),  // motorcycle
        3: Color(0xFF7C3AED),  // occlusion
        4: Color(0xFF00D8FF),  // pedestrian
        5: Color(0xFFFF5A5A),  // signal
      };
      const classHeights = <int, double>{1: 1.6, 2: 1.0, 3: 0.4, 4: 1.5, 5: 4.2};

      // 화면 가까운 voxel 부터 그리도록 z 큰 것 먼저 (back to front)
      final cells = <List<num>>[];  // [r, c, p, cls]
      for (int r = 0; r < rows; r++) {
        for (int cc = 0; cc < cols; cc++) {
          final p = ((flat[r * cols + cc] ?? 0) as num).toDouble();
          if (p < 0.15) continue;
          final cls = hasClass ? ((classFlat[r * cols + cc] as num?)?.toInt() ?? 0) : 0;
          if (hasClass && cls == 0) continue;  // class 모드: free space 스킵
          cells.add([r, cc, p, cls]);
        }
      }
      cells.sort((a, b) => (b[0] as num).compareTo(a[0] as num));  // 멀리 → 가까이

      for (final cell in cells) {
        final r = (cell[0] as num).toInt();
        final cc = (cell[1] as num).toInt();
        final p = (cell[2] as num).toDouble();
        final cls = (cell[3] as num).toInt();
        final x = (cc - cols / 2 + 0.5) * (40.0 / cols);
        final z = r * (40.0 / rows);

        Color col;
        double height;
        if (hasClass && cls > 0) {
          col = classColors[cls] ?? const Color(0xFF888888);
          height = classHeights[cls] ?? 1.0;
          if (cls == 4) {
            // 보행자: voxel 대신 작은 시안 원기둥 (구 + 라인) — 사람 모양 강조
            _drawPedestrianMarker(canvas, size, x, z, cx, cz);
            continue;
          }
          if (cls == 5) {
            // 신호등: 가는 폴 + 빨간 라이트
            _drawSignalMarker(canvas, size, x, z, cx, cz);
            continue;
          }
        } else {
          height = (p * 5.0).clamp(0.3, 5.0);
          if (p < 0.4) {
            col = Color.lerp(const Color(0xFF005580), const Color(0xFFFFB020), p / 0.4)!;
          } else {
            col = Color.lerp(const Color(0xFFFFB020), const Color(0xFFFF3B3B), (p - 0.4) / 0.6)!;
          }
        }
        _drawVoxel(canvas, size, x, z, height, col, cx, cz);
      }

      // 시나리오 라벨 — 좌측 상단 작은 칩
      final scn = bev?['scenario'];
      if (scn is Map && scn['title'] is String) {
        final tp = TextPainter(
          text: TextSpan(text: scn['title'] as String,
              style: const TextStyle(color: Color(0xFFE2EAF5), fontSize: 8.5, fontWeight: FontWeight.w800)),
          textDirection: TextDirection.ltr,
        )..layout(maxWidth: size.width - 16);
        final bgRect = Rect.fromLTWH(6, 6, tp.width + 10, tp.height + 6);
        canvas.drawRRect(
          RRect.fromRectAndRadius(bgRect, const Radius.circular(6)),
          Paint()..color = const Color(0xCC0D1520),
        );
        tp.paint(canvas, const Offset(11, 9));
      }
    }

    // ── hotspot 마커 (구체 + 빔)
    final hs = bev?['hotspots'];
    if (hs is List) {
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
      old.bev != bev || old.t != t;
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
