@echo off
setlocal
call "%~dp0windows-vs-env.cmd"
if errorlevel 1 exit /b %errorlevel%
cd /d "%~dp0.."
call npm run build
if errorlevel 1 exit /b %errorlevel%
cargo build --manifest-path src-tauri/Cargo.toml --release --features tauri/custom-protocol --bin overlay-lifecycle-regression
if errorlevel 1 exit /b %errorlevel%
node scripts/test-overlay-lifecycle.mjs
exit /b %errorlevel%
