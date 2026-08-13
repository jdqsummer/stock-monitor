# OpenHarness Upstream Manifest

- Upstream: https://github.com/HKUDS/OpenHarness
- Vendored commit SHA: 9b2efd795c6aa09f88b0c257d269a9e518da6ae7
- Vendored date: 2026-08-13
- Scope: `src/openharness/`（不含 ohmo/frontend/scripts/tests）

## 本地改动清单（应为空）
- （无）

## 更新上游流程
1. 覆盖 `vendor/openharness/` 为新版 `src/openharness/`
2. `git diff vendor/` 做冲突检查
3. 逐条复核"本地改动清单"
