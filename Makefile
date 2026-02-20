ifeq ($(OS),Windows_NT)
  PYTHON := python
  COPY_SCRIPT := powershell -ExecutionPolicy Bypass -File scripts/copy-artifacts.ps1
  CLEAN_CMD := powershell -Command "if (Test-Path dist) { Remove-Item -Recurse -Force dist }; if (Test-Path node_modules) { Remove-Item -Recurse -Force node_modules }; if (Test-Path src-tauri/target) { Remove-Item -Recurse -Force src-tauri/target }"
  GIGAAM_REF := gigaam @ git+https://github.com/salute-developers/GigaAM.git@94082238aa5cabbd4bdc28e755100a1922a90d43
else
  PYTHON := python3
  COPY_SCRIPT := bash scripts/copy-artifacts.sh
  CLEAN_CMD := rm -rf dist node_modules src-tauri/target
  GIGAAM_REF := gigaam @ git+https://github.com/salute-developers/GigaAM.git@94082238aa5cabbd4bdc28e755100a1922a90d43
endif

.PHONY: setup dev release release-win release-mac clean test

setup:
	npm install
	$(PYTHON) -m pip install -r python/requirements.txt
	$(PYTHON) -m pip install --force-reinstall --no-deps --no-cache-dir "$(GIGAAM_REF)"

dev:
	npm run tauri dev

release:
ifeq ($(OS),Windows_NT)
	$(MAKE) release-win
else
	$(MAKE) release-mac
endif

release-win:
	cmd /c scripts\\windows-tauri-build.cmd

release-mac:
	bash scripts/build-sidecar.sh
	npm run tauri build -- --bundles dmg
	$(COPY_SCRIPT) macos

test:
	npm run test
	$(PYTHON) -m unittest tests/python/test_sidecar.py

clean:
	$(CLEAN_CMD)
