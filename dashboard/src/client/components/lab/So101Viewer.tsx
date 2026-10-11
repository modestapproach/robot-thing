/**
 * SO-101 digital-twin viewer: the official URDF + STL meshes (TheRobotStudio/SO-ARM100,
 * Apache-2.0) loaded with urdf-loader into three.js, animated with the joint angles the
 * MuJoCo physics recorded for a move (or encoder telemetry from the real arm).
 * The board is drawn at the twin's *believed* pose; the tool path is the recorded one.
 */
import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import URDFLoader, { type URDFRobot } from 'urdf-loader';
import { fmt, type Trajectory, type TwinVersion } from '@/client/lib/autolab';

const URDF_URL = '/so101/so101_new_calib.urdf';
const DEFAULT_JOINTS = ['shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper'];
const BOARD_W = 0.2, BOARD_H = 0.15;

function checkerTexture(): THREE.Texture {
  const c = document.createElement('canvas');
  c.width = 800; c.height = 600; // 8 x 6 squares of 25 mm, like fixtures/board_a4.json
  const g = c.getContext('2d')!;
  for (let i = 0; i < 8; i++) for (let j = 0; j < 6; j++) {
    g.fillStyle = (i + j) % 2 ? '#1d2224' : '#ece6d2';
    g.fillRect(i * 100, j * 100, 100, 100);
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export function So101Viewer({ traj, board, height = 300 }: { traj: Trajectory; board?: TwinVersion['calibration_parameters']; height?: number }) {
  const host = useRef<HTMLDivElement>(null);
  const frameRef = useRef(0);
  const playingRef = useRef(true);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const n = traj.q_rad?.length ?? 0;
  const joints = (traj as any).joints ?? DEFAULT_JOINTS;

  useEffect(() => { playingRef.current = playing; }, [playing]);

  useEffect(() => {
    const el = host.current;
    if (!el || !n) return;
    frameRef.current = 0; setFrame(0); setPlaying(true);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(32, 1, 0.01, 10);
    scene.add(new THREE.HemisphereLight(0xdfe9e6, 0x101416, 1.6));
    const key = new THREE.DirectionalLight(0xffffff, 2.2);
    key.position.set(-0.4, 0.9, 0.5);
    scene.add(key);

    // Robot frame (z-up, metres) inside three's y-up world.
    const base = new THREE.Group();
    base.rotation.x = -Math.PI / 2;
    scene.add(base);
    const grid = new THREE.GridHelper(0.8, 16, 0x2c3c3b, 0x1b2627);
    grid.position.set(0.12, 0, 0);
    scene.add(grid);

    if (board) {
      const th = (board.rotation_deg * Math.PI) / 180, s = board.scale;
      const cx = board.offset_mm.x / 1000 + s * (Math.cos(th) * BOARD_W / 2 - Math.sin(th) * BOARD_H / 2);
      const cy = board.offset_mm.y / 1000 + s * (Math.sin(th) * BOARD_W / 2 + Math.cos(th) * BOARD_H / 2);
      const plane = new THREE.Mesh(new THREE.PlaneGeometry(BOARD_W * s, BOARD_H * s), new THREE.MeshStandardMaterial({ map: checkerTexture(), roughness: 0.9 }));
      plane.position.set(cx, cy, 0.0015);
      plane.rotation.z = th;
      base.add(plane);
    }
    const tgt = traj.target_base_mm;
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.006, 0.0012, 8, 32), new THREE.MeshBasicMaterial({ color: 0xf0705f }));
    ring.position.set(tgt.x / 1000, tgt.y / 1000, 0.004);
    base.add(ring);

    const path = traj.pos_mm.map((fr) => { const p = fr[fr.length - 1]; return new THREE.Vector3(p[0] / 1000, p[1] / 1000, p[2] / 1000); });
    const pathGeom = new THREE.BufferGeometry().setFromPoints(path);
    const pathLine = new THREE.Line(pathGeom, new THREE.LineBasicMaterial({ color: 0xb59cf5 }));
    base.add(pathLine);

    let robot: URDFRobot | null = null;
    const loader = new URDFLoader();
    loader.load(URDF_URL, (r) => { robot = r; base.add(r); setStatus('ready'); apply(0); }, undefined, () => setStatus('error'));

    const apply = (f: number) => {
      const q = traj.q_rad[Math.min(f, n - 1)] ?? [];
      if (robot) joints.forEach((name: string, i: number) => { if (q[i] !== undefined && robot!.joints[name]) robot!.setJointValue(name, q[i]); });
      pathGeom.setDrawRange(0, Math.min(f, n - 1) + 1);
    };

    // Frame the whole arm and board: look at the board centre from front-left, slightly above.
    const target = new THREE.Vector3(0.13, 0.09, 0.0);
    camera.position.set(-0.22, 0.42, 0.62);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.copy(target);
    controls.enableDamping = true;
    controls.minDistance = 0.2; controls.maxDistance = 1.5;

    const resize = () => {
      const w = el.clientWidth, h = el.clientHeight;
      renderer.setSize(w, h, false);
      renderer.domElement.style.width = '100%'; renderer.domElement.style.height = '100%';
      camera.aspect = w / Math.max(1, h); camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el); resize();

    const dt = Math.max(0.016, (traj.t[1] ?? 0.04) - (traj.t[0] ?? 0));
    let last = performance.now(), acc = 0, raf = 0, hold = 0;
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const step = (now - last) / 1000; last = now;
      if (playingRef.current) {
        acc += step;
        while (acc >= dt) {
          acc -= dt;
          if (frameRef.current >= n - 1) { hold += dt; if (hold > 0.8) { frameRef.current = 0; hold = 0; } }
          else frameRef.current += 1;
        }
        setFrame(frameRef.current);
      }
      apply(frameRef.current);
      controls.update();
      renderer.render(scene, camera);
    };
    raf = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf); ro.disconnect(); controls.dispose();
      scene.traverse((o) => { const m = o as THREE.Mesh; m.geometry?.dispose?.(); const mat = m.material as THREE.Material | THREE.Material[] | undefined; (Array.isArray(mat) ? mat : mat ? [mat] : []).forEach((x) => x.dispose()); });
      renderer.dispose(); el.removeChild(renderer.domElement);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [traj._id, board?.calibration_version]);

  const f = Math.min(frame, Math.max(0, n - 1));
  const tool = traj.pos_mm[f]?.[traj.pos_mm[f].length - 1];
  return (
    <div className="grid grid-cols-1 gap-2 min-w-0">
      <div ref={host} style={{ height }} className="relative w-full min-w-0 overflow-hidden rounded-md bg-lab-bg cursor-grab active:cursor-grabbing">
        {status !== 'ready' && (
          <div className="absolute inset-0 grid place-items-center text-[12px] text-lab-faint">
            {status === 'loading' ? 'Loading SO-101 meshes…' : 'Could not load /so101/so101_new_calib.urdf'}
          </div>
        )}
      </div>
      <div className="flex items-center gap-3 font-mono text-[11px] text-lab-dim">
        <button onClick={() => setPlaying((p) => !p)} className="px-2 py-0.5 rounded border border-lab-line hover:text-lab-text">{playing ? 'pause' : 'play'}</button>
        <input type="range" min={0} max={Math.max(0, n - 1)} value={f}
          onChange={(e) => { setPlaying(false); frameRef.current = Number(e.target.value); setFrame(frameRef.current); }}
          className="flex-1 min-w-0 accent-[var(--color-simulated)]" />
        <span className="tabular w-14 text-right">{fmt(traj.t[f], 2)} s</span>
        {tool && <span className="tabular hidden sm:inline">tool z {fmt(tool[2], 1)} mm</span>}
      </div>
    </div>
  );
}
