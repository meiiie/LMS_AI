# Quickstart: Desktop ADE Activation

1. Start Wiii Desktop without a managed account.
2. Confirm the primary action is `Công việc mới`.
3. Create work for a local folder with a goal and one acceptance criterion.
4. Confirm the task card appears before the agent session opens.
5. Confirm Neko uses the Task/Run binding and its transcript remains usable.
6. Return to Wiii work and confirm Run status is outside the transcript.
7. Open Neko Chill directly and confirm `Phiên mới` still works.
8. Reload and confirm work plus execution binding hydrate without duplicate launch.

```powershell
cd wiii-desktop
npx vitest run src/__tests__/ade
npx vitest run src/__tests__/neko-chill
npx tsc --noEmit
npm run build
```
