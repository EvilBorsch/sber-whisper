ifeq ($(OS),Windows_NT)
  PYTHON := python
  COPY_SCRIPT := powershell -ExecutionPolicy Bypass -File scripts/copy-artifacts.ps1
  CLEAN_CMD := powershell -Command "if (Test-Path dist) { Remove-Item -Recurse -Force dist }; if (Test-Path node_modules) { Remove-Item -Recurse -Force node_modules }; if (Test-Path src-tauri/target) { Remove-Item -Recurse -Force src-tauri/target }"
else
  PYTHON := python3.11
  COPY_SCRIPT := bash scripts/copy-artifacts.sh
  CLEAN_CMD := rm -rf dist node_modules src-tauri/target
endif

.PHONY: setup dev release release-win release-win-gpu release-mac gpu-sidecar-win clean test

setup:
	npm install
	$(PYTHON) -m pip install -r python/requirements.txt

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

release-win-gpu:
	cmd /c scripts\\windows-build-gpu-portable.cmd

gpu-sidecar-win:
	powershell -ExecutionPolicy Bypass -File scripts/build-sidecar.ps1 -Platform windows -Variant gpu

release-mac:
	bash scripts/build-sidecar.sh
	npm run tauri build -- --bundles dmg
	$(COPY_SCRIPT) macos

test:
	npm run test
	$(PYTHON) -m unittest tests/python/test_sidecar.py

clean:
	$(CLEAN_CMD)
