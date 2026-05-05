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

import 'package:camera/camera.dart';
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
  Map<String, dynamic>? _bev;
  Map<String, dynamic>? _fusion;
  Timer? _bevTimer;

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

  Future<void> _fetchBev() async {
    try {
      final r = await http.get(Uri.parse('$kApiBase/occupancy/demo'))
          .timeout(const Duration(seconds: 6));
      if (r.statusCode == 200) {
        final body = jsonDecode(r.body) as Map<String, dynamic>;
        if (mounted) setState(() => _bev = body);
      }
    } catch (_) {}
    final iid = _intersectionId;
    if (iid != null && iid.isNotEmpty) {
      try {
        final r = await http.get(Uri.parse('$kApiBase/fusion/intersection/$iid'))
            .timeout(const Duration(seconds: 6));
        if (r.statusCode == 200) {
          final body = jsonDecode(r.body) as Map<String, dynamic>;
          if (mounted) setState(() => _fusion = body);
        }
      } catch (_) {}
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

  String? _classifyReason(_FrameFeat feat) {
    if (feat.entropy >= 0.75) return 'high_entropy';
    if (feat.motion >= 0.7) return 'motion_spike';
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
      return const Scaffold(
        backgroundColor: _bg,
        body: Center(child: CircularProgressIndicator(color: _accent)),
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

            // 상단 HUD
            SafeArea(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 14, 20, 0),
                child: Row(
                  children: [
                    _BrandLogo(),
                    const Spacer(),
                    _BevToggleChip(active: _bevOpen, onTap: _toggleBev),
                    const SizedBox(width: 8),
                    _CounterChip(uploads: _uploads, serverTotal: _serverTotal),
                    const SizedBox(width: 8),
                    _StatusOrb(online: _serverError.isEmpty, shadowOn: _shadowOn),
                  ],
                ),
              ),
            ),

            // BEV 오버레이 패널 — 도시정보 결합 (Tesla-style + signal/VDS/TAAS)
            if (_bevOpen)
              SafeArea(
                child: Align(
                  alignment: Alignment.topRight,
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(0, 70, 14, 0),
                    child: _BevPanel(bev: _bev, fusion: _fusion),
                  ),
                ),
              ),

            // Shadow 가동 중일 때 하단 라이브 인디케이터
            if (_shadowOn)
              Positioned(
                top: 80, left: 0, right: 0,
                child: Center(child: _LiveBadge(reason: _lastReason)),
              ),

            // 하단 메인 액션
            SafeArea(
              child: Align(
                alignment: Alignment.bottomCenter,
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 28),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      _PrimaryActionPill(
                        shadowOn: _shadowOn,
                        onTap: _toggleShadow,
                        onLongPress: _manualContribute,
                      ),
                      const SizedBox(height: 12),
                      _OpenSheetHandle(onTap: _openDetailSheet),
                    ],
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

class _BevPanel extends StatelessWidget {
  final Map<String, dynamic>? bev;
  final Map<String, dynamic>? fusion;
  const _BevPanel({this.bev, this.fusion});

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.of(context).size;
    final w = size.width.clamp(280.0, 400.0).toDouble();
    final panelW = (w * 0.85).clamp(240.0, 340.0);
    return Container(
      width: panelW,
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: _bg.withValues(alpha: 0.85),
        border: Border.all(color: _accent.withValues(alpha: 0.45)),
        borderRadius: BorderRadius.circular(14),
        boxShadow: [BoxShadow(color: _accent.withValues(alpha: 0.18), blurRadius: 16)],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(children: [
            Icon(Icons.flash_on, size: 13, color: _accent),
            const SizedBox(width: 4),
            Text('BEV · CITY-AUGMENTED',
                 style: TextStyle(color: _accent, fontSize: 10,
                                  fontWeight: FontWeight.w700, letterSpacing: 1.5)),
          ]),
          const SizedBox(height: 4),
          AspectRatio(
            aspectRatio: 1.0,
            child: ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: CustomPaint(
                size: Size.square(panelW - 16),
                painter: _BevPainter(bev: bev, fusion: fusion),
              ),
            ),
          ),
          const SizedBox(height: 6),
          if (bev != null) _BevStatLine(bev: bev!),
          if (fusion != null) _CityInfoLine(fusion: fusion!),
          const SizedBox(height: 2),
          Text(
            bev == null ? '로딩 중…' : '단안 카메라 + 도시정보 결합',
            style: const TextStyle(color: _muted, fontSize: 9, letterSpacing: 1.2),
          ),
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
