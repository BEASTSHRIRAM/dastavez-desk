# Dastavez Desk: web app

Next.js (App Router), Tailwind CSS 4, GSAP, React Three Fiber, Zod. See the [root README](../README.md) for setup,
configuration, the workflow and the security model.

```bash
npm install
cp .env.example .env.local     # NEXT_PUBLIC_API_URL, default http://localhost:8000
npm run dev                    # http://localhost:3000
npx tsc --noEmit               # type-check
npm run build                  # production build
```

Notes for working here:

- The app is client-driven (token auth, microphone, WebGL), so Cache Components is turned off in `next.config.ts`.
- Everything the agent returns is rendered through `src/lib/manifest.ts`, a strict schema with a closed list of
  components. Add a component there and in `features/desk/ManifestView.tsx`, never render server-provided markup.
- 3D lives in `src/components/scene/`. It falls back to a static drawing for reduced motion, a stored "Reduce 3D"
  preference, or no WebGL.
