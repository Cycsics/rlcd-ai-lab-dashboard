param([ValidateSet('compile','upload','ports')][string]$Action='compile', [string]$Port='COM3')
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$cli=Join-Path $projectRoot 'work/tools/bin/arduino-cli.exe'
$config=Join-Path $projectRoot 'work/tools/arduino/arduino-cli.yaml'
$sketch=Join-Path $projectRoot 'work/rlcd_companion/firmware/rlcd_client'
$build=Join-Path $projectRoot 'work/rlcd_companion/firmware/build'
$fqbn='esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PartitionScheme=app3M_fat9M_16MB,PSRAM=opi'
if ($Action -eq 'ports') {
    & $cli --config-file $config board list
} elseif ($Action -eq 'compile') {
    if (!(Test-Path (Join-Path $sketch 'config.h'))) { throw 'Please run configure_windows.py first.' }
    & $cli --config-file $config compile --fqbn $fqbn --libraries (Join-Path $projectRoot 'work/vendor/ESP32-S3-RLCD-4.2/01_Arduino_Libraries') --build-path $build $sketch
} else {
    & $cli --config-file $config upload --fqbn $fqbn --port $Port --input-dir $build $sketch
}
if ($LASTEXITCODE -ne 0) { throw "Arduino failed with exit code $LASTEXITCODE" }
