"use client";

import { useMemo, useRef } from "react";
import * as THREE from "three";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { paperTexture, type Material } from "./paper";
import { SHEET, SHEET_COUNT, assembled, padded } from "./layouts";

gsap.registerPlugin(useGSAP);

export type SceneMode = "idle" | "assembling" | "done";

interface SceneProps {
  material: Material;
  mode: SceneMode;
  /** Shifts the installation sideways (world units) so text can sit beside it. */
  offsetX: number;
  intro: boolean;
}

const COBALT = new THREE.Color("#1f43d6");
const COBALT_DARK = new THREE.Color("#16318f");

function Scene({ material, mode, offsetX, intro }: SceneProps) {
  const sheets = useRef<(THREE.Mesh | null)[]>([]);
  const root = useRef<THREE.Group>(null);
  const folder = useRef<THREE.Group>(null);
  const lid = useRef<THREE.Group>(null);
  const tab = useRef<THREE.Mesh>(null);
  const timeline = useRef<gsap.core.Timeline | null>(null);
  const introduced = useRef(false);
  const previous = useRef<{ material: Material; mode: SceneMode }>({ material, mode });
  const { camera, pointer } = useThree();

  const geometry = useMemo(() => new THREE.BoxGeometry(SHEET.w, SHEET.t, SHEET.d), []);
  const edge = useMemo(() => new THREE.MeshStandardMaterial({ color: "#d8d3c4", roughness: 0.95 }), []);
  const faces = useMemo(
    () => Array.from({ length: SHEET_COUNT }, () => new THREE.MeshStandardMaterial({ roughness: 0.92, metalness: 0 })),
    [],
  );
  const folderMaterial = useMemo(() => new THREE.MeshStandardMaterial({ color: COBALT, roughness: 0.7 }), []);
  const folderBack = useMemo(() => new THREE.MeshStandardMaterial({ color: COBALT_DARK, roughness: 0.75 }), []);

  useGSAP(
    () => {
      timeline.current?.kill();
      const tl = gsap.timeline();
      timeline.current = tl;
      const meshes = sheets.current.filter(Boolean) as THREE.Mesh[];
      const poses = padded(material);
      const swapTextures = () => faces.forEach((m, i) => { m.map = paperTexture(material, i % 4); m.needsUpdate = true; });
      const assembling = mode !== "idle";
      const changedMaterial = previous.current.material !== material;
      const wasAssembled = previous.current.mode !== "idle";
      previous.current = { material, mode };

      if (!introduced.current) {
        // First reveal: sheets fall in from above and settle into the workspace arrangement.
        introduced.current = true;
        swapTextures();
        meshes.forEach((m, i) => {
          const pose = padded(material)[i];
          m.position.set(pose.p[0] + (Math.sin(i * 7) * 2), 9 + i * 0.3, pose.p[2] + Math.cos(i * 5) * 2);
          m.rotation.set(Math.sin(i) * 0.8, Math.cos(i * 2) * 1.5, Math.sin(i * 3) * 0.6);
          m.scale.setScalar(pose.s);
        });
        if (!intro) meshes.forEach((m, i) => { const p = poses[i]; m.position.set(...p.p); m.rotation.set(...p.r); });
        else {
          tl.to(meshes.map((m) => m.position), { y: (i: number) => poses[i].p[1], x: (i: number) => poses[i].p[0], z: (i: number) => poses[i].p[2], duration: 1.6, ease: "expo.out", stagger: 0.035 }, 0);
          tl.to(meshes.map((m) => m.rotation), { x: (i: number) => poses[i].r[0], y: (i: number) => poses[i].r[1], z: (i: number) => poses[i].r[2], duration: 1.8, ease: "power3.out", stagger: 0.035 }, 0);
        }
        return;
      }

      if (changedMaterial && !assembling) {
        // Workspace change: sheets lift, rearrange, and the printed pattern swaps mid-flight.
        tl.to(meshes.map((m) => m.position), { y: "+=0.9", duration: 0.35, ease: "power2.out", stagger: 0.008 }, 0)
          .call(swapTextures, [], 0.3)
          .to(meshes.map((m) => m.position), { x: (i: number) => poses[i].p[0], z: (i: number) => poses[i].p[2], duration: 1.1, ease: "power3.inOut", stagger: 0.012 }, 0.25)
          .to(meshes.map((m) => m.rotation), { x: (i: number) => poses[i].r[0], y: (i: number) => poses[i].r[1], z: (i: number) => poses[i].r[2], duration: 1.1, ease: "power3.inOut", stagger: 0.012 }, 0.25)
          .to(meshes.map((m) => m.scale), { x: (i: number) => poses[i].s, y: (i: number) => poses[i].s, z: (i: number) => poses[i].s, duration: 0.8, ease: "power2.inOut" }, 0.3)
          .to(meshes.map((m) => m.position), { y: (i: number) => poses[i].p[1], duration: 0.55, ease: "bounce.out", stagger: 0.008 }, 1.0);
        return;
      }

      if (assembling && !wasAssembled) {
        // Facts extracted: the sheets gather into one folder, then the lid closes.
        const f = folder.current!;
        const l = lid.current!;
        l.rotation.x = -1.35;
        tl.to(f.scale, { x: 1, y: 1, z: 1, duration: 0.7, ease: "back.out(1.6)" }, 0)
          .to(meshes.map((m) => m.position), { x: (i: number) => assembled(i).p[0], z: (i: number) => assembled(i).p[2], y: (i: number) => assembled(i).p[1] + 1.2, duration: 0.9, ease: "power3.inOut", stagger: 0.03 }, 0.1)
          .to(meshes.map((m) => m.rotation), { x: 0, y: (i: number) => assembled(i).r[1], z: 0, duration: 0.9, ease: "power3.inOut", stagger: 0.03 }, 0.1)
          .to(meshes.map((m) => m.scale), { x: 0.78, y: 0.78, z: 0.78, duration: 0.9, ease: "power2.inOut", stagger: 0.03 }, 0.1)
          .to(meshes.map((m) => m.position), { y: (i: number) => assembled(i).p[1], duration: 0.45, ease: "power2.in", stagger: 0.02 }, 1.1)
          .to(l.rotation, { x: 0, duration: 0.7, ease: "power3.inOut" }, 1.9);
      }
      if (mode === "done") {
        const mat = tab.current!.material as THREE.MeshStandardMaterial;
        mat.emissive = new THREE.Color("#ffffff");
        tl.fromTo(mat, { emissiveIntensity: 0 }, { emissiveIntensity: 0.7, duration: 0.35, yoyo: true, repeat: 1, ease: "sine.inOut" }, 0)
          .fromTo(folder.current!.position, { y: 0 }, { y: 0.25, duration: 0.3, yoyo: true, repeat: 1, ease: "power2.out" }, 0);
      }
      if (mode === "idle" && wasAssembled) {
        tl.to(folder.current!.scale, { x: 0, y: 0, z: 0, duration: 0.5, ease: "power2.in" }, 0)
          .to(meshes.map((m) => m.position), { x: (i: number) => poses[i].p[0], y: (i: number) => poses[i].p[1], z: (i: number) => poses[i].p[2], duration: 1.1, ease: "power3.inOut", stagger: 0.015 }, 0.2)
          .to(meshes.map((m) => m.rotation), { x: (i: number) => poses[i].r[0], y: (i: number) => poses[i].r[1], z: (i: number) => poses[i].r[2], duration: 1.1, ease: "power3.inOut" }, 0.2)
          .to(meshes.map((m) => m.scale), { x: (i: number) => poses[i].s, y: (i: number) => poses[i].s, z: (i: number) => poses[i].s, duration: 1, ease: "power2.inOut" }, 0.2);
      }
    },
    { dependencies: [material, mode], revertOnUpdate: false },
  );

  useGSAP(() => () => { timeline.current?.kill(); }, []);

  useFrame(({ clock }) => {
    const g = root.current;
    if (!g) return;
    const t = clock.getElapsedTime();
    g.rotation.y += ((Math.sin(t * 0.18) * 0.1 + pointer.x * 0.16) - g.rotation.y) * 0.04;
    g.rotation.x += ((pointer.y * -0.04) - g.rotation.x) * 0.04;
    g.position.x += (offsetX - g.position.x) * 0.06;
    camera.lookAt(0, 0.7, 0);
  });

  return (
    <>
      <hemisphereLight args={["#ffffff", "#cfc8b4", 1.15]} />
      <directionalLight
        position={[5, 9, 4]}
        intensity={2.4}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-8}
        shadow-camera-right={8}
        shadow-camera-top={8}
        shadow-camera-bottom={-8}
        shadow-bias={-0.0004}
      />
      <directionalLight position={[-6, 3, -4]} intensity={0.45} color="#9db1ff" />
      <group ref={root}>
        <mesh rotation-x={-Math.PI / 2} position-y={-0.001} receiveShadow>
          <planeGeometry args={[80, 80]} />
          <shadowMaterial opacity={0.2} />
        </mesh>
        {Array.from({ length: SHEET_COUNT }, (_, i) => (
          <mesh
            key={i}
            ref={(m) => { sheets.current[i] = m; }}
            geometry={geometry}
            material={[edge, edge, faces[i], edge, edge, edge]}
            castShadow
            receiveShadow
          />
        ))}
        <group ref={folder} scale={0}>
          <mesh position={[0, 0.045, 0]} material={folderBack} castShadow receiveShadow>
            <boxGeometry args={[SHEET.w + 0.3, 0.03, SHEET.d + 0.3]} />
          </mesh>
          <mesh position={[0, 0.25, -(SHEET.d + 0.3) / 2 + 0.015]} material={folderBack} castShadow>
            <boxGeometry args={[SHEET.w + 0.3, 0.42, 0.03]} />
          </mesh>
          <group ref={lid} position={[0, 0.46, -(SHEET.d + 0.3) / 2 + 0.03]}>
            <mesh position={[0, 0, (SHEET.d + 0.3) / 2]} material={folderMaterial} castShadow>
              <boxGeometry args={[SHEET.w + 0.3, 0.03, SHEET.d + 0.3]} />
            </mesh>
            <mesh ref={tab} position={[-0.35, 0, SHEET.d + 0.3 + 0.07]} castShadow>
              <boxGeometry args={[0.55, 0.03, 0.16]} />
              <meshStandardMaterial color="#1f43d6" roughness={0.65} />
            </mesh>
          </group>
        </group>
      </group>
    </>
  );
}

interface Props {
  material: Material;
  mode?: SceneMode;
  /** Horizontal shift as a fraction of the visible width (positive moves the installation right). */
  shift?: number;
  intro?: boolean;
  className?: string;
  label?: string;
}

export default function Installation({ material, mode = "idle", shift = 0, intro = true, className, label }: Props) {
  return (
    <div className={className} role="img" aria-label={label ?? "A procedural installation of document sheets"}>
      <Canvas
        shadows="soft"
        dpr={[1, 1.75]}
        camera={{ position: [7.5, 6.2, 9], fov: 30, near: 0.1, far: 80 }}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
        aria-hidden
      >
        <SceneWithShift material={material} mode={mode} shift={shift} intro={intro} />
      </Canvas>
    </div>
  );
}

function SceneWithShift({ material, mode, shift, intro }: { material: Material; mode: SceneMode; shift: number; intro: boolean }) {
  const viewport = useThree((s) => s.viewport);
  // Convert a fraction of the viewport into world units at the origin plane, kept modest so the scene stays composed.
  const offsetX = shift * Math.min(viewport.width, 9);
  return <Scene material={material} mode={mode} offsetX={offsetX} intro={intro} />;
}
