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
    _cam?.dispose();
    _pulseAnim.dispose();
    super.dispose();
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
    _pollServer();
    Timer.periodic(const Duration(seconds: 30), (_) => _pollServer());

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
        onIntersectionChanged: (v) async {
          final sp = await SharedPreferences.getInstance();
          await sp.setString('intersection_id', v);
          if (mounted) setState(() => _intersectionId = v);
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
                    _CounterChip(uploads: _uploads, serverTotal: _serverTotal),
                    const SizedBox(width: 8),
                    _StatusOrb(online: _serverError.isEmpty, shadowOn: _shadowOn),
                  ],
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
  final ValueChanged<String> onIntersectionChanged;

  const _DetailSheet({
    required this.deviceId,
    required this.captures, required this.uploads, required this.failures,
    required this.serverTotal, required this.serverError,
    required this.intersectionId, required this.pos,
    required this.lastEntropy, required this.lastReason,
    required this.lastUploadAt,
    required this.onIntersectionChanged,
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
